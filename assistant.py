import json
import os
import logging
import streamlit as st
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.generativeai import GenerativeModel, configure
import boto3

# Configuration de la journalisation
logging.basicConfig(filename="app.log", level=logging.INFO, format="%(asctime)s - %(message)s")

# Initialiser l'état de la session
def initialize_session_state():
    """Initialise l'état de la session."""
    if "history" not in st.session_state:
        st.session_state.history = []  # Historique des interactions
    if "docs_text" not in st.session_state:
        st.session_state.docs_text = ""  # Contenu des documents Google Docs
    if "client_docs_text" not in st.session_state:
        st.session_state.client_docs_text = ""  # Contenu des documents clients téléversés

# Interroger Gemini pour une réponse
def query_gemini(user_question, model_name="gemini-1.0-pro", docs_text="", client_docs_text="", history=None):
    """Interroge Gemini pour une réponse."""
    try:
        # Construire le prompt en fonction du modèle
        if model_name == "gemini-1.0-pro":
            prompt = f"""
            Tu es 🤖 Assurbot🤖, un assistant en assurance automobile. Ton objectif est de fournir des réponses claires, précises et concises.

            Question : {user_question}

            **Instructions :**
            - Réponds directement à la question sans inclure de contexte inutile.
            - Sois concis et précis.
            """
        else:  # gemini-2.0-flash-exp
            history_str = "\n".join([f"Q: {h['question']}\nR: {h['response']}" for h in (history or [])[-5:]])  # Limiter l'historique
            prompt = f"""
            Introduction et contexte :
            Tu es 🤖 Assurbot🤖, un assistant en assurance automobile. Ton objectif est de fournir des analyses claires, précises et structurées.
            Voici l'historique des conversations précédentes :
            {history_str}

            Voici les contenus extraits des documents clients :
            {client_docs_text}

            Voici les contenus des documents Google Docs (conditions des compagnies) :
            {docs_text}

            Question : {user_question}

            **Instructions :**
            - Fournis une réponse détaillée et structurée.
            - Si les informations nécessaires ne sont pas disponibles, indique-le clairement.
            """

        # Interroger le modèle
        model = GenerativeModel(model_name=model_name)
        response = model.generate_content(prompt)

        # Vérifier si la réponse contient du texte valide
        if response.text:
            return response.text.strip()
        else:
            return "Désolé, je n'ai pas pu générer de réponse valide pour cette question."

    except Exception as e:
        if "safety_ratings" in str(e):
            return "Désolé, je ne peux pas répondre à cette question pour des raisons de sécurité."
        else:
            return f"Erreur lors de l'interrogation de Gemini : {e}"

# Lister les fichiers dans un dossier Google Drive
@st.cache_data
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

# Extraire le texte d'un document Google Docs (texte brut)
@st.cache_data
def get_google_doc_text(doc_id, docs_service):
    """Extrait le texte brut d'un document Google Docs."""
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
        logging.error(f"Erreur lors de la lecture du document Google Docs (ID: {doc_id}) : {e}")
        return f"Erreur lors de la lecture du document Google Docs : {e}"

# Charger les documents depuis plusieurs dossiers Google Drive
@st.cache_data
def load_documents(folder_ids, drive_service, docs_service):
    """Charge les documents depuis plusieurs dossiers Google Drive."""
    docs_text = ""
    for folder_id in folder_ids:
        files = list_files_in_folder(folder_id, drive_service)
        if files:
            st.write(f"Compagnies détectés 😊✨🕵️")
            for file in files:
                if file["mimeType"] == "application/vnd.google-apps.document":
                    doc_text = get_google_doc_text(file["id"], docs_service)
                    if "Erreur" not in doc_text and doc_text.strip():
                        docs_text += f"\n\n---\n\n{doc_text}"
                    else:
                        st.warning(f"Le document {file['name']} ne contient pas de texte valide.")
                else:
                    st.warning(f"Type de fichier non pris en charge : {file['name']}")
        else:
            st.warning(f"Aucun fichier trouvé dans le dossier {folder_id}.")
    return docs_text

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

    st.title("🚗 Assistant Courtier en Assurance Auto")

    # Validation des variables d'environnement
    required_env_vars = ["GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS_JSON", "GOOGLE_DRIVE_FOLDER_ID"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        st.error(f"Les variables d'environnement suivantes sont manquantes : {', '.join(missing_vars)}")
        st.stop()

    # Initialisation des services Google
    SCOPES = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/documents.readonly",
    ]
    SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

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

    # Charger les conditions des compagnies au démarrage
    with st.spinner("Chargement des documents depuis Google Drive..."):
        st.session_state.docs_text = load_documents(folder_ids, drive_service, docs_service)
        if st.session_state.docs_text:
            st.success("Service validation✅.")

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

    # Section pour poser une question
    st.header("❓ Posez votre question")
    user_question = st.text_input("Entrez votre question ici")

    # Option pour choisir le type de réponse
    response_type = st.radio(
        "Choisissez le type de réponse :",
        ("Réponse rapide", "Analyse approfondie"),
        index=0  # Par défaut, sélectionner "Réponse rapide"
    )

    if st.button("Envoyer"):
        with st.spinner("🤖 Assurbot réfléchit..."):
            if response_type == "Réponse rapide":
                response = query_gemini(user_question, model_name="gemini-1.0-pro")
            else:
                response = query_gemini(
                    user_question,
                    model_name="gemini-2.0-flash-exp",
                    docs_text=st.session_state.docs_text,
                    client_docs_text=st.session_state.client_docs_text,
                    history=st.session_state.history
                )
            
            # Enregistrer la question et la réponse dans l'historique
            st.session_state.history.append({"question": user_question, "response": response})
        
        st.write("**Réponse :**")
        st.write(response)

    # Afficher l'historique des interactions
    if st.session_state.history:
        st.header("📜 Historique des interactions")
        for interaction in st.session_state.history:
            st.markdown(f"**Question :** {interaction['question']}")
            st.markdown(f"**Réponse :** {interaction['response']}")
            st.markdown("---")

    st.markdown("---")
    st.markdown("© 2025 Assistant Assurance Auto. Tous droits réservés.")

if __name__ == "__main__":
    main()
