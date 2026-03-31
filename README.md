# 🌿 AirWatch Tunisia
### Satellite-Based Industrial Pollution Monitoring | EcoWave 2.0 Hackathon

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Streamlit](https://img.shields.io/badge/Dashboard-Streamlit-red?logo=streamlit)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Hackathon%20Demo-orange)

Automated detection of NO₂ and SO₂ pollution spikes over Tunisian industrial zones,
powered by ESA Copernicus satellite data (Sentinel-5P / Sentinel-2) and AI models.
When a critical anomaly is detected, nearby residents receive real-time SMS alerts.

---

## 🎯 Problem Statement

Tunisia's industrial zones — Gabès (chemical complex), Sfax, Bizerte, Gafsa (phosphate) — emit
significant levels of NO₂ and SO₂. Traditional monitoring networks are sparse, expensive,
and offer no real-time public alerts. AirWatch Tunisia bridges this gap using freely
available satellite imagery and ML-based anomaly detection.

---

## 🏗️ Architecture

```
airwatch-tunisia/
├── config/
│   ├── settings.py              # Global parameters (thresholds, dates, API keys)
│   └── geeAuth.py               # Google Earth Engine auth + zone loading
├── routes/
│   ├── sentinel5pData.py        # NO2/SO2 retrieval from Sentinel-5P
│   ├── anomalyDetection.py      # Isolation Forest anomaly detection
│   ├── sentinel2Analysis.py     # Fine spatial analysis with Sentinel-2
│   ├── lstmPrediction.py        # 7-day LSTM risk forecast
│   ├── reportGenerator.py       # Natural language reports via Claude API
│   └── smsAlerts.py             # Geo-targeted SMS alerts via Twilio
├── utils/
│   └── helpers.py               # Shared utility functions
├── data/
│   └── industrial_zones.geojson # Tunisian industrial zones (6 zones)
├── models/                      # Auto-generated trained models
├── reports/                     # Auto-generated reports
├── dashboard.py                 # Interactive Streamlit dashboard
├── main.py                      # Daily pipeline orchestration
└── requirements.txt
```

---

## ⚙️ How It Works

```
Sentinel-5P (NO2/SO2)
        │
        ▼
  Data Collection  ──► Isolation Forest ──► Anomaly Detected?
  (daily, 6 zones)       (unsupervised)           │
                                              YES  │  NO
                                                   ▼
                                         Sentinel-2 Analysis
                                         (spatial, NDVI, population)
                                                   │
                                                   ▼
                                         LSTM 7-day Forecast
                                                   │
                                                   ▼
                                    Claude API Report Generation
                                                   │
                                                   ▼
                                    Twilio SMS ──► Nearby Residents
```

---

## 🤖 AI Models

| Model             | Type           | Features                        | Goal                          |
|-------------------|----------------|---------------------------------|-------------------------------|
| Isolation Forest  | Unsupervised   | NO2, SO2, weekday, month        | Anomaly detection (5% rate)   |
| LSTM              | Supervised     | NO2, SO2, temporal, weather     | 7-day risk prediction         |
| Claude API (LLM)  | Generative     | Structured alert data           | Natural language report        |

---

## 🛰️ Data Sources

| Source        | GEE Collection                          | Resolution | Use                    |
|---------------|-----------------------------------------|------------|------------------------|
| Sentinel-5P   | COPERNICUS/S5P/NRTI/L3_NO2             | ~3.5 km    | NO2 concentration      |
| Sentinel-5P   | COPERNICUS/S5P/NRTI/L3_SO2             | ~3.5 km    | SO2 concentration      |
| Sentinel-2    | COPERNICUS/S2_SR_HARMONIZED             | 10 m       | Spatial analysis, NDVI |
| ESA WorldCover| ESA/WorldCover/v200/2023               | 10 m       | Land use               |
| WorldPop      | WorldPop/GP/100m/pop                   | 100 m      | Exposed population     |

---

## 🚨 WHO Thresholds Used

| Pollutant | Daily Threshold | Critical Threshold |
|-----------|----------------|-------------------|
| NO₂       | 25 µg/m³       | 200 µg/m³         |
| SO₂       | 40 µg/m³       | 100 µg/m³         |

---

## 📦 Installation

### 1. Clone & create virtual environment

```bash
git clone https://github.com/Youssef-CS16/airwatch-tunisia.git
cd airwatch-tunisia
python -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate          # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> No GPU? Replace `tensorflow` with `tensorflow-cpu` in `requirements.txt`.

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your credentials:

```env
# Anthropic Claude API (for report generation)
ANTHROPIC_API_KEY=sk-ant-...

# Twilio (for SMS alerts — optional)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_FROM=+1xxxxxxxxxx

# Google Earth Engine (optional — simulation mode available without it)
GEE_SERVICE_ACCOUNT=your-sa@project.iam.gserviceaccount.com
GEE_KEY_FILE=/path/to/gee_key.json
GEE_PROJECT=your-gee-project-id
```

### 4. (Optional) Authenticate Google Earth Engine

```bash
earthengine authenticate
```

> Without GEE, the system runs in **simulation mode** with realistic synthetic data.
> All dashboard features remain fully operational.

---

## 🚀 Usage

### Option A — Full daily pipeline

```bash
python main.py
```

Available flags:

```bash
python main.py --force-refresh    # Re-download all data
python main.py --force-retrain    # Retrain all models
python main.py --date 2025-06-15  # Analyze a specific date
```

### Option B — Interactive dashboard

```bash
streamlit run dashboard.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

### Option C — Modular execution

```python
from config.geeAuth import load_industrial_zones
from routes.sentinel5pData import fetch_all_zones_data
from routes.anomalyDetection import detect_anomalies_for_all_zones

zones = load_industrial_zones("data/industrial_zones.geojson")
pollution_df = fetch_all_zones_data(zones, "2025-01-01", "2025-06-30", gee_available=False)
alerts = detect_anomalies_for_all_zones(pollution_df, zones)
print(alerts)
```

---

## 🌍 Monitored Zones (6)

| Zone ID               | Region            | Main Industry          |
|-----------------------|-------------------|------------------------|
| `sfax_nord`           | Sfax              | Chemical / Port        |
| `gabes_chimie`        | Gabès             | Phosphate / Chemical   |
| `tunis_ben_arous`     | Greater Tunis     | Industrial corridor    |
| `bizerte_port`        | Bizerte           | Refinery / Port        |
| `sousse_industrielle` | Sousse            | Manufacturing          |
| `gafsa_phosphate`     | Gafsa             | Phosphate mining       |

---

## 📲 SMS Alert System

When an anomaly is detected, Twilio sends geo-targeted SMS alerts to residents
within a configurable radius (default: 5 km) of the affected zone.

Example SMS:
```
ALERT - AirWatch Tunisia
Zone: Sfax Nord
Moderate pollution detected.
NO2: 85 µg/m³ | SO2: 52 µg/m³
Info: airwatch-tn.gov.tn
```

> SMS sending requires a valid Twilio account. Without credentials,
> the system runs in **simulation mode** (logs `[SMS SIMULE]` to console).

---

## 🧪 Demo Mode

No API keys? No problem. Run with full simulation:
- Realistic synthetic Sentinel-5P data (seasonal trends + ~5% random anomaly spikes)
- Template-based reports (no Claude API required)
- SMS simulation logged to console
- All dashboard features operational

---

## 🎯 EcoWave 2.0 Alignment

| Criterion       | Implementation                                              |
|-----------------|-------------------------------------------------------------|
| Real problem    | Industrial pollution in Tunisia (Gabès, Sfax, Gafsa...)    |
| Satellite data  | Sentinel-5P + Sentinel-2 (ESA Copernicus, open access)      |
| Measurable impact | Exposed population, NDVI degradation, residential proximity |
| Scalability     | Add zones via GeoJSON; multi-country extension possible     |
| SDGs            | SDG 3 (Health), SDG 11 (Cities), SDG 13 (Climate)          |

---

## ⚠️ Security Notice

- **Never commit** your `.env` file (it is in `.gitignore`)
- **Never hardcode** API keys or tokens in source files
- Rotate credentials regularly
- For production: use a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.)

---

## 📄 License

MIT License — free to use, modify, and distribute.

---

## 👥 Team | EcoWave 2.0 Hackathon

Built for the **IEEE EcoWave 2.0** hackathon.
Contact: airwatch-tunisia@ieee.org
