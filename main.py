"""
AirWatch Tunisia — Daily Pipeline Orchestrator
===============================================
Runs the full monitoring pipeline once per day:
  1. Load industrial zones + authenticate GEE (or fall back to simulation)
  2. Fetch / update Sentinel-5P pollution data (NO2, SO2)
  3. Train Isolation Forest models per zone
  4. Detect anomalies for today's date
  5. Run Sentinel-2 fine analysis on alerted zones
  6. Train LSTM + generate 7-day risk forecasts
  7. Generate AI reports for critical zones
"""

import sys
import logging
import pandas as pd
from datetime import datetime
from pathlib import Path

# Make sure the project root is on the import path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from utils.helpers import setup_logging, format_response
from config.settings import (
    INDUSTRIAL_ZONES_FILE, POLLUTION_DATA_FILE,
    ALERTS_LOG_FILE, END_DATE, START_DATE, TRAINING_START_DATE
)
from config.geeAuth import authenticate_gee, load_industrial_zones
from routes.sentinel5pData import fetch_all_zones_data
from routes.anomalyDetection import detect_anomalies_for_all_zones, train_isolation_forest
from routes.sentinel2Analysis import trigger_sentinel2
from routes.lstmPrediction import train_lstm, predict_risk
from routes.reportGenerator import generate_report

setup_logging("INFO")
logger = logging.getLogger(__name__)


def run_daily_pipeline(
    force_data_refresh: bool = False,
    force_retrain: bool = False,
    target_date: str = None
) -> dict:
    """
    Execute the full daily surveillance pipeline.

    Args:
        force_data_refresh: Re-download satellite data even if a local cache exists.
        force_retrain:       Retrain all ML models from scratch.
        target_date:         Date to analyse (YYYY-MM-DD). Defaults to today (UTC).

    Returns:
        A result dict with status code and per-step details.
    """
    start_time = datetime.utcnow()
    today = target_date or start_time.strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info(f"AIRWATCH TUNISIA — Pipeline | {today}")
    logger.info("=" * 60)

    results = {
        "run_date":   today,
        "start_time": start_time.isoformat(),
        "steps":      {},
        "summary":    {},
    }

    # ------------------------------------------------------------------
    # STEP 1 — GEE authentication + load industrial zones
    # ------------------------------------------------------------------
    logger.info("[1/7] Loading industrial zones...")
    try:
        gee_available = authenticate_gee()
        zones_gdf     = load_industrial_zones(INDUSTRIAL_ZONES_FILE)
        results["steps"]["auth_zones"] = {
            "status":        "OK",
            "gee_available": gee_available,
            "zones_count":   len(zones_gdf),
        }
        mode = "live GEE" if gee_available else "simulation mode"
        logger.info(f"    {len(zones_gdf)} zones loaded | {mode}")
    except Exception as e:
        logger.error(f"    Failed: {e}")
        results["steps"]["auth_zones"] = {"status": "FAILED", "error": str(e)}
        return format_response(500, results)

    # ------------------------------------------------------------------
    # STEP 2 — Fetch / cache Sentinel-5P data
    # ------------------------------------------------------------------
    logger.info("[2/7] Fetching Sentinel-5P data...")
    pollution_file = Path(POLLUTION_DATA_FILE)
    try:
        if force_data_refresh or not pollution_file.exists():
            logger.info(f"    Downloading {TRAINING_START_DATE} → {END_DATE}...")
            pollution_df = fetch_all_zones_data(
                zones_gdf, TRAINING_START_DATE, END_DATE,
                gee_available=gee_available,
                output_file=POLLUTION_DATA_FILE
            )
        else:
            pollution_df = pd.read_csv(POLLUTION_DATA_FILE, parse_dates=["date"])
            logger.info(f"    Loaded from cache: {len(pollution_df)} records")

        results["steps"]["data_collection"] = {
            "status":  "OK",
            "records": len(pollution_df),
            "zones":   pollution_df["zone_id"].nunique(),
        }
    except Exception as e:
        logger.error(f"    Failed: {e}")
        results["steps"]["data_collection"] = {"status": "FAILED", "error": str(e)}
        return format_response(500, results)

    # ------------------------------------------------------------------
    # STEP 3 — Train Isolation Forest per zone
    # ------------------------------------------------------------------
    logger.info("[3/7] Training Isolation Forest models...")
    trained_zones = []
    for _, zone in zones_gdf.iterrows():
        zone_id = zone["zone_id"]
        try:
            train_isolation_forest(zone_id, pollution_df, force_retrain=force_retrain)
            trained_zones.append(zone_id)
        except Exception as e:
            logger.warning(f"    [{zone_id}] Skipped: {e}")

    logger.info(f"    {len(trained_zones)}/{len(zones_gdf)} models ready")
    results["steps"]["isolation_forest"] = {"status": "OK", "trained_zones": len(trained_zones)}

    # ------------------------------------------------------------------
    # STEP 4 — Detect anomalies for today
    # ------------------------------------------------------------------
    logger.info(f"[4/7] Detecting anomalies for {today}...")
    alerts_df = pd.DataFrame()
    try:
        alerts_df = detect_anomalies_for_all_zones(
            pollution_df, zones_gdf,
            target_date=today,
            force_retrain=False
        )
        anomaly_count  = int(alerts_df["is_anomaly"].sum())                          if not alerts_df.empty else 0
        critical_count = int((alerts_df["alert_level"] == "critical").sum())         if not alerts_df.empty else 0

        # Append to the alerts log (skip duplicate entries for the same date)
        log_path = Path(ALERTS_LOG_FILE)
        if log_path.exists():
            existing  = pd.read_csv(ALERTS_LOG_FILE)
            existing  = existing[existing["date"] != today]
            alerts_df = pd.concat([existing, alerts_df], ignore_index=True)
        alerts_df.to_csv(ALERTS_LOG_FILE, index=False)

        logger.info(f"    {anomaly_count} anomaly/ies | {critical_count} critical")
        results["steps"]["anomaly_detection"] = {
            "status":             "OK",
            "anomalies_detected": anomaly_count,
            "critical_alerts":    critical_count,
        }
    except Exception as e:
        logger.error(f"    Failed: {e}")
        results["steps"]["anomaly_detection"] = {"status": "FAILED", "error": str(e)}

    # ------------------------------------------------------------------
    # STEP 5 — Sentinel-2 fine analysis on alerted zones
    # ------------------------------------------------------------------
    logger.info("[5/7] Running Sentinel-2 analysis on alerted zones...")
    s2_results = {}
    if not alerts_df.empty:
        alerted = alerts_df[alerts_df["is_anomaly"] == True]
        for _, alert in alerted.iterrows():
            zone_id = alert["zone_id"]
            try:
                geom     = zones_gdf[zones_gdf["zone_id"] == zone_id].iloc[0].geometry
                analysis = trigger_sentinel2(zone_id, geom, today, gee_available)
                s2_results[zone_id] = analysis
                logger.info(f"    [{zone_id}] {'image OK' if analysis.get('image_available') else 'no image'}")
            except Exception as e:
                logger.warning(f"    [{zone_id}] Skipped: {e}")
                s2_results[zone_id] = {"error": str(e)}

    results["steps"]["sentinel2_analysis"] = {"status": "OK", "zones_analyzed": len(s2_results)}

    # ------------------------------------------------------------------
    # STEP 6 — LSTM training + 7-day forecasts
    # ------------------------------------------------------------------
    logger.info("[6/7] Training LSTM + generating forecasts...")
    lstm_forecasts = {}
    for _, zone in zones_gdf.iterrows():
        zone_id = zone["zone_id"]
        try:
            train_lstm(zone_id, pollution_df, force_retrain=force_retrain)
            forecast = predict_risk(zone_id, pollution_df)
            lstm_forecasts[zone_id] = forecast
            logger.info(
                f"    [{zone_id}] risk={forecast.get('risk_level','N/A')} | "
                f"high-risk days={forecast.get('high_risk_days',0)}/7"
            )
        except Exception as e:
            logger.warning(f"    [{zone_id}] Skipped: {e}")

    results["steps"]["lstm_prediction"] = {"status": "OK", "zones_predicted": len(lstm_forecasts)}

    # ------------------------------------------------------------------
    # STEP 7 — Generate AI reports for critical zones
    # ------------------------------------------------------------------
    logger.info("[7/7] Generating reports for critical zones...")
    reports_generated = 0
    if not alerts_df.empty:
        critical = alerts_df[alerts_df["alert_level"] == "critical"]
        for _, alert in critical.iterrows():
            zone_id = alert["zone_id"]
            try:
                zone_info = zones_gdf[zones_gdf["zone_id"] == zone_id].iloc[0]
                report = generate_report(
                    alert_data         = dict(alert),
                    sentinel2_analysis = s2_results.get(zone_id, {"image_available": False}),
                    lstm_forecast      = lstm_forecasts.get(zone_id, {}),
                    zone_info          = dict(zone_info)
                )
                reports_generated += 1
                logger.info(f"    [{zone_id}] Saved: {report['report_file']}")
            except Exception as e:
                logger.warning(f"    [{zone_id}] Skipped: {e}")

    results["steps"]["report_generation"] = {"status": "OK", "reports_generated": reports_generated}

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    end_time         = datetime.utcnow()
    duration_seconds = (end_time - start_time).total_seconds()

    results["summary"] = {
        "status":             "COMPLETED",
        "total_zones":        len(zones_gdf),
        "anomalies_detected": int(alerts_df["is_anomaly"].sum())                if not alerts_df.empty else 0,
        "critical_zones":     int((alerts_df["alert_level"] == "critical").sum()) if not alerts_df.empty else 0,
        "reports_generated":  reports_generated,
        "duration_seconds":   round(duration_seconds, 2),
        "end_time":           end_time.isoformat(),
    }

    logger.info(
        f"DONE in {duration_seconds:.1f}s | "
        f"zones={len(zones_gdf)} | "
        f"anomalies={results['summary']['anomalies_detected']} | "
        f"reports={reports_generated}"
    )

    return format_response(200, results)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AirWatch Tunisia — Daily pipeline")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Re-download all satellite data")
    parser.add_argument("--force-retrain", action="store_true",
                        help="Retrain all ML models from scratch")
    parser.add_argument("--date", type=str, default=None,
                        help="Target date (YYYY-MM-DD). Defaults to today.")
    args = parser.parse_args()

    result = run_daily_pipeline(
        force_data_refresh=args.force_refresh,
        force_retrain=args.force_retrain,
        target_date=args.date
    )
    sys.exit(0 if result.get("status") == 200 else 1)
