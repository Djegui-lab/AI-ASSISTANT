import streamlit as st
import json
import firebase_admin
from firebase_admin import credentials
import os

# Titre de l'application Streamlit
st.title("Application Streamlit avec Firebase")

# Récupérer les credentials Firebase depuis la variable d'environnement
firebase_credentials = os.environ.get("firebasejson")

if not firebase_credentials:
    st.error("La variable d'environnement 'firebasejson' n'est pas définie.")
else:
    try:
        # Convertir la chaîne JSON en dictionnaire
        cred_dict = json.loads(firebase_credentials)
        
        # Initialiser Firebase
        if not firebase_admin._apps:  # Vérifier si Firebase n'est pas déjà initialisé
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            st.success("Firebase initialisé avec succès !")
    except json.JSONDecodeError:
        st.error("Le contenu de 'firebasejson' n'est pas un JSON valide.")
    except Exception as e:
        st.error(f"Erreur lors de l'initialisation de Firebase : {e}")

# Votre application Streamlit continue ici
st.write("Bienvenue dans l'application Streamlit avec Firebase !")
