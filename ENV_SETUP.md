# 🔐 Environment Variables Setup

## Quick Setup

### 1. Create your `.env` file

```bash
cp .env.example .env
```

### 2. Fill in your credentials

```env
# Anthropic Claude API (for AI report generation)
ANTHROPIC_API_KEY=sk-ant-...

# Twilio (for SMS alerts — optional)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_FROM=+1xxxxxxxxxx

# For test_sms.py — destination number for testing
TEST_DEST_NUMBER=+216xxxxxxxxx

# Google Earth Engine (optional — simulation mode available without it)
GEE_SERVICE_ACCOUNT=your-sa@project.iam.gserviceaccount.com
GEE_KEY_FILE=/path/to/gee_key.json
GEE_PROJECT=your-gee-project-id
```

---

## Where to get the keys

### 🤖 Anthropic API Key
1. Go to https://console.anthropic.com/
2. Sign in and create a new API key
3. Copy it into `.env`

### 📱 Twilio Credentials
1. Go to https://www.twilio.com/console
2. Copy `Account SID` and `Auth Token`
3. Add a phone number and set it as `TWILIO_PHONE_FROM`

> **Trial account:** you must verify your destination number in the Twilio console
> before sending real SMS messages.

### 🌍 Google Earth Engine
1. Go to https://code.earthengine.google.com/
2. Create or select a GCP project with the Earth Engine API enabled
3. Create a service account, download the JSON key
4. Set `GEE_SERVICE_ACCOUNT`, `GEE_KEY_FILE`, and `GEE_PROJECT`

> Without GEE, the system runs in **simulation mode** — all features work
> with realistic synthetic data.

---

## ⚠️ Security rules

- **Never commit** `.env` (it is listed in `.gitignore`)
- **Never hardcode** credentials directly in source files
- Rotate keys regularly
- For production: use a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.)

---

## Verify your setup

```python
from config.settings import ANTHROPIC_API_KEY, TWILIO_ACCOUNT_SID

print(f"Anthropic key loaded : {bool(ANTHROPIC_API_KEY)}")
print(f"Twilio SID loaded    : {bool(TWILIO_ACCOUNT_SID)}")
```

---

## Production deployment (no .env file)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export TWILIO_ACCOUNT_SID="AC..."
export TWILIO_AUTH_TOKEN="..."

streamlit run dashboard.py
```
