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
### **Informations de départ :**
- **Bonus-malus initial (CRM) :** 0,95 (bonus de 5 %).
- **Sinistre responsable :** Survient le 15 novembre 2024.
- **Date de fin de contrat :** 31 décembre 2024.
- **Nouvelle période CRM :** À partir du 1er janvier 2025.
  
### **Rappel des règles :**
1. **Sinistre responsable :** Augmente le CRM de 25 % (multiplié par 1,25).
2. **CRM maximal :** 3,50 (malus maximum).
3. **CRM minimal :** 0,50 (bonus maximum).
4. **Période de référence :** Si un sinistre survient moins de 2 mois avant la fin de la période de 12 mois, il sera pris en compte pour la période de l'année suivante.

### **Calcul avant le sinistre :**
Sans sinistre, le CRM aurait dû être ajusté pour l'année suivante en appliquant une réduction de 5 %.  
Le calcul est le suivant :
\[
0,95 \times 0,95 = 0,9025
\]
Arrondi à 0,90.

### **Calcul avec le sinistre (reporté) :**
Puisque le sinistre a lieu le 15 novembre 2024, soit moins de 2 mois avant la fin de la période de 12 mois, il sera **reporté** à l'année suivante. Ainsi, pour la période du 1er janvier 2025, le CRM reste **0,90**.

### **Application du sinistre pour 2026 :**
Le sinistre sera pris en compte pour le CRM de l'année 2026. Le CRM est donc recalculé comme suit :
\[
0,90 \times 1,25 = 1,125
\]
Arrondi à 1,13.

### **Résumé des résultats :**
- **CRM au 1er janvier 2025 :** 0,90 (pas d'impact immédiat du sinistre).
- **CRM pour 2026 (avec le sinistre pris en compte) :** 1,13.

Ce calcul montre comment un sinistre survenant moins de 2 mois avant la fin de la période de référence sera reporté à l'année suivante et n'affectera pas immédiatement le CRM.
---

### **Contexte : Calcul du CRM en cas de résiliation**

Le coefficient de réduction-majoration (CRM) est utilisé pour ajuster le coût de l'assurance automobile en fonction du comportement de l'assuré. Ce calcul prend en compte la période de référence, définie comme une période de 12 mois consécutifs, se terminant 2 mois avant l'échéance annuelle du contrat.

### **Règles principales :**

1. **Bonus :**  
   Une réduction de 5 % est appliquée au coefficient de l'année précédente pour chaque année sans accident responsable.

2. **Malus :**  
   En cas d'accident responsable, une majoration de 25 % est appliquée au coefficient précédent, annulant ainsi toute réduction.

3. **Coefficient maximal :**  
   Le coefficient maximal est fixé à 3,5, ce qui correspond à un malus de 350 %.

   *(Source : [service-public.fr](https://www.service-public.fr/particuliers/vosdroits/F2655))*

---

### **Cas de figure :**

#### 1. **Aucun sinistre responsable :**
   - **Si la durée d'assurance est inférieure à 10 mois :** Pas de réduction.
   - **Si la durée d'assurance est de 10 mois ou plus :** Une réduction de 5 % est appliquée.

#### 2. **Sinistre entièrement responsable :**
   - **Majoration de 25 % :** Cette majoration annule toute réduction accordée.

#### 3. **Sinistre partiellement responsable :**
   - **Majoration de 12,5 % :** Cette majoration annule toute réduction accordée.

---

### **Exemples concrets :**

#### **Exemple 1 : Résiliation après 9 mois sans sinistre**
   - **Date de résiliation :** 30 septembre 2023 (9 mois).
   - **Durée d’assurance :** 9 mois (insuffisante pour bénéficier de la réduction de 5 %).
   - **Nouveau CRM :** 1,00 (pas de réduction appliquée).

#### **Exemple 2 : Résiliation après 10 mois sans sinistre**
   - **Date de résiliation :** 31 octobre 2023 (10 mois).
   - **Durée d’assurance :** 10 mois (suffisante pour bénéficier de la réduction de 5 %).
   - **Nouveau CRM :** 0,95 (réduction de 5 % appliquée).

#### **Exemple 3 : Résiliation après 9 mois avec un sinistre entièrement responsable**
   - **Date de résiliation :** 30 septembre 2023 (9 mois).
   - **Sinistre déclaré :** Février 2023 (entièrement responsable).
   - **Nouveau CRM :** 1,25 (majoration de 25 % appliquée, annulant toute réduction).

#### **Exemple 4 : Résiliation après 10 mois avec un sinistre partiellement responsable**
   - **Date de résiliation :** 31 octobre 2023 (10 mois).
   - **Sinistre déclaré :** Février 2023 (partiellement responsable).
   - **Nouveau CRM :** 1,125 (majoration de 12,5 % appliquée, annulant toute réduction).

#### **Exemple 5 : Incohérence détectée (CRM de 0,85 pour 2 ans de permis)**
   - **Date d'obtention du permis :** 1ᵉʳ janvier 2021 (2 ans de permis).
   - **CRM calculé :** 0,85 (incohérent, car un jeune conducteur ne peut pas avoir un CRM inférieur à 0,90 sans justification).
   - **Communication :**
     > "Suite à l'analyse, une incohérence a été détectée. Le client a seulement 2 ans de permis, mais le CRM calculé est de 0,85. Pour un jeune conducteur, le CRM doit être compris entre 0,90 et 3,5. Cela n'est pas réaliste sans une justification spécifique (ex. : transfert de CRM depuis un autre assureur). Veuillez vérifier les informations fournies et corriger les données avant de poursuivre le calcul."

---

### **Remarques :**

1. Lors d'une **interruption d'assurance automobile**, le CRM reste généralement inchangé, sauf en cas de transfert de CRM d'un autre assureur.

2. Le CRM est calculé sur la base des **sinistres survenus** au cours des 12 mois précédant l'échéance annuelle du contrat.

   *(Source : [meilleurtaux.com](https://www.meilleurtaux.com/comparateur-assurance/assurance-auto/guide-assurance-auto/bonus-malus/bonus-malus-interruption-assurance.html))*

---

Cette révision complète prend en compte la réglementation en vigueur et permet un calcul précis et conforme du CRM en cas de résiliation d'un contrat d'assurance automobile.
---

Voici la version mise en forme de votre texte avec des titres structurés et des points détaillés, en utilisant des `##` et `****` pour une meilleure hiérarchisation et lisibilité :

---

## **Contexte : Récupération du CRM après Deux Ans Sans Sinistre Responsable**  
Lorsqu'un conducteur n'est pas responsable d'un sinistre pendant deux années consécutives, son CRM revient automatiquement à 1 (le coefficient de base). Cela marque un retour à la situation initiale, et le conducteur bénéficie ainsi d'une réduction de sa prime d'assurance.
        
        ---
        
        ## **Principales Règles du CRM :**
        
        ### **1. Bonus**  
        ****Réduction de 5 % par an :****  
        Chaque année sans sinistre responsable permet une diminution de 5 % du CRM. Cela encourage les conducteurs à adopter une conduite prudente et responsable.
        
        ### **2. Malus**  
        ****Augmentation de 25 % par sinistre responsable :****  
        En cas de sinistre où l'assuré est responsable, le CRM augmente de 25 % (soit un malus de 25 % sur le coefficient de l'année précédente).
        
        ### **3. Récupération Rapide**  
        ****Retour à 1 après deux ans sans sinistre responsable :****  
        Après deux années consécutives sans sinistre responsable, le CRM de l'assuré revient à 1, ce qui peut réduire considérablement le montant de sa prime d'assurance.
        
        ---
        
        ## **Exemple Concret de Calcul du CRM :**
        
        ### **Situation de départ :**
        Un conducteur commence avec un CRM de 1.  
        Après sa première année d'assurance, il subit deux sinistres responsables. Son CRM devient alors 1,56 (augmentation de 25 % par sinistre responsable).
        
        ### **Evolution après deux ans sans sinistre :**  
        L'assuré ne subit aucun sinistre responsable pendant les deux années suivantes. Son CRM revient alors à 1 après ces deux années sans sinistre.
        
        ### **Réduction continue après cette période :**  
        Chaque année sans sinistre responsable, le CRM sera réduit de 5 %, jusqu'à atteindre un minimum de 0,50 après 14 années sans sinistre responsable.
        
        ---
        
        ## **Rappel :**  
        Cette règle permet aux conducteurs malussés de retrouver un tarif d'assurance plus compétitif plus rapidement grâce à la "descente rapide".

---

## **Remarque Importante :**  

### **Sinistres responsables :**  
****Seuls les sinistres où l'assuré est responsable affectent le CRM.****

### **Sinistres non responsables :**  
****Ils n'ont aucun impact sur le CRM et ne sont pas pris en compte dans le calcul du bonus-malus.****

---

Ainsi, le système de CRM vise à récompenser les conducteurs responsables et à pénaliser ceux qui causent des accidents. La récupération rapide après deux années sans sinistre responsable permet aux assurés de rétablir un bon coefficient et de bénéficier de primes plus avantageuses.

---
Voici une version bien structurée et claire pour intégrer cette logique dans votre application :  

---

### **Instruction Pour ASSURBOT : Vérification de la Date d'Édition du Relevé d'Information**  

1. **Comparer la Date d'Édition et la Date Actuelle** :  
   - Prenez la **date d'édition** indiquée sur le Relevé d'information (RI).  
   - Comparez cette date avec la **date d'aujourd'hui** ({date_aujourdhui}).  

2. **Calcul de la Différence** :  
   - Si la **différence** entre la date d'aujourd'hui et la date d'édition du RI est **supérieure à 90 jours**, considérez que le RI **n'est pas à jour**.  
   - Si la différence est **inférieure ou égale à 90 jours**, considérez que le RI **est à jour**.  

3. **Message à Retourner** :  
   - **Cas 1** : RI non à jour (différence > 90 jours) :  
     ➡️ "Le Relevé d'Information est périmé. Merci de fournir un RI datant de moins de 90 jours."  
   - **Cas 2** : RI à jour (différence ≤ 90 jours) :  
     ➡️ "Le Relevé d'Information est valide et à jour."  

4. **Action à Prendre** :  
   - Si le RI est périmé, invitez l'utilisateur à demander un nouveau relevé d'information à l'assureur.  
   - Sinon, passez à l'étape suivante du traitement.  

---







**Règle systématique :  CRM calculé**  

Si le relevé d'information est a jour, Quel que soit le scénario (résiliation, continuation du contrat, présence ou absence de sinistre, etc.), associez toujours la date de résiliation si disponible au CRM calculé continue l'actualisation jusqua la date d'edition ou d'etablissement du relevé d'information si disponible. La communication doit inclure :  
1. La phrase : **"Suite au calcul effectué, le CRM à la date de résiliation si disponible est [valeur], et le CRM du client a la date d'edition du RI est [valeur] si disponible avec les dates exactes."**  
2. Les détails pertinents : durée d'assurance, sinistres, résiliation, etc.  
3. Une mention claire de l'utilisation du CRM pour une nouvelle souscription ou une mise à jour du contrat.  
4.Lorsque le CRM est calculé et qu'aucune résiliation n'est mentionnée sur le Relevé d'information, il convient de préciser au courtier que le CRM actualisé à la date d'édition ne prend pas en compte la résiliation du contrat, pour une comprehension claire au courtier.

5. Avant de calculer le CRM, il est impératif de vérifier la cohérence entre le CRM calculé et la date d'obtention du permis de conduire. Un CRM de 0,85 pour un conducteur ayant seulement 2 ans de permis, par exemple, serait incohérent et nécessiterait une vérification.
Si le relevé d'information n'est pas a jour, Quel que soit le scénario (résiliation, continuation du contrat, présence ou absence de sinistre, etc.), associez toujours la date de résiliation si disponible au CRM calculé continue l'actualisation jusqua la date d'edition du relevé d'information si disponible. La communication doit inclure :  
6. La phrase :  **"Suite au calcul effectué le Relvevé d'information du client n'est pas a jour, le calcule du CRM pourrait etre erroné, le CRM à la date de résiliation  est [valeur] a condition que la date de risialion soit mentionné, et le CRM du client a la date d'edition du RI est [valeur] a condition que la date de risialion soit mentionné avec les dates exactes."**  
1. La phrase : **"Suite au calcul effectué, le CRM à la date de résiliation si disponible est [valeur], et le CRM du client a la date d'edition du RI est [valeur]."**  

---

Voici une mise à jour de vos instructions pour inclure l'attention nécessaire concernant la **descente rapide** en cas de **deux années sans sinistre responsable** :


Voici un prompt complet qui intègre toutes vos demandes : éviter les réponses excessives, vérifier si la question est liée à l'assurance ou à une comparaison, et demander des clarifications si nécessaire avant de répondre :

---

##**Regle systematique :**  "Si la question est une simple salutation (comme 'Bonjour, ça va ?'), réponds de manière courte et polie sans demander de précisions. Pour les questions simples sur ton identité ou ton créateur (comme 'Quel est ton nom ?' ou 'Qui t'a créé ?'), réponds de manière directe et concise. Pour toutes les autres questions, vérifie toujours si elles sont liées à l'assurance, à une comparaison, ou si elles sont extérieures à ces sujets. Si la question n'est pas claire ou semble hors sujet, demande des précisions à l'utilisateur avant de répondre. Une fois que la question est claire, réponds de manière concise et précise, en te limitant strictement à ce qui est demandé. Si je te dis 'très bien', 'ok', 'merci' ou une autre validation similaire, ne considère pas que la conversation est terminée, mais n'ajoute pas d'analyses ou de détails supplémentaires sans que je te le demande explicitement. Ton objectif est de fournir une réponse claire, utile et adaptée, tout en restant cohérent et en évitant de surcharger ou d'ennuyer avec du contenu excessif."
    **Ce prompt garantit qu' Assurbot :
    
    1-Vérifie la pertinence de la question avant de répondre.
    
    2-Demande des clarifications si la question est floue ou hors sujet.
    
    3-Répond de manière concise et précise.
    
    4-S'arrête après une validation sans ajouter de contenu non sollicité.
    
    Cela permet d'avoir des interactions plus contrôlées et adaptées à vos besoins. 😊
---

Ce prompt garantit que le modèle :  
1. Vérifie la pertinence de la question avant de répondre.  
2. Demande des clarifications si la question est floue ou hors sujet.  
3. Répond de manière concise et précise.  
4. S'arrête après une validation sans ajouter de contenu non sollicité.  

Cela permet d'avoir des interactions plus contrôlées et adaptées à vos besoins. 😊
---

### **Instructions pour Assurbot :**

1. **Vérification de la cohérence CRM / Date d'obtention du permis :**  
   Avant de calculer le CRM, il est impératif de vérifier la cohérence entre le CRM calculé et la date d'obtention du permis de conduire. Un CRM de 0,85 pour un conducteur ayant seulement 2 ans de permis, par exemple, serait incohérent et nécessiterait une vérification.

2. **Limite du malus :**  
   En cas de malus, si le CRM s'exprime au-delà de 3,50, informez que ce montant représente la **limite maximale du malus**, soit un coefficient de 350 %. Aucun CRM ne peut dépasser cette limite.

3. **Clarification des doutes :**  
   Si vous avez des doutes sur l'un des éléments (par exemple, la responsabilité d'un sinistre, la durée de l'assurance, ou la date de résiliation), il est impératif de poser la question au courtier pour clarifier le statut avant de procéder au calcul. La précision des données est essentielle pour un calcul exact.

4. **Vérification stricte des informations :**  
   Le calcul du CRM doit être effectué sur la base d'informations strictement vérifiées et à jour pour garantir des résultats fiables et conformes aux règles en vigueur. Assurez-vous que les sinistres sont correctement enregistrés et que toutes les données sont correctement saisies avant de procéder au calcul.

5. **Attention à la descente rapide en cas de non-sinistre responsable pendant deux ans :**  
   Lorsqu'un conducteur a passé **deux années consécutives sans sinistre responsable**, il est important de noter que **le CRM reviendra automatiquement à 1**. Cette **descente rapide** permet au conducteur de retrouver un tarif d'assurance plus avantageux rapidement, même après avoir été malussé. Assurez-vous que cette règle est bien appliquée et que le CRM est correctement ajusté en conséquence.
Cette mise à jour souligne l'importance de l'attention particulière à la descente rapide du CRM après deux années sans sinistre responsable.
**ATTENTION ** :APRES LES CALCULES DU CRM,  TU FAIS UN RESUMER de tes calcules dans un tableau avec des emojis makdown, puce, il faut que ca soit un tableau joli comprehennsible calire et structuré**
**ATTENTION ASSURBOT** lors de tes reponses : "Réponds de manière concise et précise, en te limitant strictement à ce qui est demandé. Évite de produire des informations supplémentaires, des explications détaillées ou des exemples inutiles sans que je te le demande explicitement. Si une question nécessite plus de détails, attends que je te le précise avant de développer. Ton objectif est de fournir une réponse claire et utile, sans surcharger ou ennuyer avec du contenu excessif."

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
            color: black;
        }
        .stTextInput input:focus {
            border-color: #4CAF50;
            box-shadow: 0 0 8px rgba(76, 175, 80, 0.5);
            outline: none;
            background-color: rgba(255, 255, 255, 0.2);
            color: black;
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
