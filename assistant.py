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
import boto3  # Pour Amazon Textract
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime  # Ajout pour la gestion des dates

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
        st.session_state.history = []  # Historique des interactions
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

# Calculer la mise à jour du CRM
def calculate_crm_update(ri_date, crm_value):
    """Calcule si le CRM est à jour en fonction de la date d'édition du RI et de la date d'aujourd'hui."""
    today = datetime.now()
    ri_date = datetime.strptime(ri_date, "%d/%m/%Y")
    delta = today - ri_date
    if delta.days > 90:  # 3 mois = 90 jours
        return f"⚠️ Le CRM de {crm_value} est daté du {ri_date.strftime('%d/%m/%Y')} et n'est donc pas à jour. Un RI plus récent (daté de moins de 3 mois) est nécessaire."
    else:
        return f"✅ Le CRM de {crm_value} est à jour (émis le {ri_date.strftime('%d/%m/%Y')})."

# Interroger Gemini avec l'historique des interactions
def query_gemini_with_history(docs_text, client_docs_text, user_question, history, model="gemini-2.0-flash-exp"):
    """Interroge Gemini avec l'historique des interactions."""
    try:
        # Convertir l'historique en une chaîne de caractères
        history_str = "\n".join([f"Q: {h['question']}\nR: {h['response']}" for h in history])
        
        # Obtenir la date d'aujourd'hui
        date_aujourdhui = datetime.now().strftime("%d/%m/%Y")
        
        # Construire le prompt avec l'historique et la date d'aujourd'hui
        prompt = f"""
**System message**


---

### **Rôle :**  
Je suis 🤖 **Assurbot** 🤖, une assistance intelligente pour courtiers en assurance, entraînée et créée par **DJEGUI WAGUE**. Mon rôle est d'aider les courtiers à déterminer si un client est éligible aux conditions de souscription des produits d'assurance, en proposant les meilleures garanties, formules et options adaptées aux besoins du client.  

**Objectifs :**  
- Aider les courtiers à identifier les produits d'assurance qui acceptent ou refusent un client.  
- **Ne jamais estimer les primes d'assurance.**  
- Utiliser les fiches produits des courtiers grossistes (comme APRIL, Maxance, Zéphir, etc.) et analyser les documents clients (carte grise, permis de conduire, relevé d'information, etc.).  

---
### **Historique des conversations :**  
{history_str}  

### **Documents des compagnies d'assurance :**  
{docs_text}  

### **Documents clients :**  
{client_docs_text}  

**Question :** {user_question}  

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

# Fonction pour traiter un fichier téléversé
def process_file(uploaded_file):
    """Traite un fichier téléversé et extrait son texte."""
    try:
        # Lire le fichier téléversé
        file_bytes = uploaded_file.read()

        # Vérifier la taille du fichier (limite à 5 Mo)
        if len(file_bytes) > 5 * 1024 * 1024:  # 5 Mo
            st.error("⚠️ Le fichier est trop volumineux. Veuillez téléverser un fichier de moins de 5 Mo.")
            return None

        # Afficher un spinner pendant l'extraction
        with st.spinner("Extraction du texte en cours..."):
            extracted_text = extract_text_with_textract(file_bytes)

        # Vérifier si l'extraction a réussi
        if "Erreur" in extracted_text:
            st.error(extracted_text)  # Afficher l'erreur
            return None

        # Retourner le texte extrait
        return extracted_text
    except Exception as e:
        st.error(f"Erreur lors du traitement du fichier {uploaded_file.name} : {e}")
        return None

def main():
    """Fonction principale pour l'interface utilisateur."""
    # Initialiser les variables de session
    initialize_session_state()

    # Charger les e-mails autorisés
    authorized_emails = load_authorized_emails()

    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(135deg, #1e3c72, #2a5298);
            color: white;
            padding: 20px;
        }
        .centered-title {
            text-align: center;
            font-size: 42px;
            font-weight: bold;
            color: white;
            margin-bottom: 20px;
        }
        .centered-text {
            text-align: center;
            font-size: 18px;
            color: #4CAF50;
            margin-bottom: 30px;
        }
        .stButton button {
            background-color: #4CAF50;
            color: white;
            border-radius: 12px;
            padding: 12px 24px;
            font-size: 16px;
            font-weight: bold;
            border: none;
        }
        .stTextInput input {
            border-radius: 12px;
            padding: 12px;
            border: 1px solid #ccc;
            font-size: 16px;
            background-color: rgba(255, 255, 255, 0.1);
            color: black;
        }
        .stTextInput input:focus {
            border-color: #4CAF50;
            box-shadow: 0 0 8px rgba(76, 175, 80, 0.5);
            outline: none;
            background-color: rgba(255, 255, 255, 0.2);
            color: black;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<h1 class="centered-title">COURTIER-ASSISTANT</h1>', unsafe_allow_html=True)
    st.markdown('<p class="centered-text">Connectez-vous ou inscrivez-vous pour accéder au contenu.</p>', unsafe_allow_html=True)

    # Onglets Connexion et Inscription
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
            with ThreadPoolExecutor() as executor:
                # Traiter les fichiers en parallèle
                extracted_texts = list(executor.map(process_file, uploaded_files))
            
            # Ajouter les textes extraits à l'état de la session
            for extracted_text in extracted_texts:
                if extracted_text:  # Vérifier que le texte extrait n'est pas None
                    if "client_docs_text" not in st.session_state:
                        st.session_state.client_docs_text = ""
                    st.session_state.client_docs_text += f"\n\n---\n\n{extracted_text}"

        # Section pour poser des questions
        st.header("❓ Posez une question sur les documents")
        user_question = st.text_input("Entrez votre question ici")
        if st.button("Envoyer la question"):
            with st.spinner("Interrogation 🤖Assurbot..."):
                response = query_gemini_with_history(
                    st.session_state.docs_text, 
                    st.session_state.client_docs_text, 
                    user_question, 
                    st.session_state.history
                )
            st.session_state.history.insert(0, {"question": user_question, "response": response})

        # Affichage de l'historique des interactions
        if st.session_state.history:
            with st.expander("📜 Historique des interactions", expanded=True):
                for interaction in st.session_state.history:
                    st.markdown(f"**Question :** {interaction['question']}")
                    st.markdown(f"**Réponse :** {interaction['response']}")
                    st.markdown("---")

        st.markdown("---")
        st.markdown("© 2025 Assistant Assurance Auto. Tous droits réservés.")

if __name__ == "__main__":
    if initialize_firebase():
        main()
