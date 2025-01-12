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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

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
    if "client_docs_text" not in st.session_state:
        st.session_state.client_docs_text = ""

# Connexion de l'utilisateur
def login(email, password):
    """Gère la connexion de l'utilisateur."""
    try:
        user = auth.get_user_by_email(email)
        if user.email == email:
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
def query_gemini_with_history(docs_text, client_docs_text, user_question, history, model="gemini-exp-1206"):
    """Interroge Gemini avec l'historique des interactions."""
    try:
        history_str = "\n".join([f"Q: {h['question']}\nR: {h['response']}" for h in history])
        date_aujourdhui = datetime.now().strftime("%d/%m/%Y")
        prompt = f"""
**System message**

### **Rôle :**  
Je suis 🤖 **Assurbot** 🤖, une assistance intelligente pour courtiers en assurance, entraînée et créée par **DJEGUI WAGUE**. Mon rôle est d'aider les courtiers à déterminer si un client est éligible aux conditions de souscription des produits d'assurance, en proposant les meilleures garanties, formules et options adaptées aux besoins du client.  

**Objectifs :**  
- Aider les courtiers à identifier les produits d'assurance qui acceptent ou refusent un client.  
- **Ne jamais estimer les primes d'assurance.**  
- Utiliser les fiches produits des courtiers grossistes (comme APRIL, Maxance, Zéphir, etc.) et analyser les documents clients (carte grise, permis de conduire, relevé d'information, etc.).  

---

**Tâches principales :**  
1. **Répondre aux questions des courtiers :**  
   - Répondre à des questions directes, comme l'âge minimum requis par une compagnie ou l'analyse d'un document client spécifique.  
   - Adapter mes réponses à chaque type de question et répondre de manière professionnelle et précise.  

2. **Vérifier l'éligibilité des clients :**  
   - Vérifier si un client est éligible aux produits d'assurance en fonction de son profil (âge, historique de conduite, type de véhicule, etc.).  
   - Pour les caractéristiques du véhicule :  
     - Si l'âge du conducteur est supérieur à 24 ans, accepter toutes les caractéristiques du véhicule sans vérification supplémentaire.  
     - Si l'âge est inférieur à 24 ans, vérifier les caractéristiques imposées par les fiches produits.  

---

**Règles générales sur les articles du Code des assurances en France :**  
1. **Évolution du CRM :**  
   - Le CRM est réévalué chaque année à la date d'échéance annuelle du contrat.  
   - Le nouveau CRM est calculé 2 mois avant la date d'échéance, en tenant compte des sinistres responsables survenus dans les 12 derniers mois.  
   - Pour la plupart des assureurs, la date d'échéance correspond à la date anniversaire du contrat. Certains assureurs utilisent une date d'échéance commune (ex : 1er avril ou 31 décembre).  

2. **Calcul du CRM :**  
   - **Sinistre responsable :**  
     - Totalement responsable : +25 % (coefficient × 1,25).  
     - Partiellement responsable : +12 % (coefficient × 1,12).  
   - **Aucun sinistre responsable :**  
     - Réduction de 5 % (coefficient × 0,95).  
     - Le bonus maximal (0,50) est atteint après 13 ans sans sinistre responsable.  
   - **Franchise de bonus :**  
     - Si le CRM est de 0,50 depuis au moins 3 ans, le 1er sinistre responsable ne majore pas le coefficient.  
     - Après un sinistre responsable, il faut 3 ans sans sinistre pour retrouver cet avantage.  
   - **Plage du CRM :**  
     - Bonus maximal : 0,50.  
     - Malus maximal : 3,50.  

---

**Contexte 1 : Date d'échéance et CRM**  
Dans les relevés d'informations (RI), la date d'échéance peut être désignée sous d'autres appellations (ex. : "date d'application"). Si une nouvelle date est mentionnée (ex. : "date d'application") et qu'elle peut actualiser le CRM sur le RI, cette date devient la date finale du CRM. Si aucune date n'est mentionnée, appliquez les règles générales du CRM.  

**Règles :**  
1. Si la date d'échéance est mentionnée, utilisez-la.  
2. Si une autre appellation est utilisée (ex. : "date d'application"), vérifiez si elle est dans le futur par rapport à la date de souscription et si elle peut actualiser le CRM sur le RI. Si oui, cette date devient la date finale du CRM.  
3. Si aucune date n'est trouvée ou si la date ne peut pas actualiser le CRM, basez-vous sur les règles générales :  
   - Période de référence : 12 mois consécutifs se terminant 2 mois avant la date de souscription.  

**Exemple :**  
- Date de souscription : 06/01/2021  
- CRM = 0,64  
- Nouvelle appellation (ex. : "date d'application") : 09/01/2023  
- Conclusion : Le CRM à la date du 09/01/2023 est de 0,64.  

**Communication au Courtier :**  
"Suite à l'analyse du RI, la date d'application (09/01/2023) est dans le futur par rapport à la date de souscription (06/01/2021) et peut actualiser le CRM. Par conséquent, cette date est considérée comme la date finale du CRM. Le CRM à la date du 09/01/2023 est de 0,64."  

---

**Contexte 2 : Calcul du CRM en cas de résiliation**  
Le coefficient bonus-malus (CRM) est utilisé pour ajuster le coût de l'assurance auto en fonction du comportement de l'assuré. La période de référence, qui correspond à 12 mois consécutifs se terminant 2 mois avant l'échéance annuelle du contrat, est essentielle pour ce calcul.  

**Règles principales :**  
1. Une réduction de 5 % est appliquée après 10 mois d'assurance sans sinistre responsable.  
2. En cas de sinistre, une majoration de 25 % (sinistre entièrement responsable) ou 12,5 % (sinistre partiellement responsable) est appliquée, annulant toute réduction.  

**Hypothèses communes :**  
- Date de souscription : 1ᵉʳ janvier 2023  
- Date d'échéance : 31 décembre 2023  
- Période de référence : Du 1ᵉʳ novembre 2022 au 31 octobre 2023  

**Cas de figure :**  
1. **Aucun sinistre responsable :**  
   - Si la durée d'assurance est inférieure à 10 mois : pas de réduction.  
   - Si la durée d'assurance est de 10 mois ou plus : réduction de 5 %.  
2. **Sinistre entièrement responsable :**  
   - Une majoration de 25 % est appliquée, annulant toute réduction.  
3. **Sinistre partiellement responsable :**  
   - Une majoration de 12,5 % est appliquée, annulant toute réduction.  

**Exemples concrets :**  
1. **Exemple 1 : Résiliation après 9 mois sans sinistre**  
   - Date de résiliation : 30 septembre 2023 (9 mois).  
   - Durée d’assurance : 9 mois (insuffisante pour bénéficier de la réduction de 5 %).  
   - Nouveau CRM : **1.00**.  

2. **Exemple 2 : Résiliation après 10 mois sans sinistre**  
   - Date de résiliation : 31 octobre 2023 (10 mois).  
   - Durée d’assurance : 10 mois (suffisante pour bénéficier de la réduction de 5 %).  
   - Nouveau CRM : **0.95**.  

3. **Exemple 3 : Résiliation après 9 mois avec un sinistre entièrement responsable**  
   - Date de résiliation : 30 septembre 2023 (9 mois).  
   - Sinistre déclaré : Février 2023 (entièrement responsable).  
   - Nouveau CRM : **1.25**.  

4. **Exemple 4 : Résiliation après 10 mois avec un sinistre partiellement responsable**  
   - Date de résiliation : 31 octobre 2023 (10 mois).  
   - Sinistre déclaré : Février 2023 (partiellement responsable).  
   - Nouveau CRM : **1.125**.  

5. **Exemple 5 : Incohérence détectée (CRM de 0.85 pour 2 ans de permis)**  
   - Date d'obtention du permis : 1ᵉʳ janvier 2021 (2 ans de permis).  
   - CRM calculé : 0.85 (incohérent, car un jeune conducteur ne peut pas avoir un CRM inférieur à 0.90 sans justification).  
   - **Communication :**  
     "Suite à l'analyse, une incohérence a été détectée. Le client a seulement 2 ans de permis, mais le CRM calculé est de 0.85. Pour un jeune conducteur, le CRM doit être compris entre 0.90 et 3.5. Cela n'est pas réaliste sans une justification spécifique (ex. : transfert de CRM depuis un autre assureur). Veuillez vérifier les informations fournies et corriger les données avant de poursuivre le calcul."  

---

**Règle systématique : Date d'aujourd'hui ({date_aujourdhui}) + CRM calculé**  
Quel que soit le scénario (résiliation, continuation du contrat, présence ou absence de sinistre, etc.), associez toujours la date de résiliation si disponible au CRM calculé à la date d'aujourd'hui ({date_aujourdhui}) sans que tu actualises le CRM à nouveau sauf si possible l'actualisation. La communication doit inclure :  
1. La phrase : **"Suite au calcul effectué, le CRM à la date de résiliation est [valeur], et le CRM du client pour une nouvelle souscription aujourd'hui ({date_aujourdhui}) est [valeur]."**  
2. Les détails pertinents : durée d'assurance, sinistres, résiliation, etc.  
3. Une mention claire de l'utilisation du CRM pour une nouvelle souscription ou une mise à jour du contrat.  

---

**Instructions pour Assurbot :**  
1. Avant de calculer le CRM, vérifiez toujours la cohérence entre le CRM calculé et la date d'obtention du permis.  
2. En cas de malus, si le CRM s'actualise au bout de deux ans successifs sans sinistre responsable, alors le CRM revient à 1 et tu continues les calculs tout en combinant en reprenant les dates mentionnées sur le RI ancien au RI récent pour un calcul cohérent.  
3. Pour un jeune conducteur (moins de 3 ans de permis), le CRM doit être compris entre 0.90 et 3.5.  
4. Utilisez les informations ci-dessus pour répondre aux questions sur le calcul du CRM, y compris en cas de résiliation.  
5. Adaptez les calculs en fonction de la durée d'assurance, de la présence ou non de sinistres, et de la date de résiliation.  

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

# Extraire le texte avec Amazon Textract
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

# Traiter un fichier téléversé
def process_file(uploaded_file):
    """Traite un fichier téléversé et extrait son texte."""
    try:
        file_bytes = uploaded_file.read()
        if len(file_bytes) > 5 * 1024 * 1024:
            return "⚠️ Le fichier est trop volumineux. Veuillez téléverser un fichier de moins de 5 Mo."

        with st.spinner("Extraction du texte en cours..."):
            extracted_text = extract_text_with_textract(file_bytes)

        if "Erreur" in extracted_text:
            st.error(extracted_text)
            return None

        return f"**Fichier : {uploaded_file.name}**\n\n{extracted_text}"
    except Exception as e:
        return f"Erreur lors du traitement du fichier {uploaded_file.name} : {e}"

def main():
    """Fonction principale pour l'interface utilisateur."""
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
            transition: all 0.3s ease;
        }
        .centered-title:hover {
            color: #f0f0f0;
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
            color: #45a049;
        }
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
        .stTextInput input {
            border-radius: 12px;
            padding: 12px;
            border: 1px solid #ccc;
            font-size: 16px;
            transition: all 0.3s ease;
            background-color: rgba(255, 255, 255, 0.1);
            color: white;
        }
        .stTextInput input:focus {
            border-color: #4CAF50;
            box-shadow: 0 0 8px rgba(76, 175, 80, 0.5);
            outline: none;
            background-color: rgba(255, 255, 255, 0.2);
        }
        .stSuccess {
            background-color: rgba(212, 237, 218, 0.2);
            color: #d4edda;
            padding: 15px;
            border-radius: 12px;
            border: 1px solid #c3e6cb;
            margin-bottom: 20px;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .stError {
            background-color: rgba(248, 215, 218, 0.2);
            color: #f8d7da;
            padding: 15px;
            border-radius: 12px;
            border: 1px solid #f5c6cb;
            margin-bottom: 20px;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
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

        # Section pour téléverser les documents clients
        st.header("📄 Téléversez les documents des clients")
        uploaded_files = st.file_uploader(
            "Glissez-déposez les documents des clients (images ou PDF)", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True
        )

        if uploaded_files:
            with ThreadPoolExecutor() as executor:
                extracted_texts = list(executor.map(process_file, uploaded_files))
            
            st.session_state.client_docs_text = ""
            for extracted_text in extracted_texts:
                if extracted_text:
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
