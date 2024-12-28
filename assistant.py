import os
import streamlit as st
import firebase_admin
from firebase_admin import credentials, auth
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google import genai

# Initialisation de Firebase Admin SDK
firebase_json_path = os.environ.get("FIRE_BASE_APPLICATION_CREDENTIALS_JSON")  # Fichier JSON dans le même répertoire
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_json_path)
    firebase_admin.initialize_app(cred)

# Gestion de l'état de l'utilisateur
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_email = None

def signup(email, password):
    try:
        user = auth.create_user(email=email, password=password)
        st.success(f"Utilisateur {user.email} créé avec succès!")
    except Exception as e:
        st.error(f"Erreur: {e}")

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
    .stMarkdown h1 {
        color: #2E86C1;  /* Bleu */
        font-size: 42px;  /* Taille de police plus grande */
        font-weight: bold;
        margin-bottom: 20px;
        transition: all 0.3s ease;
        text-align: center;  /* Centrer le titre */
    }
    .stMarkdown h1:hover {
        color: #1c5a7a;  /* Bleu plus foncé au survol */
        transform: scale(1.02);  /* Légère augmentation de la taille */
    }

    .stMarkdown h2 {
        color: #D35400;  /* Orange */
        font-size: 32px;  /* Taille de police plus grande */
        font-weight: bold;
        margin-bottom: 15px;
        transition: all 0.3s ease;
        text-align: center;  /* Centrer le sous-titre */
    }
    .stMarkdown h2:hover {
        color: #a84300;  /* Orange plus foncé au survol */
        transform: scale(1.02);  /* Légère augmentation de la taille */
    }

    .stMarkdown h3 {
        color: #4CAF50;  /* Vert */
        font-size: 26px;  /* Taille de police plus grande */
        font-weight: bold;
        margin-bottom: 10px;
        transition: all 0.3s ease;
        text-align: center;  /* Centrer le sous-titre */
    }
    .stMarkdown h3:hover {
        color: #367c39;  /* Vert plus foncé au survol */
        transform: scale(1.02);  /* Légère augmentation de la taille */
    }

    /* Style pour le spinner (animation de chargement) */
    .stSpinner {
        color: #4CAF50;  /* Vert */
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

    /* Style pour les liens */
    a {
        color: #2E86C1;  /* Bleu */
        text-decoration: none;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    a:hover {
        color: #1c5a7a;  /* Bleu plus foncé au survol */
        text-decoration: underline;  /* Soulignement au survol */
    }

    /* Style pour les conteneurs */
    .stContainer {
        background-color: white;
        padding: 20px;
        border-radius: 12px;  /* Coins plus arrondis */
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);  /* Ombre légère */
        margin-bottom: 20px;
        transition: all 0.3s ease;
    }
    .stContainer:hover {
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.2);  /* Ombre plus prononcée au survol */
        transform: translateY(-2px);  /* Effet de levée */
    }

    /* Style pour les séparateurs */
    .stMarkdown hr {
        border: 1px solid #e0e0e0;
        margin: 20px 0;
    }

    /* Effet de rotation pour les icônes ou éléments spécifiques */
    .rotate-on-hover {
        transition: transform 0.3s ease;
    }
    .rotate-on-hover:hover {
        transform: rotate(10deg);  /* Rotation de 10 degrés au survol */
    }

    /* Effet de fondu pour les éléments */
    .fade-on-hover {
        transition: opacity 0.3s ease;
    }
    .fade-on-hover:hover {
        opacity: 0.8;  /* Légère transparence au survol */
    }

    /* Effet de gradient animé pour les boutons ou conteneurs */
    .gradient-animation {
        background: linear-gradient(90deg, #4CAF50, #2E86C1);
        background-size: 200% auto;
        transition: background-position 0.5s ease;
    }
    .gradient-animation:hover {
        background-position: right center;  /* Animation du gradient au survol */
    }

    /* Style pour le fond de la page */
    .stApp {
        background: linear-gradient(135deg, #f0f2f6, #e6f7ff);  /* Dégradé de fond */
        padding: 20px;
    }

    /* Style pour les cartes modernes */
    .modern-card {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transition: all 0.3s ease;
    }
    .modern-card:hover {
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.2);
        transform: translateY(-2px);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Interface utilisateur avec onglets
if not st.session_state.logged_in:
    st.title("Application Streamlit avec Firebase Auth")
    st.write("Connectez-vous ou inscrivez-vous pour accéder au contenu.")

    tab1, tab2 = st.tabs(["Connexion", "Inscription"])

    with tab1:
        st.subheader("Connexion")
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Mot de passe", type="password", key="login_password")
        if st.button("Se connecter"):
            login(email, password)

    with tab2:
        st.subheader("Inscription")
        new_email = st.text_input("Email (inscription)", key="signup_email")
        new_password = st.text_input("Mot de passe (inscription)", type="password", key="signup_password")
        if st.button("S'inscrire"):
            signup(new_email, new_password)

# Si l'utilisateur est connecté, affichez l'application principale
if st.session_state.logged_in:
    st.success(f"Bienvenue, {st.session_state.user_email}!")
    if st.button("Se déconnecter"):
        logout()

    # Votre application principale commence ici
    st.title("🚗 Assistant Courtier en Assurance Auto")
    

    # Configurations
    SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/documents.readonly"]
    gemini_api_key = "AIzaSyDkp3DVEJR6XE24SbaJMTEm271ZFKKMHkc"  # Remplacez par votre clé API Gemini

    # Initialiser les services Google Drive et Docs
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    drive_service = build("drive", "v3", credentials=credentials)
    docs_service = build("docs", "v1", credentials=credentials)

    # Initialiser Gemini
    client = genai.Client(api_key=gemini_api_key)

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
    if "docs_text" not in st.session_state:
        # Entrez l'ID du dossier Google Drive
        folder_id = st.text_input("Entrez l'ID du dossier Google Drive :")

        if folder_id:
            files = list_files_in_folder(folder_id)
            if files:
                st.write("### Fichiers détectés :")
                docs_text = ""
                for file in files:
                    if file["mimeType"] == "application/vnd.google-apps.document":  # Google Docs
                        st.write(f"Lecture du document : {file['name']}")
                        doc_text = get_google_doc_text(file["id"])
                        docs_text += f"\n\n---\n\n{doc_text}"
                    else:
                        st.warning(f"Type de fichier non pris en charge : {file['name']}")
                
                if docs_text:
                    st.session_state["docs_text"] = docs_text
                    st.success("Les documents ont été chargés.")
            else:
                st.warning("Aucun fichier trouvé dans ce dossier.")
    else:
        st.success("Les documents sont déjà chargés et prêts à être utilisés.")

    # Posez une question
    if "docs_text" in st.session_state:
        user_question = st.text_input("Posez une question sur tous les documents :")
        if st.button("Envoyer la question"):
            with st.spinner("Interrogation de Gemini..."):
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