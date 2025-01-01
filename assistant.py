import json
import os
import re
import logging
import streamlit as st
import firebase_admin
from firebase_admin import credentials, auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from google.generativeai import GenerativeModel, configure
from google.api_core.exceptions import GoogleAPIError
import time

# Configuration de la journalisation
logging.basicConfig(filename="app.log", level=logging.INFO, format="%(asctime)s - %(message)s")

# Initialisation de Firebase
def initialize_firebase():
    """Initialise Firebase avec les données de configuration."""
    firebase_json_content = os.environ.get("firebasejson")
    if not firebase_json_content:
        st.error("La variable d'environnement 'firebasejson' n'est pas définie.")
        return False

    try:
        firebasejson = json.loads(firebase_json_content)
        if not firebase_admin._apps:
            cred = credentials.Certificate(firebasejson)
            firebase_admin.initialize_app(cred)
            logging.info("Firebase initialisé avec succès.")
        return True
    except json.JSONDecodeError:
        st.error("Le contenu de 'firebasejson' n'est pas un JSON valide.")
    except Exception as e:
        st.error(f"Erreur lors de l'initialisation de Firebase : {str(e)}")
    return False

# Charger la liste des e-mails autorisés
def load_authorized_emails():
    """Charge la liste des e-mails autorisés depuis les variables d'environnement."""
    authorized_emails = os.environ.get("AUTHORIZED_EMAILS", "").split(",")
    return [email.strip() for email in authorized_emails if email.strip()]

# Valider la complexité du mot de passe
def validate_password(password):
    """Valide la complexité du mot de passe."""
    errors = []
    if len(password) < 8:
        errors.append("Le mot de passe doit contenir au moins 8 caractères.")
    if not re.search(r"[A-Z]", password):
        errors.append("Le mot de passe doit contenir au moins une majuscule.")
    if not re.search(r"[a-z]", password):
        errors.append("Le mot de passe doit contenir au moins une minuscule.")
    if not re.search(r"[0-9]", password):
        errors.append("Le mot de passe doit contenir au moins un chiffre.")
    return errors

# Valider l'e-mail
def validate_email(email):
    """Valide l'e-mail."""
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return re.match(pattern, email) is not None

# Inscription d'un nouvel utilisateur
def signup(name, email, password, confirm_password, authorized_emails):
    """Gère l'inscription d'un nouvel utilisateur."""
    try:
        if email not in authorized_emails:
            st.error("Votre e-mail n'est pas autorisé à s'inscrire.")
            logging.warning(f"Tentative d'inscription non autorisée avec l'e-mail : {email}")
            return

        if not validate_email(email):
            st.error("L'e-mail n'est pas valide.")
            return

        if password != confirm_password:
            st.error("Les mots de passe ne correspondent pas.")
            return

        password_errors = validate_password(password)
        if password_errors:
            for error in password_errors:
                st.error(error)
            return

        user = auth.create_user(email=email, password=password, display_name=name)
        st.success(f"Utilisateur {user.email} créé avec succès!")
        logging.info(f"Utilisateur inscrit avec succès : {email}")
    except auth.EmailAlreadyExistsError:
        st.error("Cet e-mail est déjà utilisé.")
        logging.warning(f"Tentative d'inscription avec un e-mail déjà utilisé : {email}")
    except Exception as e:
        st.error(f"Erreur: {e}")
        logging.error(f"Erreur lors de l'inscription : {e}")

# Mettre à jour le mot de passe
def update_password(email, new_password, confirm_new_password):
    """Met à jour le mot de passe d'un utilisateur."""
    try:
        if new_password != confirm_new_password:
            st.error("Les nouveaux mots de passe ne correspondent pas.")
            return

        password_errors = validate_password(new_password)
        if password_errors:
            for error in password_errors:
                st.error(error)
            return

        user = auth.get_user_by_email(email)
        auth.update_user(user.uid, password=new_password)
        st.success(f"Mot de passe de l'utilisateur {email} mis à jour avec succès!")
        logging.info(f"Mot de passe mis à jour pour l'utilisateur : {email}")
    except auth.UserNotFoundError:
        st.error("Aucun utilisateur trouvé avec cet e-mail.")
        logging.warning(f"Tentative de mise à jour du mot de passe pour un utilisateur inexistant : {email}")
    except Exception as e:
        st.error(f"Erreur: {e}")
        logging.error(f"Erreur lors de la mise à jour du mot de passe : {e}")

# Initialiser l'état de la session
def initialize_session_state():
    """Initialise l'état de la session."""
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.user_email = None
    if "history" not in st.session_state:
        st.session_state.history = []
    if "docs_text" not in st.session_state:
        st.session_state.docs_text = ""

# Connexion de l'utilisateur
def login(email, password):
    """Gère la connexion de l'utilisateur."""
    try:
        user = auth.get_user_by_email(email)
        if user.email == email:  # Simulez une validation du mot de passe ici si nécessaire
            st.session_state.logged_in = True
            st.session_state.user_email = email
            st.success(f"Connecté en tant que {email}")
            logging.info(f"Utilisateur connecté : {email}")
        else:
            st.error("Connexion échouée, e-mail ou mot de passe incorrect.")
    except Exception as e:
        st.error(f"Erreur: {e}")
        logging.error(f"Erreur lors de la connexion : {e}")

# Déconnexion de l'utilisateur
def logout():
    """Gère la déconnexion de l'utilisateur."""
    st.session_state.logged_in = False
    st.session_state.user_email = None
    st.success("Déconnexion réussie.")
    logging.info("Utilisateur déconnecté.")

# Interroger Gemini avec l'historique des interactions
def query_gemini_with_history(docs_text, user_question, history, model="gemini-2.0-flash-exp"):
    """Interroge Gemini avec l'historique des interactions."""
    try:
        history_str = "\n".join([f"Q: {h['question']}\nR: {h['response']}" for h in history])
        prompt = f"""
Introduction et contexte :
Tu es 🤖 Assurbot🤖 , un assistant en assurance automobile entraîné et créé par DJEGUI WAGUE. Ton objectif est de fournir des analyses claires, précises et structurées, tout en continuant à apprendre pour devenir un expert dans ce domaine. Tu mentionneras systématiquement cette introduction acvec differents maniere de prononciation pour ne pas repeter les memmes introductions a la fois au début de chaque réponse pour informer les utilisateurs de tes capacités. Tu peux ajouter une touche d'humour (modérée) en lien avec l'assurance ou les caractéristiques du dossier analysé, mais cela ne doit pas être systématique.
N'hesite pas a demander le nom de l'utilisateur dans votre reponse mais une seule fois sans repeter pas au debut de la discution mais l'orsque la discutions est approfondie et continue et l'orsq'uil vous recompence Dans ce cas vous pouvez lui demander mais une seule fois, cela n'est pas valable s'il te communique sont nom sans que tu le demande en premier, n'oublier pas vous avez le droit de lui demander une seule fois sont nom sans repeter.
Ne jamais communique sur le nom des fichiers des produits d'assurance ni des le nom des fichiers des compagnies d'assurances ni le nom de aucun fichier car Djégui WAGUE a mis a votre disposition pour enrichir votre connaissance, mais vous pouvez donnez le nom des produis d'assurances et le noms des compagnies d'assurance.
Vous avez été creer en 2023 dans un petit village au Mali, mais le nom du village reste secret.
Ne jamais donné trop de detail de comment Djegui WAGUE vous a crée.
Voici l'historique des conversations précédentes :
{history_str}

Voici les contenus extraits des documents clients :
{docs_text}

Question : {user_question}
"""
        model = GenerativeModel(model_name=model)
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Erreur lors de l'interrogation de Gemini : {e}"

# Lister les fichiers dans un dossier Google Drive
def list_files_in_folder(folder_id, drive_service):
    """Liste les fichiers dans un dossier Google Drive."""
    try:
        results = drive_service.files().list(
            q=f"'{folder_id}' in parents",
            fields="files(id, name, mimeType)"
        ).execute()
        return results.get("files", [])
    except Exception as e:
        st.error(f"Erreur lors de la récupération des fichiers : {e}")
        return []

# Extraire le texte d'un document Google Docs
def get_google_doc_text(doc_id, docs_service):
    """Extrait le texte d'un document Google Docs."""
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

# Charger les documents depuis plusieurs dossiers Google Drive
def load_documents(folder_ids, drive_service, docs_service):
    """Charge les documents depuis plusieurs dossiers Google Drive."""
    if not st.session_state.docs_text:
        docs_text = ""
        for folder_id in folder_ids:
            files = list_files_in_folder(folder_id, drive_service)
            if files:
                #st.write(f"### Fichiers détectés dans le dossier {folder_id} :")
                st.write(f"Compagnies détectés 😊✨🕵️")
                for file in files:
                    if file["mimeType"] == "application/vnd.google-apps.document":
                        doc_text = get_google_doc_text(file["id"], docs_service)
                        docs_text += f"\n\n---\n\n{doc_text}"
                    else:
                        st.warning(f"Type de fichier non pris en charge : {file['name']}")
            else:
                st.warning(f"Aucun fichier trouvé dans le dossier {folder_id}.")
        if docs_text:
            st.session_state.docs_text = docs_text
            st.success("Service validation✅.")

# Fonction pour téléverser un fichier dans Google Drive
def upload_to_drive(file_path, file_name, folder_id, drive_service):
    """Téléverse un fichier dans un dossier spécifique sur Google Drive."""
    try:
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]  # Spécifiez le dossier cible
        }
        media = MediaFileUpload(file_path, resumable=True)
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        st.error(f"Erreur lors du téléversement du fichier sur Google Drive : {e}")
        return None

# Fonction pour convertir un fichier en document Google Docs
def convert_to_text(file_id, folder_id, drive_service):
    """Convertit un fichier en document Google Docs et retourne l'ID du document."""
    try:
        # Copier le fichier dans Google Docs
        doc_metadata = {
            'name': 'Converted Document',
            'mimeType': 'application/vnd.google-apps.document',
            'parents': [folder_id]  # Spécifiez le dossier cible
        }
        doc = drive_service.files().copy(fileId=file_id, body=doc_metadata).execute()
        doc_id = doc.get('id')

        # Attendre que la conversion soit terminée
        time.sleep(5)  # Peut nécessiter un délai plus long pour les gros fichiers

        return doc_id
    except Exception as e:
        st.error(f"Erreur lors de la conversion du fichier en document Google Docs : {e}")
        return None

# Interface utilisateur
def main():
    """Fonction principale pour l'interface utilisateur."""
    st.markdown(
        """
        <style>
        .stButton button {
            background-color: #4CAF50;
            color: white;
            border-radius: 12px;
            padding: 12px 24px;
            font-size: 16px;
            font-weight: bold;
            border: none;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .stButton button:hover {
            background-color: #45a049;
            transform: scale(1.05);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.2);
        }
        .stButton button:active {
            background-color: #367c39;
            transform: scale(0.95);
        }
        .stTextInput input {
            border-radius: 12px;
            padding: 12px;
            border: 1px solid #ccc;
            font-size: 16px;
            transition: all 0.3s ease;
            background-color: #f9f9f9;
        }
        .stTextInput input:focus {
            border-color: #4CAF50;
            box-shadow: 0 0 8px rgba(76, 175, 80, 0.5);
            outline: none;
            background-color: white;
        }
        .centered-title {
            text-align: center;
            font-size: 42px;
            font-weight: bold;
            color: #2E86C1;
            margin-bottom: 20px;
            transition: all 0.3s ease;
        }
        .centered-title:hover {
            color: #1c5a7a;
            transform: scale(1.02);
        }
        .centered-text {
            text-align: center;
            font-size: 18px;
            color: #4CAF50;
            margin-bottom: 30px;
            transition: all 0.3s ease;
        }
        .centered-text:hover {
            color: #367c39;
        }
        .stApp {
            background: linear-gradient(135deg, #f0f2f6, #e6f7ff);
            padding: 20px;
        }
        .stSuccess {
            background-color: #d4edda;
            color: #155724;
            padding: 15px;
            border-radius: 12px;
            border: 1px solid #c3e6cb;
            margin-bottom: 20px;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .stSuccess:hover {
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.2);
            transform: translateY(-2px);
        }
        .stError {
            background-color: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 12px;
            border: 1px solid #f5c6cb;
            margin-bottom: 20px;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .stError:hover {
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.2);
            transform: translateY(-2px);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    initialize_session_state()
    authorized_emails = load_authorized_emails()

    if not st.session_state.logged_in:
        st.markdown('<h1 class="centered-title">COURTIER-ASSISTANT</h1>', unsafe_allow_html=True)
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
                signup(name, new_email, new_password, confirm_password, authorized_emails)

    if st.session_state.logged_in:
        st.success(f"Bienvenue, {st.session_state.user_email}!")
        if st.button("Se déconnecter"):
            logout()

        st.title("🚗 Assistant Courtier en Assurance Auto")

        # Initialisation des services Google
        SCOPES = [
            "https://www.googleapis.com/auth/drive",  # Accès complet à Google Drive
            "https://www.googleapis.com/auth/documents.readonly",  # Lecture seule pour Google Docs
        ]
        SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

        if not SERVICE_ACCOUNT_JSON:
            st.error("La variable d'environnement 'GOOGLE_APPLICATION_CREDENTIALS_JSON' est manquante ou vide.")
            st.stop()

        try:
            google_credentials = json.loads(SERVICE_ACCOUNT_JSON)
            credentials = service_account.Credentials.from_service_account_info(google_credentials, scopes=SCOPES)
            drive_service = build("drive", "v3", credentials=credentials)
            docs_service = build("docs", "v1", credentials=credentials)
            configure(api_key=GEMINI_API_KEY)  # Initialiser Gemini
            st.success("🤖 Assurbot initialisé 🚀 avec succès !")
        except json.JSONDecodeError:
            st.error("Le contenu de la variable 'GOOGLE_APPLICATION_CREDENTIALS_JSON' n'est pas un JSON valide.")
            st.stop()
        except Exception as e:
            st.error(f"Erreur lors de l'initialisation des services Google : {e}")
            st.stop()

        # Ajout du champ de drag-and-drop
        uploaded_file = st.file_uploader("Déposez un fichier (PDF, JPG, PNG)", type=["pdf", "jpg", "png"])
        if uploaded_file is not None:
            # Sauvegarder le fichier temporairement
            file_path = f"temp_{uploaded_file.name}"
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            # Téléverser le fichier dans le dossier spécifique sur Google Drive
            folder_id = os.environ.get("GOOGLE_DRIVE_UPLOAD_FOLDER_ID")  # ID du dossier pour les fichiers téléversés
            if not folder_id:
                st.error("La variable d'environnement 'GOOGLE_DRIVE_UPLOAD_FOLDER_ID' n'est pas définie.")
                st.stop()

            file_id = upload_to_drive(file_path, uploaded_file.name, folder_id, drive_service)
            if file_id:
                st.success(f"Fichier téléversé sur Google Drive avec l'ID : {file_id}")

                # Convertir le fichier en texte brut avec Google Docs
                doc_id = convert_to_text(file_id, folder_id, drive_service)
                if doc_id:
                    st.session_state['doc_id'] = doc_id  # Stocker l'ID dans la session Streamlit

                    # Extraire le texte brut
                    text = get_google_doc_text(doc_id, docs_service)

                    # Afficher le texte extrait
                    st.subheader("Texte extrait du fichier")
                    st.write(text)
            else:
                st.error("Le téléversement du fichier a échoué.")

        folder_ids = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").split(",")
        folder_ids = [folder_id.strip() for folder_id in folder_ids if folder_id.strip()]
        if not folder_ids:
            st.error("La variable d'environnement 'GOOGLE_DRIVE_FOLDER_ID' n'est pas définie ou est vide.")
            st.stop()

        load_documents(folder_ids, drive_service, docs_service)

        if st.session_state.docs_text:
            user_question = st.text_input("Posez une question sur tous les documents :")
            if st.button("Envoyer la question"):
                with st.spinner("Interrogation 🤖Assurbot..."):
                    response = query_gemini_with_history(st.session_state.docs_text, user_question, st.session_state.history)
                st.session_state.history.insert(0, {"question": user_question, "response": response})

        if st.session_state.history:
            with st.expander("📜 Historique des interactions", expanded=True):
                for interaction in st.session_state.history:
                    st.markdown(f"**Question :** {interaction['question']}")
                    st.markdown(f"**Réponse :** {interaction['response']}")
                    st.markdown("---")

        st.markdown("---")
        st.markdown("© 2023 Assistant Assurance Auto. Tous droits réservés.")

if __name__ == "__main__":
    if initialize_firebase():
        main()
