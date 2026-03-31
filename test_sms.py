import os
import sys

# S'assurer que le chemin est correct pour importer 'routes'
sys.path.insert(0, os.path.abspath("."))

# Vos identifiants Twilio — à renseigner dans .env ou en variables d'environnement
# Ne jamais hardcoder ces valeurs ici
TWILIO_SID    = os.environ.get("TWILIO_ACCOUNT_SID", "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
TWILIO_TOKEN  = os.environ.get("TWILIO_AUTH_TOKEN",  "your_auth_token_here")
TWILIO_NUMBER = os.environ.get("TWILIO_PHONE_FROM",  "+1xxxxxxxxxx")
DEST_NUMBER   = os.environ.get("TEST_DEST_NUMBER",   "+216xxxxxxxxx")

# Configuration des variables d'environnement requises par Twilio
os.environ["TWILIO_ACCOUNT_SID"]  = TWILIO_SID
os.environ["TWILIO_AUTH_TOKEN"]   = TWILIO_TOKEN
os.environ["TWILIO_PHONE_NUMBER"] = TWILIO_NUMBER

try:
    from routes.smsAlerts import send_sms
except ModuleNotFoundError as e:
    print(f"❌ Erreur d'importation : {e}")
    print("👉 Solution : Installez le package manquant en tapant : pip install twilio")
    sys.exit(1)

print(f"⏳ Tentative d'envoi d'un vrai SMS vers {DEST_NUMBER}...")

try:
    result = send_sms(
        to_number=DEST_NUMBER,
        message=(
            "ALERTE - AirWatch Tunisia\n"
            "Zone: Sfax Nord\n"
            "Pollution moderee detectee.\n"
            "NO2: 85 ug/m3 | SO2: 52 ug/m3\n"
            "Info: airwatch-tn.gov.tn"
        ),
        simulate=False  # Faux = envoi réel
    )
    
    if result.get('success'):
        print(f"✅ SUCCÈS ! Le message a été envoyé à l'opérateur. ID: {result.get('sid')}")
    else:
        print(f"⚠️ ÉCHEC : {result}")

except Exception as e:
    print(f"❌ ERREUR CRITIQUE lors de l'envoi : {e}")
    print("\n👉 PISTES DE SOLUTION :")
    print("1. Si vous avez un compte Twilio 'Trial' (Gratuit), vous DEVEZ ajouter et vérifier votre numéro tunisien (+216...) dans la console Twilio (Verified Caller IDs).")
    print("2. Vérifiez que votre TWILIO_TOKEN est toujours valide et n'a pas été révoqué.")