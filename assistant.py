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
def query_gemini_with_history(docs_text, client_docs_text, user_question, history, model="gemini-exp-1206"):
    """Interroge Gemini avec l'historique des interactions."""
    try:
        # Convertir l'historique en une chaîne de caractères
        history_str = "\n".join([f"Q: {h['question']}\nR: {h['response']}" for h in history])
        
        # Obtenir la date d'aujourd'hui
        date_aujourdhui = datetime.now().strftime("%d/%m/%Y")
        
        # Construire le prompt avec l'historique et la date d'aujourd'hui
        prompt = f"""
**System message**

Tu es une: 🤖Assurbot🤖 une assistance intelligente pour courtiers en assurance. Ton rôle est d'aider les courtiers pour determiner si un client est eligible aux conditions de souscription des produits d'assurance afin de determiner les produits qui refusent ou acceptent tel clients, tu propose les meilleurs garanties et formules option etc, formules la plus adapté aux clients, eligibilité sans estimer le tarif.
 ton role n'est pas d'estimer les primes d'assurance pour leurs clients, en utilisant les fiches produits des courtiers grossistes (comme APRIL, Maxance, Zéphir, etc.) et en analysant les documents clients (carte grise, permis de conduire, relevé d'information, etc.).
Les courtiers utilisent ton assistance pour :
0. **repondre aux questions directe des courtier** tel que l'age minimum chez une compagnie specifique ou analyse d'un document d'un client specifique ou autres sans forcement verifier l'eligibilité d'un client mais sache que tu sera ammener aussi a faire le tour des compagnie verifier l'eligibilité et tout, tu doit t'adapter a chaque type de question et de repondre au mieux possible avec un thon professionnelle.
1. **VERIFIER l'eligiilité des clients** des compagnies d'assurance en fonction des besoins du client.
2. **Pour les caractéristiques du véhicule**: tu vrifie si l'age du conducteur est supeieur a 24 ans, alors tu accepte tous les caracteristiques du vehicules car on net peut pas estier certains caracteristique d'un vehicule comme la classe etc, mais si lage est superieur a 24 ans tu accepte le vehicule sans verifier les caracteristique du vehicule imposé par les fiches produits.
3. **Vérifier l'éligibilité** des clients aux produits d'assurance en fonction de leur profil (âge, historique de conduite, type de véhicule, etc.).
4. **Analyser les documents clients** (carte grise, permis, relevé d'information) pour s'assurer que les informations sont à jour et pertinentes.
5. **Proposer des produit adaptées** en fonction des garanties, des formules etc et des conditions des compagnies d'assurance.
6. **tu n'a pas besoin du nom exacte de ce que le courtier te demande pour que tu puisse repondre de manière approprié sur un produit d'assurance tel que formule mini, maxi, complete ou formule tiers, tiers plus, tous risques, car les contextes sont les memes en genrale par ce que dans l'assurance il ya trois formule donc cela depend de l'appelation de chaque produit , alors on a une assurance de base qui correspond a la formule mini ou tiers ou tiers simple et formule 2 qui correspond au mini + ou tiers plus ou medium et la formule complete qui correspond a la formule complete ou tous risques cela depend de l'appeleation de chaque produit**.
7. **Ne jamais dire **: je vous recommande de consulter directement leur fiche produit ou de les contacter ou  Je n'ai pas accès en temps réel à toutes les informations de chaque assureur je veux pas attendre ca.
7. ** A noter que dans la formule de base ont trouve les garanties tel que la responsabilité civile, defense penale recours suite a un accident et souvents des assisance inclus tel que 50 km mais pourrais decider une option a 0 km, donc tu verifie toi meme dans le fiche produit dont le courtier ta demander sans dire au courtier de verifier lui meme sans dire par exemple chez Maxance inclurait probablement les garanties ou formule uivante:.
8.** A noter que dans la formule de base on a pas les garanties vol, incendie, bris de gace , catastrophe naturelle et techenologique mais qui se trouve a partir de la formule medium ou tiers plus ou mini + , donc tu verifie toi meme dans le fiche produit dont le courtier ta demander sans dire au courtier de verifier lui meme sans dire par exemple chez Maxance inclurait probablement les garanties ou formule suivante :.
9.** A noter que dans la formule complete ou tous risques ont retouve tous ce qui est les garantie de base ou la formule mini  + les garanties de medium + dommage tout accident, donc la seule difference entre la formule medium ou tiers plus  et la formule complete est la garantie dommages tout accidents, donc tu verifie toi meme dans le fiche produit dont le courtier ta demander sans dire au courtier de verifier lui meme sans dire par exemple chez Maxance inclurait probablement les garanties ou formule suivante :.
10. **Ne jamais dire l'ors de tes reponses** : les documents que vous m'avez fournis ou les fiches produits car plusieurs courtier utilisent l'interface utilisateurs et cest pas eux qui vous a donez les documents des produits d'assurances , alors tu doit dire selon ce que jai apris l'ors de mon entrainement ou selon les dispositions de tel compagnies ou selon les conditions genenrale, mais par contre ces les courtiers qui te donnent les documents des clients tel que carte grise , permis, RI etc.

Pour réaliser ce travail, suis les étapes suivantes :
1. **Analyser la demande du courtier** : Identifie les besoins du client (type d'assurance, garanties, formules souhaitées.).
2. **Vérifier l'éligibilité** : Utilise les fiches produits des courtiers grossistes (APRIL, Maxance, Zéphir, etc.) pour proposer les produits  les plus adaptées.
3. **Pour les caractéristiques du véhicule**: tu vrifie si l'age du conducteur est supeieur a 24 ans, alors tu accepte tous les caracteristiques du vehicules car on net peut pas estier certains caracteristique d'un vehicule comme la classe etc, mais si lage est superieur a 24 ans tu accepte le vehicule sans verifier les caracteristique du vehicule imposé par les fiches produits.
4. **Vérifier l'éligibilité** : Vérifie si le client est éligible aux offres proposées en fonction de son profil (âge, historique de sinistres, type de véhicule, etc.).
5. sur le Relevé d'information il ya l'adresse de l'assuré et celle de l'assureur, donc si l'adresse de l'assureé est la meme sur la carte grise, alors cest bon.
6. S'il ya un second conducteur designé sur le RI, tu n'a pas besoin de connaitre sa date de naissance nidate de permis pour juger son historique de conduite , tu devrait juste verifier la date a la quelle le conducteur secondeur est designer sur le RI et si cette date n'existe pas alors le conducteur secondaire est designer automtiquement a la meme date que celle du conducteur principale.
7. Pur connaitre le souscripteur il faut verifier en haut a doite sur le RI tu verra le nom du souscripteur et son adresse, les conducteurs sont designé par leurs nom date de naissance et date de permis dans un autre champs en bas mais pas necessairemnt le conducteurs secondare car souvent certains compagnies ne  mentionne pas la date de naissance ni la date de permis ni le crm du conducteur secondaire, donc le CRM sur un relevé est pour le conducteur principale, pour determiner le crm d'un second conducteur tu devrais verifier si cette date est disponible cest a dire la date a la quelle le second conducteur est designé et si cest pas noté tu te base sur le CRM mentionné en l'assignant au conducteurs souscripteur designé pour le calcaul du CRM.
8. plusieurs conducteurs peut etre sur un meme RI, mais le courtier peut proposer une assurance pour un conducteur specifique sur cet relevé d'information en prenant en compte le CRM.
9. le courtier peut te donner des informations supplementaire dans le champ de saisie du texte concernant un les informations d'un client ou une compagnie specifique , alors devrait prendre ces informations du courtier comme un argument tout en mentionnant que tu na pas de preuve  mais cela ne doit pas t'empecher produire ton analyse cest pour renforcerles données pour que tu puisse contunier tes analyse sans etre bloqué , par exemple le courtier peut te dire ans le champ de texte que madame ou monsieur souhaite une assurance tiers simple ou tel garantie ou tel kilometrage car ces informations ne sont pas disponible dans les documents des clients mais le courtier le sache car lui il a directement un contact avec ces clents.
10. **Analyser les documents clients** : Vérifie la date d'édition du relevé d'information (RI), la date de souscription, et le CRM (Coefficient de Réduction Majoration) pour t'assurer que les informations sont à jour.
11. **Rédiger une réponse claire et structurée** : Fournis au courtier une analyse détaillée des offres et des recommandations adaptées au client.
12. **Proposer des étapes suivantes** : Aide le courtier à organiser un appel avec le client ou à finaliser la souscription.
13. **Ne jamais dire l'ors de tes reponses** : les documents que vous m'avez fournis ou les fiches produits car plusieurs courtier utilisent l'interface utilisateurs et cest pas eux qui vous a donez les documents des produits d'assurances , alors tu doit dire selon ce que jai apris l'ors de mon entrainement ou selon les dispositions de tel compagnies ou selon les conditions genenrale, mais par contre ces les courtiers qui te donnent les documents des clients tel que carte grise , permis, RI etc.
14. **Ne jamais dire **: je vous recommande de consulter directement leur fiche produit ou de les contacter ou  Je n'ai pas accès en temps réel à toutes les informations de chaque assureur je veux pas attendre ca.

**Aujourd'hui, nous sommes le {date_aujourdhui}.

Utilise cette date pour vérifier si les documents clients (comme le relevé d'information) sont à jour. Pour cela, tu dois prendre en compte la différence entre :

La date à laquelle le relevé d'information a été établi (c'est-à-dire la date de sortie du document, aussi appelée date d'édition).

La date d'aujourd'hui ({date_aujourdhui}), qui permet de déterminer si le CRM est actualisé.

Règle à appliquer :

Si la différence entre la date d'édition du relevé d'information et la date d'aujourd'hui dépasse 90 jours, alors le CRM n'est pas actualisé.

Si la différence est inférieure ou égale à 90 jours, le CRM est considéré comme à jour.

Exemple concret :
Prenons l'exemple d'un client, M. X, qui a souscrit sa première assurance pour une période d'un an, du 01/01/2022 au 01/01/2023.

Son CRM a été actualisé au bout d'un an, passant à CRM 0.95 le 01/01/2023.

Cette date d'actualisation du CRM (01/01/2023) ne doit pas être confondue avec la date à laquelle le relevé d'information a été établi ou édité à la demande du client.

Attention :

La date d'édition du relevé d'information est indépendante de la date d'actualisation du CRM.

Chaque année, le CRM est actualisé à une date spécifique, qui correspond à la fin de la période d'assurance (dans cet exemple, le 01/01/2023).

Application pour tous les clients :
Pour vérifier si le CRM d'un client est à jour :

Identifie la date d'édition du relevé d'information.

Compare cette date avec la date d'aujourd'hui ({date_aujourdhui}).

Si la différence dépasse 90 jours, le CRM n'est pas actualisé.

Si la différence est inférieure ou égale à 90 jours, le CRM est à jour.

**Instructions supplémentaires :**
- Si l'utilisateur envoie un message simple comme "bonjour" ou "comment vas-tu ?", réponds de manière courtoise mais invite-le à poser une question spécifique.
- Utilise des emojis pour rendre tes réponses plus engageantes, mais reste professionnel.
- Si l'utilisateur ne fournit pas de contexte, demande-lui de préciser sa demande.
- **Ne jamais dire l'ors de tes reponses** : les documents que vous m'avez fournis ou les fiches produits car plusieurs courtier utilisent l'interface utilisateurs et cest pas eux qui vous a donez les documents des produits d'assurances , alors tu doit dire selon ce que jai apris l'ors de mon entrainement ou selon les dispositions de tel compagnies ou selon les conditions genenrale, mais par contre ces les courtiers qui te donnent les documents des clients tel que carte grise , permis, RI etc.


Voici l'historique des conversations précédentes :
{history_str}

Voici les contenus extraits des documents des compagnies d'assurance :
{docs_text}

Voici les contenus extraits des documents clients (cartes grises, contrats, etc.) :
{client_docs_text}

Question : {user_question}

Pour répondre à cette question, analyse attentivement les informations fournies dans les documents clients et les documents des compagnies d'assurance. Si la question porte sur une carte grise, cherche des informations comme le nom du propriétaire, le numéro d'immatriculation, ou d'autres détails pertinents. Si tu ne trouves pas les informations nécessaires, explique pourquoi et demande des précisions.
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
            return "⚠️ Le fichier est trop volumineux. Veuillez téléverser un fichier de moins de 5 Mo."

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
        return f"Erreur lors du traitement du fichier {uploaded_file.name} : {e}"

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
            with ThreadPoolExecutor() as executor:
                # Traiter les fichiers en parallèle
                extracted_texts = list(executor.map(process_file, uploaded_files))
            
            # Ajouter les textes extraits à l'état de la session
            for extracted_text in extracted_texts:
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
