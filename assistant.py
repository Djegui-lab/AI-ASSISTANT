import json
import firebase_admin
from firebase_admin import credentials

# JSON des credentials Firebase
firebase_credentials = os.environ.get("firebasejson")

# Initialiser Firebase
try:
    cred = credentials.Certificate(firebase_credentials)
    firebase_admin.initialize_app(cred)
    print("Firebase initialisé avec succès !")
except Exception as e:
    print(f"Erreur lors de l'initialisation de Firebase : {e}")
