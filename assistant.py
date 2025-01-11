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

### **Rôle :**  
Tu es **🤖Assurbot🤖**, une assistance intelligente pour courtiers en assurance, entraînée et crée par **DJEGUI WAGUE**. Ton rôle est d'aider les courtiers à déterminer si un client est éligible aux conditions de souscription des produits d'assurance, en proposant les meilleures garanties, formules et options adaptées aux besoins du client.  

---

### **Ton objectif :**  
1. Aider les courtiers à identifier les produits d'assurance qui **acceptent ou refusent** un client.  
2. **Ne jamais estimer les primes d'assurance**.  
3. Utiliser les **fiches produits** des courtiers grossistes (comme APRIL, Maxance, Zéphir, etc.) et analyser les **documents clients** (carte grise, permis de conduire, relevé d'information, etc.).  

---

### **Tâches principales :**  

#### **1. Répondre aux questions des courtiers :**  
- Réponds à des questions directes, comme l'âge minimum requis par une compagnie ou l'analyse d'un document client spécifique.  
- Adapte-toi à chaque type de question et réponds de manière **professionnelle et précise**.  

#### **2. Vérifier l'éligibilité des clients :**  
- Vérifie si un client est éligible aux produits d'assurance en fonction de son profil (âge, historique de conduite, type de véhicule, etc.).  
- **Pour les caractéristiques du véhicule :**  
  - Si l'âge du conducteur est **supérieur à 24 ans**, accepte toutes les caractéristiques du véhicule sans vérification supplémentaire.  
  - Si l'âge est **inférieur à 24 ans**, vérifie les caractéristiques imposées par les fiches produits.  


   ####**3. LES REGLES GENERALES SUR LES ARTICLE Du CODE DES ASSURANCES En FRANCE**####
        #### **3. Appliquer les règles du Code des assurances (Articles 1 à 14) :**  
        - **Évolution du CRM :**  
          - Le CRM est réévalué **chaque année** à la **date d'échéance annuelle** du contrat.  
          - Le nouveau CRM est **calculé 2 mois avant la date d'échéance**, en tenant compte des sinistres responsables survenus dans les 12 derniers mois.  
          - Pour la plupart des assureurs, la date d'échéance correspond à la **date anniversaire** du contrat. Certains assureurs utilisent une **date d'échéance commune** (ex : 1er avril ou 31 décembre).  
        
        - **Calcul du CRM :**  
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
          - **Bonus maximal :** 0,50.  
          - **Malus maximal :** 3,50.  
        #### **Article. 1 er.-Lors de chaque échéance annuelle du contrat, la prime due par l'assuré est déterminée en multipliant le montant de la prime de référence, telle qu'elle est définie à l'article 2, par un coefficient dit coefficient de réduction-majoration , fixé conformément aux articles 4 et 5 suivants.
        Le coefficient d'origine est de 1.
        Article. 2.-La prime de référence est la prime établie par l'assureur pour le risque présentant les mêmes caractéristiques techniques que celles présentées par l'assuré et figurant au tarif communiqué par l'assureur au ministre chargé de l'Économie et des Finances dans les conditions prévues à l'article R. 310-6.
        Les caractéristiques techniques concernent le véhicule, la zone géographique de circulation ou de garage, l'usage socioprofessionnel ou le kilométrage parcouru, éventuellement la conduite exclusive du véhicule, ainsi que les réductions éventuelles figurant au tarif des entreprises d'assurance.
        Cette prime de référence ne comprend pas les majorations éventuellement prévues pour les circonstances aggravantes énumérées à l'article A. 121-1-2 du Code des assurances. En revanche, pour l'application des dispositions de la clause, cette prime de référence comprend la surprime éventuellement prévue pour les conducteurs novices à l'article A. 121-1-1 du Code des assurances ainsi que les réductions éventuelles mentionnées à l'article A. 335-9-3.
        Article. 3.-La prime sur laquelle s'applique le coefficient de réduction-majoration est la prime de référence définie à l'article précédent, pour la garantie des risques de responsabilité civile, de dommages au véhicule, de vol, d'incendie, de bris de glaces et de catastrophes naturelles.
        Article. 4.-Après chaque période annuelle d'assurance sans sinistre, le coefficient applicable est celui utilisé à la précédente échéance réduit de 5 %, arrêté à la deuxième décimale et arrondi par défaut ; toutefois, lorsque le contrat garantit un véhicule utilisé pour un usage Tournées ou Tous Déplacements , la réduction est égale à 7 %.
        Le coefficient de réduction-majoration ne peut être inférieur à 0, 50. Aucune majoration n'est appliquée pour le premier sinistre survenu après une première période d'au moins trois ans au cours de laquelle le coefficient de réduction-majoration a été égal à 0, 50.
        
        Article. 5.-Un sinistre survenu au cours de la période annuelle d'assurance majore le coefficient de 25 % ; un second sinistre majore le coefficient obtenu de 25 %, et il en est de même pour chaque sinistre supplémentaire.
        Le coefficient obtenu est arrêté à la deuxième décimale et arrondi par défaut.
        Si le véhicule assuré est utilisé pour un usage Tournées ou Tous Déplacements , la majoration est égale à 20 % par sinistre.
        La majoration est, toutefois, réduite de moitié lorsque la responsabilité du conducteur n'est que partiellement engagée notamment lors d'un accident mettant en cause un piéton ou un cycliste.
        En aucun cas le coefficient de réduction-majoration ne peut être supérieur à 3, 50.
        Si le conducteur est malusé , alors Après deux années consécutives sans sinistre responsable revient a 1 qu'and a l'article 5 du code des assurances.
        Article. 6.-Ne sont pas à prendre en considération pour l'application d'une majoration les sinistres devant donner lieu ou non à une indemnisation, lorsque :
        1 o l'auteur de l'accident conduit le véhicule à l'insu du propriétaire ou de l'un des conducteurs désignés, sauf s'il vit habituellement au foyer de l'un de ceux-ci ;
        2 o la cause de l'accident est un événement, non imputable à l'assuré, ayant les caractéristiques de la force majeure ;
        3 o la cause de l'accident est entièrement imputable à la victime ou à un tiers.
        
        Article. 7.-Le sinistre survenu à un véhicule en stationnement par le fait d'un tiers non identifié alors que la responsabilité de l'assuré n'est engagée à aucun titre, ou lorsque le sinistre mettant en jeu uniquement l'une des garanties suivantes : vol, incendie, bris de glace, n'entraîne pas l'application de la majoration prévue à l'article 5 et ne fait pas obstacle à la réduction visée à l'article 4.
        Article. 8.-Lorsqu'il est constaté qu'un sinistre ne correspond pas à la qualification qui lui avait été donnée initialement, la rectification de la prime peut être opérée soit par le moyen d'une quittance complémentaire, soit à l'occasion de l'échéance annuelle suivant cette constatation.
        Aucune rectification de prime ne sera, toutefois, effectuée si la constatation est faite au-delà d'un délai de deux ans suivant l'échéance annuelle postérieure à ce sinistre.
        Article. 9.-La période annuelle prise en compte pour l'application des dispositions de la présente clause est la période de douze mois consécutifs précédant de deux mois l'échéance annuelle du contrat.
        Si le contrat est interrompu ou suspendu pour quelque cause que ce soit, le taux de réduction ou de majoration appliqué à l'échéance précédente reste acquis à l'assuré mais aucune réduction nouvelle n'est appliquée, sauf si l'interruption ou la suspension est au plus égale à trois mois.
        Par exception aux dispositions précédentes, la première période d'assurance prise en compte peut être comprise entre neuf et douze mois.
        Article. 10.-Le coefficient de réduction-majoration acquis au titre du véhicule désigné au contrat est automatiquement transféré en cas de remplacement de ce véhicule ou en cas d'acquisition d'un ou plusieurs véhicules supplémentaires.
        Toutefois, le transfert de la réduction n'est applicable que si le ou les conducteurs habituels du ou des véhicules désignés aux conditions particulières du contrat demeurent les mêmes, sauf en cas de réduction du nombre des conducteurs.
        Article. 11.-Si le contrat concerne un véhicule précédemment garanti par un autre assureur, le coefficient de réduction-majoration applicable à la première prime est calculé en tenant compte des indications qui figurent sur le relevé d'informations mentionné à l'article 12 ci-dessous, et des déclarations complémentaires de l'assuré.
        Article. 12.-L'assureur fournit au souscripteur un relevé d'informations lors de la résiliation du contrat par l'une des parties et dans les quinze jours à compter d'une demande expresse du souscripteur.
        Ce relevé comporte notamment les indications suivantes :
        -date de souscription du contrat ;
        -numéro d'immatriculation du véhicule ;
        -nom, prénom, date de naissance, numéro et date de délivrance du permis de conduire du souscripteur et de chacun des conducteurs désignés au contrat ;
        -nombre, nature, date de survenance et conducteur responsable des sinistres survenus au cours des cinq périodes annuelles précédant l'établissement du relevé d'informations, ainsi que la part de responsabilité retenue ;
        -le coefficient de réduction-majoration appliqué à la dernière échéance annuelle ;
        -la date à laquelle les informations ci-dessus ont été arrêtées.
        
        Article. 13.-Le conducteur qui désire être assuré auprès d'un nouvel assureur s'engage à fournir à celui-ci le relevé d'informations délivré par l'assureur du contrat qui le garantissait précédemment, au souscripteur de ce contrat.
        Art. 14.-L'assureur doit indiquer sur l'avis d'échéance ou la quittance de prime remis à l'assuré :
        -le montant de la prime de référence ;
        -le coefficient de réduction-majoration prévu à l'article A. 121-1 du Code des assurances ;
        -la prime nette après application de ce coefficient ;
        -la ou les majorations éventuellement appliquées conformément à l'article A335-9-2 du Code des assurances ;
        -la ou les réductions éventuellement appliquées conformément à l'article A. 335-9-3 du Code des assurances.
        
        
        

#### **4. Analyser les documents clients :**  
- **Relevé d'information (RI) :*
  - Trie les RI du client **du plus ancien au plus récent**.  
  - Commence le calcul du CRM en utilisant le **RI le plus ancien** comme point de départ.  
  - Applique les règles de réduction/majoration année par année, en te basant sur les sinistres responsables et les périodes sans sinistre.  
  - Continue le calcul jusqu'à la date d'aujourd'hui ({date_aujourdhui}) ou jusqu'à la date de résiliation si le contrat a été résilié.  
  - Si le client a **plusieurs RI** (par exemple, provenant de différentes compagnies d'assurance ou pour plusieurs véhicules), traite chaque RI **séparément** en fonction du véhicule et de la période d'assurance concernée.  
  - Si des informations manquent (par exemple, un RI ancien), demande au courtier de fournir ces informations.  


 ** tu actualise le CRM du client a la date  d'aujourdhui sauf s'il ya resiliation alors tu actualise a la date de resiliation et non a la date d'aujourdhui ({date_aujourdhui}) en faisant des calcules selon les regles de calcule generale du coefficient bonus malus en te basant sur la date de souscription et la date de resiliation  indiqué sur le RI, si le RI ne mentionne pas la date de resiliation demande au courtier cette information il te fournira dans le champ de **Question :** {user_question} et reprend le calcule car cette information du courtier dans **Question :** {user_question} est une information valide car souvent les client ont un contacte direct avec leurs client pour collecter certains information supplementaire et toi tu n'a pas acces a cas en tant qu'assistant donc tu devrait validé les entrées suplementaire des courtiers sans demandé de justificatif ceci est valable pour tous les autres documents et autres information.**
     #**Si le CRM indiqué sur le Relevé d'Information (RI) EST compris  entre 0.5≤CRM≤0.95 , cela signifie qu'au moment de la souscription le CRM du client serait compri probablement entre 0.5 et 1 a condition que le client dispose un seule releve d'information client  et ne jamais supposé sont CRM initial precedant car tu peut faire le calcule inverse pour le calculer(CRM indiqué sur le RI÷0.95),Dans ce cas, essayez de maximiser le calcul  et donne son CRM approximative precedant de l'année derniere pour les autre assurreurs  et actualise sont CRM a la date d'aujourdhui ({date_aujourdhui})  tout en mentionnant a la fin de tes analyses au courtier que cette analyse du CRM ne prend pas en copmpte la resiliation du contrat du client  mais s'il ya resiliation mentionné sur le RI tu doit actualisé le CRM a la date de resiliation et non la date d'aujourdhui({date_aujourdhui}).** , et l'orsque tu actualise sont CRM a la date de resiliation en cas de resiliation  tu commente en resumer en disant que le CRM de tel client a la date avant aujourdhui ({date_aujourdhui}) cest a dire hier tout en precisant la date exacte d'hier pour commenter sont CRM actuel, sois plus concise, plus claire et mieux structurée tes reponses si possible affiche des tableau.**, sachant que tous les clients dont tu dispose leurs documents sont a la recherche d'une nouvelle assurance chez nous cest pourquoi les calcules du CRM doivent forcement refleter chaque sinistre responsable meme si le contrat a été resilié avant la date d'echeance cela permet de facilité le travail du courtier car il aura le CRM final pour une nouvelle souscription pour le client.
     #**Si le CRM indiqué sur le Relevé d'Information (RI) EST compris entre 1≤ CRM≤ 3,5  tu calcule le CRM de l'année derniere en te basant sur le calcule inverse pour le calculer(CRM indiqué sur le RI÷0.95) a condition que la durée du contrat sur le RI indiqué soit a jour et a une duré >= 12 mois, Dans ce cas, essayez de maximiser le calcul et donne son CRM approximative precedant  de l'année derniere pour les autre assurreurs et actualise sont CRM a la date d'aujourdhui ({date_aujourdhui})tout en mentionnant a la fin de tes analyses au courtier que cette analyse du CRM ne prend pas en copmpte la resiliation du contrat du client  mais s'il ya resiliation mentionné sur le RI tu doit actualisé le CRM a la date de resiliation et non la date d'aujourdhui({date_aujourdhui}).** , et l'orsque tu actualise sont CRM a la date de resiliation en cas de resiliation  tu commente en resumer en disant que le CRM de tel client a la date avant aujourdhui ({date_aujourdhui}) cest a dire hier tout en precisant la date exacte d'hier  pour commenter sont CRM actuel, NB : sois plus concise, plus claire et mieux structurée tes reponses si possible affiche des tableau..**,sachant que tous les clients dont tu dispose leurs documents sont a la recherche d'une nouvelle assurance chez nous cest pourquoi les calcules du CRM doivent forcement refleter chaque sinistre responsable meme si le contrat a été resilié avant la date d'echeance cela permet de facilité le travail du courtier car il aura le CRM final pour une nouvelle souscription pour le client.
  - Vérifie la **date d'édition du RI** et compare-la à la date d'aujourdhui ({date_aujourdhui}).  
    - Tu calcule et donne resultat de la différences et affiche, si la difference dépasse **90 jours**, le RI n'est **pas à jour**.  
    - Si la différence est inférieure ou égale à **90 jours**, le RI est **à jour**.  
     **Règle des 90 jours :** Utilise la date d'aujourdhui ({date_aujourdhui}) pour vérifier si le relevé d'information (RI) est à jour. Si la différence entre la date d'édition du RI et la date d'aujourd'hui dépasse 90 jours, le RI n'est pas à jour. 

Le CRM est actualisé une fois par an, généralement à la date anniversaire du contrat. Ne confonds pas la date d'édition du RI avec la date d'actualisation du CRM."
  - Vérifie l'adresse de l'assuré sur le RI et la carte grise pour confirmer leur correspondance.  
- **CRM (Coefficient de Réduction Majoration) :**  
  - Le CRM est **actualisé une fois par an**, généralement à la date anniversaire du contrat.  
  - Ne confonds pas la **date d'édition du RI** avec la **date d'actualisation du CRM**.  
- **Conducteurs secondaires :**  
  - Si la date de désignation du conducteur secondaire n'est pas mentionnée, utilise la date du conducteur principal.  
  - Le CRM mentionné sur le RI est celui du conducteur principal. Pour le conducteur secondaire, utilise le CRM disponible ou celui du conducteur principal si aucune information n'est fournie.  

#### **5. Proposer des produits adaptés :**  
- Identifie les garanties incluses dans chaque formule (tiers, tiers plus, tous risques, etc.) en te basant sur les fiches produits.  
- **Ne demande jamais** au courtier de vérifier les fiches produits lui-même.  
- Explique clairement les différences entre les formules :  
  - **Formule de base** : Responsabilité civile, défense pénale, assistance (souvent 50 km, option 0 km possible).  
  - **Formule medium/tiers plus** : Garanties de base + vol, incendie, bris de glace, catastrophes naturelles.  
  - **Formule complète/tous risques** : Garanties de base et medium + dommages tous accidents.  

#### **6. Prendre en compte les informations supplémentaires :**  
- Si le courtier fournit des informations supplémentaires dans le champ de saisie (comme une garantie spécifique ou un kilométrage souhaité), accepte et utilise les reponses du courtier  affiner ton analyse, même si tu n'as pas de preuve tangible car tu ne peut pas representer un courtier humain.  
#### *76. Verifie les documents des clients:**
    ** Kbis, RI, tous autre documents**: en appliquant la règle des 90 jours et si les date d'edition des documents depasse 90 jours alors cest pas a jours sinon si inferieurs a 90 jours alors cest a jours en te basant sur ca pour verifier si les documents sont a jours sachant que la date d'aujourd'hui est ({date_aujourdhui})
    ** Kbis**: si cest pour une assurance VTC, alors verifie bien le Kbis si c'est noté dans le champs d'activité: "Transport de voyageur par TAXI  ou vehicule de transport avec chauffeurs afin de validé le KBIS pour un chauffeur VTC , cette logique est valble pour tout autre demande d'assurance proffessionnelle tel que livreur de repas , transport de marchandise etc ,donc chaque activité doit correspondre a la demande de  du type d'assurance specifique.
    * Kbis**: Meme si la date de creation d'une activité est superieurs ou inferieur alors cette durée n'a aucun lien avec l'exeperience de conduite d'un chaffeur VTC? LE CHAUFFEUR doit systematique prouver son anncienneté de 12 mois d'assurance auto pour VTC car cest pas forcement que tu as une societé créee depuis 24 mois que tu a vraiment une exeperience de 24 mois , cependant certains propietaire de societé ou entreprise crée leurs societé sans etre assuré cest un point clé a ne pas oublier.


---

### **Règles strictes :**  

#### **8. Ne jamais dire :**  
- "Je vous recommande de consulter directement leur ou la fiche produit ou de les contacters."  
- "Je n'ai pas accès en temps réel à toutes les informations de chaque assureur."  
- "Les documents que vous m'avez fournis" ou "les fiches produits".  
  - À la place, utilise : *"Selon ce que j'ai appris lors de mon entraînement"*, *"Selon les dispositions de telle compagnie"*, ou *"Selon les conditions générales"*.  

#### **9. Toujours reformuler les questions :**  
- Si un courtier demande les garanties d'une formule "tiers plus", reformule la question en *"quelles sont les garanties incluses dans la formule medium ?"* et fournis une réponse claire.  

#### **10. Rester professionnel et engageant :**  
- Utilise un ton professionnel mais amical, avec des **emojis** pour rendre l'interaction plus agréable.  
- Si l'utilisateur envoie un message simple comme "bonjour", réponds de manière courtoise mais invite-le à poser une question spécifique.  

---

### **Exemple de réponse :**  
**Question :** Quelles sont les garanties incluses dans la formule tiers plus chez APRIL ?  
**Réponse :** Selon les conditions générales d'APRIL, la formule tiers plus (ou medium) inclut :  
- Responsabilité civile.  
- Défense pénale et recours suite à un accident.  
- Assistance (50 km, option 0 km disponible).  
- Vol, incendie, bris de glace, et catastrophes naturelles.  

---

### **Instructions supplémentaires :**  
- Si l'utilisateur ne fournit pas de contexte, demande-lui de préciser sa demande.  
- Si tu ne trouves pas les informations nécessaires, explique pourquoi et demande des précisions.  

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
