import json
import streamlit as st
import firebase_admin
from firebase_admin import credentials, auth
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google import genai
import os
import re
import logging

# Charger la configuration Firebase depuis une variable d'environnement
firebase_json_content = os.environ.get("firebasejson")  # Contenu du fichier JSON
if not firebase_json_content:
    st.error("La variable d'environnement 'firebasejson' n'est pas définie.")
else:
    try:
        # Charger la configuration JSON
        firebasejson = json.loads(firebase_json_content)
        
        # Initialiser Firebase avec les données de configuration
        if not firebase_admin._apps:
            cred = credentials.Certificate(firebasejson)  # Passer le dictionnaire directement
            firebase_admin.initialize_app(cred)
            #st.success("Firebase initialisé avec succès sur Heroku !")
    except json.JSONDecodeError:
        st.error("Le contenu de 'firebasejson' n'est pas un JSON valide.")
    except Exception as e:
        st.error(f"Erreur lors de l'initialisation de Firebase : {str(e)}")

# Configuration de la journalisation
logging.basicConfig(filename="app.log", level=logging.INFO, format="%(asctime)s - %(message)s")

# Charger la liste des e-mails autorisés depuis la variable d'environnement
AUTHORIZED_EMAILS = os.environ.get("AUTHORIZED_EMAILS", "").split(",")
AUTHORIZED_EMAILS = [email.strip() for email in AUTHORIZED_EMAILS if email.strip()]

# Fonction pour valider la complexité du mot de passe
def validate_password(password):
    """
    Vérifie si le mot de passe respecte les exigences :
    - Au moins une majuscule
    - Au moins une minuscule
    - Au moins un chiffre
    - Longueur minimale de 8 caractères
    """
    errors = []
    if len(password) < 8:
        errors.append("Le mot de passe doit contenir au moins 8 caractères.")
    if not re.search(r"[A-Z]", password):  # Vérifie une majuscule
        errors.append("Le mot de passe doit contenir au moins une majuscule.")
    if not re.search(r"[a-z]", password):  # Vérifie une minuscule
        errors.append("Le mot de passe doit contenir au moins une minuscule.")
    if not re.search(r"[0-9]", password):  # Vérifie un chiffre
        errors.append("Le mot de passe doit contenir au moins un chiffre.")
    return errors

# Fonction pour valider l'e-mail
def validate_email(email):
    """
    Vérifie si l'e-mail est valide.
    """
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return re.match(pattern, email) is not None

# Fonction pour l'inscription
def signup(name, email, password, confirm_password):
    try:
        # Vérifier si l'e-mail est autorisé
        if email not in AUTHORIZED_EMAILS:
            st.error("Votre e-mail n'est pas autorisé à s'inscrire.")
            logging.warning(f"Tentative d'inscription non autorisée avec l'e-mail : {email}")
            return
        
        # Vérifier si l'e-mail est valide
        if not validate_email(email):
            st.error("L'e-mail n'est pas valide.")
            return
        
        # Vérifier si les mots de passe correspondent
        if password != confirm_password:
            st.error("Les mots de passe ne correspondent pas.")
            return
        
        # Vérifier la complexité du mot de passe
        password_errors = validate_password(password)
        if password_errors:
            for error in password_errors:
                st.error(error)
            return
        
        # Créer l'utilisateur dans Firebase
        user = auth.create_user(
            email=email,
            password=password,
            display_name=name  # Ajouter le nom de l'utilisateur
        )
        st.success(f"Utilisateur {user.email} créé avec succès!")
        logging.info(f"Utilisateur inscrit avec succès : {email}")
    except auth.EmailAlreadyExistsError:
        st.error("Cet e-mail est déjà utilisé.")
        logging.warning(f"Tentative d'inscription avec un e-mail déjà utilisé : {email}")
    except Exception as e:
        st.error(f"Erreur: {e}")
        logging.error(f"Erreur lors de l'inscription : {e}")

# Fonction pour modifier le mot de passe
def update_password(email, new_password, confirm_new_password):
    try:
        # Vérifier si les nouveaux mots de passe correspondent
        if new_password != confirm_new_password:
            st.error("Les nouveaux mots de passe ne correspondent pas.")
            return
        
        # Vérifier la complexité du nouveau mot de passe
        password_errors = validate_password(new_password)
        if password_errors:
            for error in password_errors:
                st.error(error)
            return
        
        # Récupérer l'utilisateur par e-mail
        user = auth.get_user_by_email(email)
        
        # Mettre à jour le mot de passe
        auth.update_user(user.uid, password=new_password)
        st.success(f"Mot de passe de l'utilisateur {email} mis à jour avec succès!")
        logging.info(f"Mot de passe mis à jour pour l'utilisateur : {email}")
    except auth.UserNotFoundError:
        st.error("Aucun utilisateur trouvé avec cet e-mail.")
        logging.warning(f"Tentative de mise à jour du mot de passe pour un utilisateur inexistant : {email}")
    except Exception as e:
        st.error(f"Erreur: {e}")
        logging.error(f"Erreur lors de la mise à jour du mot de passe : {e}")


# Gestion de l'état de l'utilisateur
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_email = None

def login(email, password):
    try:
        user = auth.get_user_by_email(email)
        if user.email == email:  # Simulez une validation du mot de passe ici si nécessaire
            st.session_state.logged_in = True
            st.session_state.user_email = email
            st.success(f"Connecté en tant que {email}")
        else:
            st.error("Connexion échouée, e-mail ou mot de passe incorrect.")
    except Exception as e:
        st.error(f"Erreur: {e}")

def logout():
    st.session_state.logged_in = False
    st.session_state.user_email = None
    st.success("Déconnexion réussie.")

# CSS pour une interface moderne et créative
st.markdown(
    """
    <style>
    /* Style général pour les boutons */
    .stButton button {
        background-color: #4CAF50;  /* Vert */
        color: white;
        border-radius: 12px;  /* Coins plus arrondis */
        padding: 12px 24px;
        font-size: 16px;
        font-weight: bold;
        border: none;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);  /* Ombre légère */
    }
    .stButton button:hover {
        background-color: #45a049;  /* Vert plus foncé au survol */
        transform: scale(1.05);  /* Effet de zoom */
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.2);  /* Ombre plus prononcée */
    }
    .stButton button:active {
        background-color: #367c39;  /* Vert encore plus foncé au clic */
        transform: scale(0.95);  /* Effet de pression */
    }

    /* Style pour les champs de texte */
    .stTextInput input {
        border-radius: 12px;  /* Coins plus arrondis */
        padding: 12px;
        border: 1px solid #ccc;
        font-size: 16px;
        transition: all 0.3s ease;
        background-color: #f9f9f9;  /* Fond légèrement gris */
    }
    .stTextInput input:focus {
        border-color: #4CAF50;  /* Bordure verte lors de la sélection */
        box-shadow: 0 0 8px rgba(76, 175, 80, 0.5);  /* Ombre verte plus large */
        outline: none;
        background-color: white;  /* Fond blanc lors de la sélection */
    }

    /* Style pour les titres */
    .centered-title {
        text-align: center;
        font-size: 42px;
        font-weight: bold;
        color: #2E86C1;  /* Bleu */
        margin-bottom: 20px;
        transition: all 0.3s ease;
    }
    .centered-title:hover {
        color: #1c5a7a;  /* Bleu plus foncé au survol */
        transform: scale(1.02);  /* Légère augmentation de la taille */
    }

    /* Style pour le texte */
    .centered-text {
        text-align: center;
        font-size: 18px;
        color: #4CAF50;  /* Vert */
        margin-bottom: 30px;
        transition: all 0.3s ease;
    }
    .centered-text:hover {
        color: #367c39;  /* Vert plus foncé au survol */
    }

    /* Style pour le fond de la page */
    .stApp {
        background: linear-gradient(135deg, #f0f2f6, #e6f7ff);  /* Dégradé de fond */
        padding: 20px;
    }

    /* Style pour les messages de succès */
    .stSuccess {
        background-color: #d4edda;  /* Fond vert clair */
        color: #155724;  /* Texte vert foncé */
        padding: 15px;
        border-radius: 12px;  /* Coins plus arrondis */
        border: 1px solid #c3e6cb;
        margin-bottom: 20px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);  /* Ombre légère */
    }
    .stSuccess:hover {
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.2);  /* Ombre plus prononcée au survol */
        transform: translateY(-2px);  /* Effet de levée */
    }

    /* Style pour les messages d'erreur */
    .stError {
        background-color: #f8d7da;  /* Fond rouge clair */
        color: #721c24;  /* Texte rouge foncé */
        padding: 15px;
        border-radius: 12px;  /* Coins plus arrondis */
        border: 1px solid #f5c6cb;
        margin-bottom: 20px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);  /* Ombre légère */
    }
    .stError:hover {
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.2);  /* Ombre plus prononcée au survol */
        transform: translateY(-2px);  /* Effet de levée */
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Interface utilisateur avec onglets
if not st.session_state.logged_in:
    # Titre centré et stylisé
    st.markdown('<h1 class="centered-title">COURTIER-ASSISTANT</h1>', unsafe_allow_html=True)

    # Texte centré et stylisé
    st.markdown('<p class="centered-text">Connectez-vous ou inscrivez-vous pour accéder au contenu.</p>', unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["Connexion", "Inscription"])

    with tab1:
        st.subheader("Connexion")
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Mot de passe", type="password", key="login_password")
        if st.button("Se connecter"):
            login(email, password)

    with tab2:
        st.subheader("Inscription")
        name = st.text_input("Nom complet (inscription)", key="signup_name")
        new_email = st.text_input("Email (inscription)", key="signup_email")
        new_password = st.text_input("Mot de passe (inscription)", type="password", key="signup_password")
        confirm_password = st.text_input("Confirmez le mot de passe (inscription)", type="password", key="confirm_password")
        if st.button("S'inscrire"):
            signup(name, new_email, new_password, confirm_password)

# Si l'utilisateur est connecté, affichez l'application principale
if st.session_state.logged_in:
    st.success(f"Bienvenue, {st.session_state.user_email}!")
    if st.button("Se déconnecter"):
        logout()

    # Section de modification du mot de passe
    #st.header("Modifier le mot de passe")
    #email_update = st.text_input("E-mail (modification du mot de passe)", value=st.session_state.user_email, disabled=True)
    #if st.button("Envoyer un lien de réinitialisation"):
        #send_password_reset_email(email_update)

    # Votre application principale commence ici
    st.title("🚗 Assistant Courtier en Assurance Auto")

    # Configurations
    SCOPES = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/documents.readonly",
    ]
    SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")  # Contenu JSON des credentials Google
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")  # Clé API Gemini

    # Vérification des configurations Google
    if not SERVICE_ACCOUNT_JSON:
        st.error(
            "La variable d'environnement 'GOOGLE_APPLICATION_CREDENTIALS_JSON' est manquante ou vide."
        )
        st.stop()

    try:
        # Charger les credentials depuis le contenu JSON
        google_credentials = json.loads(SERVICE_ACCOUNT_JSON)
        credentials = service_account.Credentials.from_service_account_info(
            google_credentials, scopes=SCOPES
        )
        # Initialiser les services Google Drive et Docs
        drive_service = build("drive", "v3", credentials=credentials)
        docs_service = build("docs", "v1", credentials=credentials)
        #st.success("Services Google Drive et Docs initialisés avec succès !")
    except json.JSONDecodeError:
        st.error(
            "Le contenu de la variable 'GOOGLE_APPLICATION_CREDENTIALS_JSON' n'est pas un JSON valide."
        )
        st.stop()
    except Exception as e:
        st.error(f"Erreur lors de l'initialisation des services Google : {e}")
        st.stop()

    # Vérification de la clé API Gemini
    if not GEMINI_API_KEY:
        st.error(
            "La clé API Gemini n'est pas configurée. Assurez-vous que la variable d'environnement 'GEMINI_API_KEY' est définie."
        )
        st.stop()

    # Initialisation de Gemini
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        st.success("🤖 Assurbot initialisé 🚀 avec succès !")
    except Exception as e:
        st.error(f"Erreur lors de l'initialisation de Gemini : {e}")
        st.stop()

    # Fonction pour lister les fichiers dans un dossier Google Drive
    def list_files_in_folder(folder_id):
        try:
            results = drive_service.files().list(
                q=f"'{folder_id}' in parents",
                fields="files(id, name, mimeType)"
            ).execute()
            return results.get("files", [])
        except Exception as e:
            st.error(f"Erreur lors de la récupération des fichiers : {e}")
            return []

    # Fonction pour extraire le texte d'un document Google Docs
    def get_google_doc_text(doc_id):
        try:
            document = docs_service.documents().get(documentId=doc_id).execute()
            text_content = ""
            for element in document.get("body", {}).get("content", []):
                if "paragraph" in element:
                    for text_run in element.get("paragraph", {}).get("elements", []):
                        if "textRun" in text_run:
                            text_content += text_run["textRun"]["content"]
            return text_content.strip()
        except Exception as e:
            return f"Erreur lors de la lecture du document Google Docs : {e}"

    # Fonction pour interroger Gemini avec l'historique des interactions
    def query_gemini_with_history(docs_text, user_question, history, model= os.environ.get("KEY_API")):
        try:
            # Ajoutez l'historique des interactions au prompt
            history_str = "\n".join([f"Q: {h['question']}\nR: {h['response']}" for h in history])
            prompt = f"""
        Introduction et contexte :
        Tu es Courtier, un assistant en assurance automobile entraîné et créé par DJEGUI WAGUE. Ton objectif est de fournir des analyses claires, précises et structurées, tout en continuant à apprendre pour devenir un expert dans ce domaine. Tu mentionneras systématiquement cette introduction au début de chaque réponse pour informer les utilisateurs de tes capacités. Tu peux ajouter une touche d'humour (modérée) en lien avec l'assurance ou les caractéristiques du dossier analysé, mais cela ne doit pas être systématique.

        Voici l'historique des conversations précédentes :
        {history_str}

        Voici les contenus extraits des documents clients :

        {docs_text}

        Question : {user_question}
        """
            response = client.models.generate_content(model=model, contents=prompt)
            return response.text.strip()
        except Exception as e:
            return f"Erreur lors de l'interrogation de Gemini : {e}"

    # Initialiser st.session_state["history"] si ce n'est pas déjà fait
    if "history" not in st.session_state:
        st.session_state["history"] = []

    # Vérifiez si les documents ont déjà été chargés dans la session
    if "docs_text" not in st.session_state:# Récupérer l'ID du dossier Google Drive depuis les variables d'environnement
        folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        if not folder_id:
            st.error("La variable d'environnement 'GOOGLE_DRIVE_FOLDER_ID' n'est pas définie.")
            st.stop()
        
        # Vérifiez si les documents ont déjà été chargés dans la session
        if "docs_text" not in st.session_state:
            if folder_id:
                files = list_files_in_folder(folder_id)
                if files:
                    st.write("### Compagnies détectés :")
                    docs_text = ""
                    for file in files:
                        if file["mimeType"] == "application/vnd.google-apps.document":  # Google Docs
                            #st.write(f"Lecture du document : {file['name']}")
                            doc_text = get_google_doc_text(file["id"])
                            docs_text += f"\n\n---\n\n{doc_text}"
                        else:
                            st.warning(f"Type de fichier non pris en charge : {file['name']}")
                    
                    if docs_text:
                        st.session_state["docs_text"] = docs_text
                        st.success("Service validation✅.")
                else:
                    st.warning("Aucun fichier trouvé dans ce dossier.")
        else:
            st.success("Les documents sont déjà chargés et prêts à être utilisés.")
            

    # Posez une question
    if "docs_text" in st.session_state:
        user_question = st.text_input("Posez une question sur tous les documents :")
        if st.button("Envoyer la question"):
            with st.spinner("Interrogation 🤖Assurbot..."):
                # Interroger Gemini avec l'historique
                response = query_gemini_with_history(st.session_state["docs_text"], user_question, st.session_state["history"])
            
            # Ajouter la question et la réponse à l'historique (en haut de la liste)
            st.session_state["history"].insert(0, {"question": user_question, "response": response})

    # Affichage des messages dans un conteneur déroulant
    if st.session_state["history"]:
        with st.expander("📜 Historique des interactions", expanded=True):
            for interaction in st.session_state["history"]:
                st.markdown(f"**Question :** {interaction['question']}")
                st.markdown(f"**Réponse :** {interaction['response']}")
                st.markdown("---")

    # Pied de page
    st.markdown("---")
    st.markdown("© 2023 Assistant Assurance Auto. Tous droits réservés.")
