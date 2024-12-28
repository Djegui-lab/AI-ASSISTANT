import json
import streamlit as st
import firebase_admin
from firebase_admin import credentials, auth
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google import genai
import os

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
            st.success("Firebase initialisé avec succès sur Heroku !")
    except json.JSONDecodeError:
        st.error("Le contenu de 'firebasejson' n'est pas un JSON valide.")
    except Exception as e:
        st.error(f"Erreur lors de l'initialisation de Firebase : {str(e)}")

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
    /* Ajoutez votre CSS ici */
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
    SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")  # Chemin du fichier JSON Google
    SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/documents.readonly"]
    gemini_api_key = os.environ.get("GEMINI_API_KEY")  # Clé API Gemini

    # Vérification des configurations
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        st.error("Le fichier de credentials Google est introuvable. Assurez-vous que la variable d'environnement 'GOOGLE_APPLICATION_CREDENTIALS_JSON' est correctement configurée.")
        st.stop()
    if not gemini_api_key:
        st.error("La clé API Gemini n'est pas configurée. Assurez-vous que la variable d'environnement 'GEMINI_API_KEY' est définie.")
        st.stop()

    # Initialiser les services Google Drive et Docs
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        drive_service = build("drive", "v3", credentials=credentials)
        docs_service = build("docs", "v1", credentials=credentials)
    except Exception as e:
        st.error(f"Erreur lors de l'initialisation des services Google : {e}")
        st.stop()

    # Initialiser Gemini
    try:
        client = genai.Client(api_key=gemini_api_key)
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
