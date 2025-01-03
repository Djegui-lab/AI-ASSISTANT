import json
import os
import re
import logging
import streamlit as st
import firebase_admin
from firebase_admin import credentials, auth
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.generativeai import GenerativeModel, configure
from google.api_core.exceptions import GoogleAPIError
import boto3
import requests  # Pour faire des appels HTTP à l'API Hugging Face

# Configuration de la journalisation
logging.basicConfig(filename="app.log", level=logging.INFO, format="%(asctime)s - %(message)s")

# Clé API Hugging Face
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
HUGGINGFACE_API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-mnli"

# Fonction pour classifier la question avec Hugging Face Inference API
def classify_question_with_huggingface(question):
    """Classifie la question en utilisant Hugging Face Inference API."""
    headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
    payload = {
        "inputs": question,
        "parameters": {"candidate_labels": ["client", "company", "comparison"]}
    }
    try:
        response = requests.post(HUGGINGFACE_API_URL, headers=headers, json=payload)
        response.raise_for_status()  # Vérifie les erreurs HTTP
        result = response.json()
        st.write(f"Scores de confiance : {dict(zip(result['labels'], result['scores']))}")  # Afficher les scores
        return result["labels"][0]  # Retourne la classe prédite
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur lors de l'appel à Hugging Face API : {e}")
        return "comparison"  # Retourne une valeur par défaut en cas d'erreur

# Fonction pour demander le feedback utilisateur
def ask_user_feedback(question, predicted_class):
    """Demande à l'utilisateur de confirmer ou de corriger la classification."""
    st.write(f"Question : {question}")
    st.write(f"Classification prédite : {predicted_class}")
    
    # Afficher un radio bouton pour le feedback
    feedback = st.radio("La classification est-elle correcte ?", ["Oui", "Non"], key=f"feedback_{question}")
    
    # Si l'utilisateur clique sur "Non", afficher un selectbox pour corriger la classification
    if feedback == "Non":
        corrected_class = st.selectbox("Corriger la classification :", ["client", "company", "comparison"], key=f"corrected_class_{question}")
        return corrected_class
    return predicted_class

# Fonction pour journaliser les erreurs
def log_classification_error(question, predicted_class, corrected_class):
    """Journalise les erreurs de classification."""
    log_message = f"Question : {question} | Prédiction : {predicted_class} | Correction : {corrected_class}"
    logging.info(log_message)

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
    if "client_docs_text" not in st.session_state:
        st.session_state.client_docs_text = ""

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
def query_gemini_with_history(docs_text, client_docs_text, user_question, history, model="gemini-2.0-flash-exp"):
    """Interroge Gemini avec l'historique des interactions."""
    try:
        history_str = "\n".join([f"Q: {h['question']}\nR: {h['response']}" for h in history[-5:]])  # Limiter l'historique
        prompt = f"""
Introduction et contexte :
Tu es 🤖 Assurbot🤖 , un assistant en assurance automobile entraîné et créé par DJEGUI WAGUE. Ton objectif est de fournir des analyses claires, précises et structurées, tout en continuant à apprendre pour devenir un expert dans ce domaine.
Voici l'historique des conversations précédentes :
{history_str}

Voici les contenus extraits des documents clients :
{client_docs_text}

Voici les contenus des documents Google Docs :
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

# Fonction pour extraire le texte avec Amazon Textract
def extract_text_with_textract(file_bytes):
    """Extrait le texte d'un fichier avec Amazon Textract."""
    try:
        textract_client = boto3.client(
            "textract",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "eu-central-1"),
        )
        response = textract_client.detect_document_text(Document={"Bytes": file_bytes})
        text = ""
        for item in response["Blocks"]:
            if item["BlockType"] == "LINE":
                text += item["Text"] + "\n"
        return text.strip()
    except Exception as e:
        return f"Erreur lors de l'extraction du texte avec Textract : {e}"

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
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/documents.readonly",
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

        folder_ids = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").split(",")
        folder_ids = [folder_id.strip() for folder_id in folder_ids if folder_id.strip()]
        if not folder_ids:
            st.error("La variable d'environnement 'GOOGLE_DRIVE_FOLDER_ID' n'est pas définie ou est vide.")
            st.stop()

        load_documents(folder_ids, drive_service, docs_service)

        # Section pour téléverser les documents clients
        st.header("📄 Téléversez les documents des clients")
        uploaded_files = st.file_uploader(
            "Glissez-déposez les documents des clients (images ou PDF)", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True
        )

        if uploaded_files:
            client_docs_text = ""
            for uploaded_file in uploaded_files:
                st.write(f"### Fichier : {uploaded_file.name}")
                
                # Extraire le texte avec Amazon Textract
                file_bytes = uploaded_file.read()
                extracted_text = extract_text_with_textract(file_bytes)
                client_docs_text += f"\n\n---\n\n{extracted_text}"
                st.text_area("Texte extrait", extracted_text, height=200, key=uploaded_file.name)
            
            st.session_state.client_docs_text = client_docs_text

        # Section pour poser des questions
        st.header("❓ Posez une question sur les documents")
        user_question = st.text_input("Entrez votre question ici")
        if st.button("Envoyer la question"):
            # Classifier la question
            predicted_class = classify_question_with_huggingface(user_question)
            final_class = ask_user_feedback(user_question, predicted_class)
            
            # Journaliser les erreurs
            if final_class != predicted_class:
                log_classification_error(user_question, predicted_class, final_class)
            
            # Adapter les documents en fonction de la classification
            if final_class == "client":
                docs_text = ""  # Ne pas utiliser les documents des compagnies
            elif final_class == "company":
                client_docs_text = ""  # Ne pas utiliser les documents clients
            else:  # "comparison" ou "both"
                pass  # Utiliser les deux types de documents
            
            with st.spinner("Interrogation 🤖Assurbot..."):
                response = query_gemini_with_history(
                    st.session_state.docs_text,  # Documents Google Docs
                    st.session_state.client_docs_text,  # Documents clients téléversés
                    user_question,
                    st.session_state.history
                )
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
