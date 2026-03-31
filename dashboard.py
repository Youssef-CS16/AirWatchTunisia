"""
AirWatch Tunisia - Dashboard Streamlit v2
Interactive map with multi-layer tiles, heatmap, and rich popups + systeme d'alertes SMS.
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta
from pathlib import Path
# test_sms removed — credentials must come from .env only 


ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from utils.helpers import setup_logging, format_concentration, get_color_for_alert_level

setup_logging("INFO")
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="AirWatch Tunisia",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_custom_css():
    st.markdown("""
    <style>
        .main-header {
            background: linear-gradient(135deg, #1a472a 0%, #2d6a4f 50%, #40916c 100%);
            padding: 20px 30px; border-radius: 12px;
            margin-bottom: 20px; color: white;
        }
        .badge-critical { background:#dc3545; color:white; padding:3px 10px;
                          border-radius:12px; font-size:0.8em; font-weight:bold; }
        .badge-moderate { background:#fd7e14; color:white; padding:3px 10px;
                          border-radius:12px; font-size:0.8em; font-weight:bold; }
        .badge-normal   { background:#28a745; color:white; padding:3px 10px;
                          border-radius:12px; font-size:0.8em; font-weight:bold; }
    </style>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Loading data (cache 1h)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def load_application_data():
    from config.settings import (
        INDUSTRIAL_ZONES_FILE, POLLUTION_DATA_FILE,
        ALERTS_LOG_FILE, END_DATE, START_DATE
    )
    from config.geeAuth import authenticate_gee, load_industrial_zones
    from routes.sentinel5pData import fetch_all_zones_data
    from routes.anomalyDetection import detect_anomalies_for_all_zones

    zones_gdf     = load_industrial_zones(INDUSTRIAL_ZONES_FILE)
    gee_available = authenticate_gee()

    pollution_file = Path(POLLUTION_DATA_FILE)
    if pollution_file.exists():
        pollution_df = pd.read_csv(pollution_file, parse_dates=["date"])
    else:
        pollution_df = fetch_all_zones_data(
            zones_gdf, START_DATE, END_DATE,
            gee_available=gee_available,
            output_file=POLLUTION_DATA_FILE
        )

    alerts_file = Path(ALERTS_LOG_FILE)
    today_str   = datetime.utcnow().strftime("%Y-%m-%d")

    if alerts_file.exists():
        alerts_df = pd.read_csv(alerts_file)
        if today_str not in alerts_df.get("date", pd.Series([])).values:
            new_alerts = detect_anomalies_for_all_zones(pollution_df, zones_gdf)
            alerts_df  = pd.concat([alerts_df, new_alerts], ignore_index=True)
            alerts_df.to_csv(alerts_file, index=False)
        current_alerts = alerts_df[alerts_df["date"] == today_str]
    else:
        current_alerts = detect_anomalies_for_all_zones(pollution_df, zones_gdf)
        current_alerts.to_csv(ALERTS_LOG_FILE, index=False)

    return zones_gdf, pollution_df, current_alerts, gee_available


# ---------------------------------------------------------------------------
# PAGE 1 : Interactive map
# ---------------------------------------------------------------------------
def render_home_page(zones_gdf, pollution_df, current_alerts):
    import folium
    from streamlit_folium import st_folium
    from config.settings import MAP_CENTER_LAT, MAP_CENTER_LON, WHO_THRESHOLDS

    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;font-size:2rem;">AirWatch Tunisia</h1>
        <p style="margin:4px 0 0;opacity:0.85;">
            Satellite industrial pollution monitoring |
            Sentinel-5P &amp; Sentinel-2 | IA
        </p>
    </div>
    """, unsafe_allow_html=True)

    # KPIs globaux
    total = len(zones_gdf)
    crit  = int((current_alerts["alert_level"] == "critical").sum()) if not current_alerts.empty else 0
    mod   = int((current_alerts["alert_level"] == "moderate").sum()) if not current_alerts.empty else 0
    norm  = total - crit - mod

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Monitored zones", total)
    c2.metric("Critical alerts", crit)
    c3.metric("Moderate alerts",  mod)
    c4.metric("Normal zones",    norm)

    st.divider()

    # ---- Carte Folium enrichie ----------------------------------------
    m = folium.Map(location=[MAP_CENTER_LAT, MAP_CENTER_LON], zoom_start=7, tiles=None)

    # Fonds de carte multiples
    folium.TileLayer("CartoDB positron",    name="Clair",    control=True).add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="Sombre",   control=True).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite", control=True,
    ).add_to(m)

    # Fusionner alertes avec zones
    if not current_alerts.empty:
        merged = zones_gdf.merge(
            current_alerts[["zone_id","alert_level","no2_ugm3","so2_ugm3",
                             "anomaly_score","is_anomaly"]],
            on="zone_id", how="left"
        )
    else:
        merged = zones_gdf.copy()
        for col in ["alert_level","no2_ugm3","so2_ugm3","anomaly_score"]:
            merged[col] = "normal" if col == "alert_level" else 0.0

    merged["alert_level"] = merged["alert_level"].fillna("normal")
    merged["centroid_lon"] = merged.geometry.centroid.x
    merged["centroid_lat"] = merged.geometry.centroid.y

    # Groupes de couches
    g_critical  = folium.FeatureGroup(name="Critical alerts",     show=True)
    g_moderate  = folium.FeatureGroup(name="Moderate alerts",      show=True)
    g_normal    = folium.FeatureGroup(name="Normal zones",        show=True)
    g_heatmap   = folium.FeatureGroup(name="Heatmap pollution",     show=False)
    g_residents = folium.FeatureGroup(name="Residents enregistres", show=False)

    no2_who = WHO_THRESHOLDS["NO2"]["daily"]
    so2_who = WHO_THRESHOLDS["SO2"]["daily"]

    for _, zone in merged.iterrows():
        level  = zone.get("alert_level", "normal") or "normal"
        color  = get_color_for_alert_level(level)
        lon    = zone["centroid_lon"]
        lat    = zone["centroid_lat"]
        no2    = float(zone.get("no2_ugm3", 0) or 0)
        so2    = float(zone.get("so2_ugm3", 0) or 0)
        score  = float(zone.get("anomaly_score", 0) or 0)
        name   = zone.get("name", zone["zone_id"])
        city   = zone.get("city", "N/A")
        itype  = zone.get("industry_type", "N/A")
        pop    = zone.get("population_nearby", "N/A")

        no2_ratio = round(no2 / no2_who, 1)
        so2_ratio = round(so2 / so2_who, 1)

        # Cercle de zone (rayon proportionnel au score)
        radius_m     = 4000 + score * 8000
        fill_opacity = 0.10 + score * 0.25
        target_group = (g_critical if level == "critical" else
                        g_moderate if level == "moderate" else g_normal)

        folium.Circle(
            location=[lat, lon], radius=radius_m,
            color=color, fill=True, fill_opacity=fill_opacity, weight=2,
            tooltip=name
        ).add_to(target_group)

        # Barres de progression
        no2_pct   = min(100, int((no2 / max(no2_who * 3, 1)) * 100))
        so2_pct   = min(100, int((so2 / max(so2_who * 3, 1)) * 100))
        no2_color = "#ff6b6b" if no2 > no2_who else "#51cf66"
        so2_color = "#ff6b6b" if so2 > so2_who else "#51cf66"
        hdr_color = ("#dc3545" if level == "critical" else
                     "#fd7e14" if level == "moderate" else "#28a745")

        popup_html = f"""
        <div style="min-width:290px;font-family:Arial,sans-serif;font-size:13px;">
          <div style="background:{hdr_color};color:white;
                      padding:8px 12px;border-radius:6px 6px 0 0;">
            <b style="font-size:14px;">{name}</b>
            <span style="float:right;font-size:11px;opacity:0.9;">{level.upper()}</span>
          </div>
          <div style="padding:12px;border:1px solid #ddd;border-top:none;
                      border-radius:0 0 6px 6px;background:white;">
            <div style="color:#666;font-size:11px;margin-bottom:8px;">
              {city} &nbsp;|&nbsp; {itype} &nbsp;|&nbsp;
              Pop. ~{f'{int(pop):,}' if isinstance(pop,(int,float)) else pop}
            </div>
            <b>NO2 :</b>
            <span style="color:{no2_color};">{no2:.1f} µg/m³</span>
            <span style="color:#999;font-size:11px;"> OMS:{no2_who} | x{no2_ratio}</span><br>
            <div style="background:#eee;border-radius:3px;height:6px;margin:3px 0 8px;">
              <div style="background:{no2_color};width:{no2_pct}%;
                          height:100%;border-radius:3px;"></div>
            </div>
            <b>SO2 :</b>
            <span style="color:{so2_color};">{so2:.1f} µg/m³</span>
            <span style="color:#999;font-size:11px;"> OMS:{so2_who} | x{so2_ratio}</span><br>
            <div style="background:#eee;border-radius:3px;height:6px;margin:3px 0 8px;">
              <div style="background:{so2_color};width:{so2_pct}%;
                          height:100%;border-radius:3px;"></div>
            </div>
            <div style="margin-top:8px;padding-top:8px;border-top:1px solid #eee;">
              <b>Score anomalie :</b> {score:.3f} / 1.0<br>
              <div style="background:#eee;border-radius:3px;height:8px;margin:3px 0;">
                <div style="background:{'#dc3545' if score>0.5 else '#fd7e14' if score>0.3 else '#28a745'};
                            width:{int(score*100)}%;height:100%;border-radius:3px;"></div>
              </div>
            </div>
            <div style="margin-top:6px;color:#555;font-size:11px;">
              GPS : {lat:.4f}N, {lon:.4f}E
            </div>
          </div>
        </div>
        """

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=folium.Tooltip(
                f"<b>{name}</b><br>NO2:{no2:.0f} SO2:{so2:.0f} µg/m³",
                sticky=True
            ),
            icon=folium.Icon(
                color=color,
                icon=("industry"             if level == "critical" else
                      "exclamation-triangle" if level == "moderate" else "check-circle"),
                prefix="fa"
            )
        ).add_to(target_group)

    # Heatmap pollution (couche optionnelle)
    try:
        from folium.plugins import HeatMap
        heat_data = []
        for _, zone in merged.iterrows():
            lat2      = zone.geometry.centroid.y
            lon2      = zone.geometry.centroid.x
            no2       = float(zone.get("no2_ugm3", 0) or 0)
            so2       = float(zone.get("so2_ugm3", 0) or 0)
            intensity = min(1.0, (no2 / 200 + so2 / 100) / 2)
            if intensity > 0:
                heat_data.append([lat2, lon2, intensity])
        if heat_data:
            HeatMap(
                heat_data, radius=60, blur=40, min_opacity=0.3,
                gradient={"0.2":"blue","0.5":"yellow","0.8":"orange","1.0":"red"}
            ).add_to(g_heatmap)
    except Exception:
        pass

    # Residents enregistres (couche optionnelle)
    try:
        from routes.smsAlerts import load_residents
        res_df = load_residents()
        if not res_df.empty:
            for _, res in res_df.head(300).iterrows():
                folium.CircleMarker(
                    location=[res["latitude"], res["longitude"]],
                    radius=4, color="#a8dadc", fill=True, fill_opacity=0.6, weight=1,
                    popup=folium.Popup(
                        f"<b>{res['name']}</b><br>Tel:{res['phone']}<br>"
                        f"GPS:{res['latitude']:.4f},{res['longitude']:.4f}",
                        max_width=200
                    ),
                    tooltip=res["resident_id"]
                ).add_to(g_residents)
    except Exception:
        pass

    for g in [g_critical, g_moderate, g_normal, g_heatmap, g_residents]:
        g.add_to(m)

    # Legende
    legend_html = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:1000;
                background:rgba(15,15,25,0.92);color:#eee;
                padding:14px 18px;border-radius:10px;
                box-shadow:0 4px 12px rgba(0,0,0,0.5);
                font-family:Arial;font-size:13px;">
      <b>Niveau d'alerte</b>
      <div style="margin-top:8px;">
        <span style="color:#dc3545;font-size:18px;">&#9679;</span> Critique
      </div>
      <div><span style="color:#fd7e14;font-size:18px;">&#9679;</span> Modere</div>
      <div><span style="color:#28a745;font-size:18px;">&#9679;</span> Normal</div>
      <hr style="border-color:#444;margin:8px 0;">
      <div style="font-size:11px;color:#555;">
        Rayon = intensite anomalie<br>
        Couches via bouton haut-droite
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    try:
        from folium.plugins import MiniMap
        MiniMap(toggle_display=True, position="bottomright").add_to(m)
    except Exception:
        pass

    st_folium(m, width=None, height=580, returned_objects=[])

    # Tableau recapitulatif
    st.subheader("Zone summary")
    if not current_alerts.empty:
        display = current_alerts[
            ["zone_name","alert_level","no2_ugm3","so2_ugm3","anomaly_score"]
        ].copy()
        display.columns = ["Zone","Niveau","NO2 (µg/m³)","SO2 (µg/m³)","Score"]
        display["NO2 (µg/m³)"] = display["NO2 (µg/m³)"].round(1)
        display["SO2 (µg/m³)"] = display["SO2 (µg/m³)"].round(1)
        display["Score"]       = display["Score"].round(3)
        st.dataframe(display, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Helper : Affichage de la grille pixels S5P + resultats S2
# ---------------------------------------------------------------------------
def _render_pixel_map(result: dict, zone_info):
    """
    Affiche la grille de pixels S5P sur une carte Folium avec :
    - Rectangles codes par couleur (vert / orange / rouge)
    - Popup avec valeurs NO2/SO2 par pixel
    - Marqueurs S2 sur les pixels rouges analyses
    """
    import folium
    from streamlit_folium import st_folium

    pixels     = result.get("pixels", [])
    s2_results = result.get("s2_results", [])
    counts     = result.get("level_counts", {})

    if not pixels:
        st.warning("Aucun pixel disponible.")
        return

    # KPIs grille
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total pixels",   result.get("total_pixels", 0))
    k2.metric("Pixels verts",   counts.get("green",  0))
    k3.metric("Pixels oranges", counts.get("orange", 0))
    k4.metric("Pixels rouges",  counts.get("red",    0),
              help="Pixels ayant declenche une analyse Sentinel-2")
    k5.metric("Analyses S2",    result.get("s2_triggered_count", 0))

    st.caption(
        f"Taille pixel : {result.get('pixel_size_km','N/A')} | "
        f"NO2 max : {result.get('no2_max',0):.1f} µg/m³ | "
        f"SO2 max : {result.get('so2_max',0):.1f} µg/m³"
    )

    # Centre de la carte sur la zone
    center_lat = zone_info.geometry.centroid.y
    center_lon = zone_info.geometry.centroid.x

    m = folium.Map(location=[center_lat, center_lon], zoom_start=10,
                   tiles="CartoDB positron")

    # Couches
    g_green  = folium.FeatureGroup(name="Pixels normaux (vert)",  show=True)
    g_orange = folium.FeatureGroup(name="Pixels moderes (orange)", show=True)
    g_red    = folium.FeatureGroup(name="Pixels critiques (rouge)", show=True)
    g_s2     = folium.FeatureGroup(name="Analyses Sentinel-2",     show=True)

    color_map = {"green": "#28a745", "orange": "#fd7e14", "red": "#dc3545"}
    fill_map  = {"green": 0.25,      "orange": 0.40,      "red": 0.60}
    group_map = {"green": g_green,   "orange": g_orange,  "red": g_red}

    for px in pixels:
        level  = px["level"]
        color  = color_map.get(level, "#aaa")
        no2    = px["no2_ugm3"]
        so2    = px["so2_ugm3"]

        popup_html = f"""
        <div style="font-family:Arial;font-size:12px;min-width:200px;">
          <b>Pixel {px['pixel_id']}</b><br>
          <span style="color:{color};font-weight:bold;">{level.upper()}</span><br>
          <hr style="margin:4px 0;">
          <b>NO2 :</b> {no2:.1f} µg/m³<br>
          <b>SO2 :</b> {so2:.1f} µg/m³<br>
          <b>Centre :</b> {px['center_lat']:.4f}N, {px['center_lon']:.4f}E<br>
          {'<b style="color:#dc3545;">Analyse S2 declenchee</b>' if px.get('s2_triggered') else ''}
        </div>
        """

        folium.Rectangle(
            bounds=[[px["lat_min"], px["lon_min"]],
                    [px["lat_max"], px["lon_max"]]],
            color=color,
            fill=True,
            fill_opacity=fill_map.get(level, 0.3),
            weight=1.5,
            popup=folium.Popup(popup_html, max_width=240),
            tooltip=f"{level.upper()} | NO2:{no2:.0f} SO2:{so2:.0f} µg/m³"
        ).add_to(group_map.get(level, g_green))

    # Marqueurs S2 sur les pixels rouges analyses
    for s2 in s2_results:
        slat = s2.get("center_lat", center_lat)
        slon = s2.get("center_lon", center_lon)
        img_ok = s2.get("image_available", False)

        s2_popup = f"""
        <div style="font-family:Arial;font-size:12px;min-width:220px;">
          <b style="color:#dc3545;">Analyse Sentinel-2</b><br>
          Pixel : {s2.get('pixel_id','N/A')}<br>
          Image : {'Disponible' if img_ok else 'Indisponible'}<br>
          {'<b>NDVI :</b> ' + str(round(s2.get('ndvi_current',0),3)) + '<br>' if img_ok else ''}
          {'<b>Pop. exposee :</b> ' + str(s2.get('population_exposed_1km','N/A')) + ' hab.<br>' if img_ok else ''}
          {'<b>Distance hab. :</b> ' + str(s2.get('min_distance_to_residential_m','N/A')) + ' m' if img_ok else s2.get('reason','')}
        </div>
        """

        folium.Marker(
            location=[slat, slon],
            popup=folium.Popup(s2_popup, max_width=260),
            tooltip=f"S2 Pixel {s2.get('pixel_id','')}",
            icon=folium.Icon(
                color="red" if img_ok else "gray",
                icon="satellite" if img_ok else "question-circle",
                prefix="fa"
            )
        ).add_to(g_s2)

    # Contour de la zone industrielle
    try:
        import json
        folium.GeoJson(
            data=zone_info.geometry.__geo_interface__,
            style_function=lambda _: {
                "color": "#40916c", "weight": 2,
                "fillOpacity": 0.05, "dashArray": "5,5"
            },
            tooltip="Perimetre zone industrielle"
        ).add_to(m)
    except Exception:
        pass

    for g in [g_green, g_orange, g_red, g_s2]:
        g.add_to(m)

    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    # Legende
    legend = """
    <div style="position:fixed;bottom:20px;left:20px;z-index:1000;
                background:rgba(15,15,25,0.9);color:#eee;
                padding:12px 16px;border-radius:8px;font-family:Arial;font-size:12px;">
      <b>Pixels Sentinel-5P</b><br>
      <span style="color:#28a745;">&#9632;</span> Normal (sous OMS)<br>
      <span style="color:#fd7e14;">&#9632;</span> Modere (seuil OMS)<br>
      <span style="color:#dc3545;">&#9632;</span> Critique → S2 declenche<br>
      <span style="color:#dc3545;">&#9679;</span> Resultat Sentinel-2
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend))
    st_folium(m, width=None, height=500, returned_objects=[])

    # Detail des pixels rouges + resultats S2
    if s2_results:
        st.subheader(f"{len(s2_results)} pixel(s) rouge(s) — Resultats Sentinel-2")
        for s2 in s2_results:
            img_ok  = s2.get("image_available", False)
            border  = "#28a745" if img_ok else "#888"
            ndvi_c  = s2.get("ndvi_current")
            ndvi_ch = s2.get("ndvi_change")
            pop     = s2.get("population_exposed_1km", "N/A")
            dist    = s2.get("min_distance_to_residential_m", "N/A")

            st.markdown(f"""
            <div style="background:#f5f5f5;border-radius:8px;padding:14px;
                        margin:6px 0;border-left:4px solid {border};">
              <b>Pixel {s2.get('pixel_id','N/A')}</b>
              &nbsp;|&nbsp; NO2:{s2.get('no2_ugm3',0):.1f} µg/m³
              &nbsp;|&nbsp; SO2:{s2.get('so2_ugm3',0):.1f} µg/m³<br>
              <span style="color:{border};">Image S2 : {'Disponible' if img_ok else 'Indisponible'}</span>
              {'<br>NDVI actuel : <b>' + str(round(ndvi_c,3)) + '</b>' if ndvi_c else ''}
              {'&nbsp;| Evolution : <b>' + f'{ndvi_ch:+.3f}' + '</b>' if ndvi_ch else ''}
              {'<br>Population exposee (1km) : <b>' + (f'{pop:,}' if isinstance(pop,int) else str(pop)) + ' hab.</b>' if img_ok else ''}
              {'<br>Distance habitations : <b>' + str(dist) + ' m</b>' if img_ok else ''}
              {'<br><span style="color:#999;">' + str(s2.get('reason','')) + '</span>' if not img_ok else ''}
            </div>
            """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# PAGE 2 : Zone detail
# ---------------------------------------------------------------------------
def render_zone_detail_page(zones_gdf, pollution_df, current_alerts):
    import plotly.graph_objects as go
    from config.settings import WHO_THRESHOLDS

    st.header("Zone detail industrielle")

    zone_options  = dict(zip(zones_gdf["name"], zones_gdf["zone_id"]))
    selected_name = st.selectbox("Selectionner une zone :", list(zone_options.keys()))
    selected_id   = zone_options[selected_name]

    zone_data = pollution_df[pollution_df["zone_id"] == selected_id].copy()
    zone_data["date"] = pd.to_datetime(zone_data["date"])
    last_30   = zone_data.sort_values("date").tail(30)
    zone_info = zones_gdf[zones_gdf["zone_id"] == selected_id].iloc[0]

    alert_info = None
    if not current_alerts.empty and selected_id in current_alerts["zone_id"].values:
        alert_info = current_alerts[current_alerts["zone_id"] == selected_id].iloc[0]

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.subheader(selected_name)
        st.caption(
            f"Ville : {zone_info.get('city','N/A')} | "
            f"Type : {zone_info.get('industry_type','N/A')} | "
            f"Pop. exposee : ~{zone_info.get('population_nearby',0):,}"
        )
    if alert_info is not None:
        with col2:
            st.metric("NO2", f"{alert_info['no2_ugm3']:.1f} µg/m³",
                      f"OMS: {WHO_THRESHOLDS['NO2']['daily']}", delta_color="off")
        with col3:
            st.metric("SO2", f"{alert_info['so2_ugm3']:.1f} µg/m³",
                      f"OMS: {WHO_THRESHOLDS['SO2']['daily']}", delta_color="off")

    st.divider()

    # Graphique temporel
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=last_30["date"], y=last_30["no2_ugm3"],
                             mode="lines+markers", name="NO2 (µg/m³)",
                             line=dict(color="#e63946", width=2)))
    fig.add_trace(go.Scatter(x=last_30["date"], y=last_30["so2_ugm3"],
                             mode="lines+markers", name="SO2 (µg/m³)",
                             line=dict(color="#457b9d", width=2)))
    fig.add_hline(y=WHO_THRESHOLDS["NO2"]["daily"], line_dash="dash",
                  line_color="#e63946", annotation_text="Seuil NO2 OMS")
    fig.add_hline(y=WHO_THRESHOLDS["SO2"]["daily"], line_dash="dash",
                  line_color="#457b9d", annotation_text="Seuil SO2 OMS")
    fig.update_layout(
        title=f"30 derniers jours - {selected_name}",
        xaxis_title="Date", yaxis_title="Concentration (µg/m³)",
        hovermode="x unified", plot_bgcolor="white", height=380,
        legend=dict(orientation="h", y=-0.2)
    )
    fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
    st.plotly_chart(fig, use_container_width=True)

    # ----------------------------------------------------------------
    # GRILLE PIXELS S5P -> TRIGGER S2 SUR PIXELS ROUGES
    # ----------------------------------------------------------------
    st.divider()
    st.subheader("Grille pixels Sentinel-5P")
    st.caption(
        "Chaque zone est divisee en pixels de la taille reelle de Sentinel-5P "
        "(~3.5 x 5.5 km). Les pixels **rouges** declenchent automatiquement "
        "une analyse Sentinel-2 a 10m de resolution sur ce pixel precis."
    )

    today   = datetime.utcnow().strftime("%Y-%m-%d")
    no2_now = float(alert_info["no2_ugm3"]) if alert_info is not None else 30.0
    so2_now = float(alert_info["so2_ugm3"]) if alert_info is not None else 20.0

    if st.button(
        "Analyser les pixels S5P et declencher S2 sur zones rouges",
        type="primary", key=f"pixels_{selected_id}"
    ):
        with st.spinner("Construction grille + analyse Sentinel-2 sur pixels rouges..."):
            from routes.pixelEngine import analyze_zone_pixels
            result = analyze_zone_pixels(
                zone_id=selected_id,
                zone_geometry=zone_info.geometry,
                zone_no2=no2_now, zone_so2=so2_now,
                alert_date=today, gee_available=False
            )
            st.session_state[f"pixel_result_{selected_id}"] = result

    if f"pixel_result_{selected_id}" in st.session_state:
        _render_pixel_map(st.session_state[f"pixel_result_{selected_id}"], zone_info)

    st.divider()

    # ---- Previsions LSTM + Rapport IA -----------------------------
    ca, cb = st.columns(2)

    with ca:
        st.subheader("Prevision 7 jours (LSTM)")
        if st.button("Generer previsions", key=f"lstm_{selected_id}"):
            with st.spinner("Calcul..."):
                from routes.lstmPrediction import predict_risk
                forecast = predict_risk(selected_id, pollution_df)
                risk  = forecast.get("risk_level","N/A")
                color = {"HIGH":"red","MODERATE":"orange","LOW":"green"}.get(risk,"gray")
                st.markdown(f"**Risque global : :{color}[{risk}]**")
                st.write(f"Jours a risque : **{forecast.get('high_risk_days',0)}/7**")
                if forecast.get("predictions"):
                    pf = pd.DataFrame(forecast["predictions"])
                    st.dataframe(
                        pf[["date","predicted_no2_ugm3","predicted_so2_ugm3"]]
                        .rename(columns={"date":"Date",
                                         "predicted_no2_ugm3":"NO2 (µg/m³)",
                                         "predicted_so2_ugm3":"SO2 (µg/m³)"}),
                        hide_index=True, use_container_width=True
                    )

    with cb:
        st.subheader("Rapport IA")
        if alert_info is not None and st.button("Generer rapport",
                                                 key=f"rep_{selected_id}"):
            with st.spinner("Generation..."):
                from routes.reportGenerator import generate_report
                from routes.sentinel2Analysis import trigger_sentinel2
                from routes.lstmPrediction import predict_risk
                s2_res   = trigger_sentinel2(selected_id, zone_info.geometry, today, False)
                forecast = predict_risk(selected_id, pollution_df)
                report   = generate_report(dict(alert_info), s2_res, forecast, dict(zone_info))
                st.text_area("Rapport", report["report_text"], height=320)
                st.download_button("Telecharger", report["report_text"],
                                   f"rapport_{selected_id}_{today}.txt", "text/plain")


# ---------------------------------------------------------------------------
# PAGE 3 : Active alerts
# ---------------------------------------------------------------------------
def render_alerts_page(current_alerts):
    st.header("Active alerts")
    if current_alerts.empty:
        st.info("Aucune alerte disponible.")
        return

    lf = st.multiselect("Filtrer :", ["critical","moderate","normal"],
                        default=["critical","moderate"])
    df = current_alerts[current_alerts["alert_level"].isin(lf)] if lf else current_alerts

    for _, row in df.iterrows():
        level  = row.get("alert_level","normal")
        border = "#dc3545" if level=="critical" else "#fd7e14" if level=="moderate" else "#28a745"
        st.markdown(f"""
        <div style="background:#f5f5f5;border-radius:8px;padding:12px 16px;
                    margin:6px 0;border-left:4px solid {border};">
            <span class="badge-{level}">{level.upper()}</span>
            &nbsp; <b>{row.get('zone_name', row.get('zone_id',''))}</b>
            &nbsp;|&nbsp; {row.get('date','N/A')}
            &nbsp;|&nbsp; NO2 : <b>{row.get('no2_ugm3',0):.1f}</b> µg/m³
            &nbsp;|&nbsp; SO2 : <b>{row.get('so2_ugm3',0):.1f}</b> µg/m³
            &nbsp;|&nbsp; Score : <b>{row.get('anomaly_score',0):.3f}</b>
        </div>
        """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# PAGE 4 : Systeme d'alertes SMS
# ---------------------------------------------------------------------------
def render_sms_page(zones_gdf, current_alerts):
    from routes.smsAlerts import (
        load_residents, get_residents_in_radius,
        send_zone_alert, load_sms_history,
        register_resident, ALERT_RADIUS_KM
    )
    import plotly.express as px

    st.header("Systeme d'alertes SMS")
    st.caption(
        "Envoie automatiquement des SMS aux habitants situes dans le "
        "rayon d'alerte d'une zone industrielle, bases sur leur position GPS."
    )

    tab1, tab2, tab3, tab4 = st.tabs([
        "Envoyer alertes",
        "Residents enregistres",
        "S'enregistrer",
        "Historique campagnes",
    ])

    # ================================================================
    # TAB 1 : Lancer une campagne
    # ================================================================
    with tab1:
        st.subheader("Lancer une campagne d'alerte SMS")
        col_l, col_r = st.columns(2)

        with col_l:
            zone_options  = dict(zip(zones_gdf["name"], zones_gdf["zone_id"]))
            selected_name = st.selectbox("Zone industrielle :",
                                         list(zone_options.keys()), key="sms_zone")
            selected_id   = zone_options[selected_name]

            alert_info = None
            if not current_alerts.empty and selected_id in current_alerts["zone_id"].values:
                alert_info = current_alerts[current_alerts["zone_id"] == selected_id].iloc[0]

            if alert_info is not None:
                level = alert_info["alert_level"]
                no2   = float(alert_info["no2_ugm3"])
                so2   = float(alert_info["so2_ugm3"])
                hdr   = ("#dc3545" if level=="critical" else
                         "#fd7e14" if level=="moderate" else "#28a745")
                st.markdown(f"""
                <div style="background:#f5f5f5;border-radius:8px;padding:14px;
                            border-left:4px solid {hdr};">
                    <b>Niveau d'alerte actuel :</b>
                    <span style="color:{hdr};font-weight:bold;">{level.upper()}</span><br>
                    <b>NO2 :</b> {no2:.1f} µg/m³ &nbsp;|&nbsp;
                    <b>SO2 :</b> {so2:.1f} µg/m³
                </div>
                """, unsafe_allow_html=True)
            else:
                level = st.selectbox("Niveau manuel :", ["critical","moderate"])
                no2   = st.number_input("NO2 (µg/m³)", value=80.0,  min_value=0.0)
                so2   = st.number_input("SO2 (µg/m³)", value=120.0, min_value=0.0)

            default_r = ALERT_RADIUS_KM.get(level, 5.0)
            radius_km = st.slider(
                "Rayon d'alerte (km)", 1.0, 20.0, default_r, 0.5,
                help="Les residents dans ce rayon GPS recevront un SMS"
            )
            simulate = st.checkbox("Mode simulation (sans vrais SMS)", value=True)

        with col_r:
            zone_row   = zones_gdf[zones_gdf["zone_id"] == selected_id].iloc[0]
            center_lat = zone_row.geometry.centroid.y
            center_lon = zone_row.geometry.centroid.x
            res_df     = load_residents()
            targets    = get_residents_in_radius(center_lat, center_lon, radius_km, res_df)

            st.markdown(f"""
            <div style="background:#f5f5f5;border-radius:8px;padding:14px;">
                <b>Apercu campagne</b><br><br>
                Zone : <b>{selected_name}</b><br>
                Centre GPS : {center_lat:.4f}N, {center_lon:.4f}E<br>
                Rayon : <b>{radius_km} km</b><br>
                Residents cibles :
                <b style="color:#e67e22;font-size:1.3em;">{len(targets)}</b><br>
                Mode : <b>{'Simulation' if simulate else 'REEL - Twilio'}</b>
            </div>
            """, unsafe_allow_html=True)

            if not targets.empty:
                prev = targets[["resident_id","name","phone","distance_km"]].head(10).copy()
                prev["distance_km"] = prev["distance_km"].round(2)
                st.dataframe(prev, hide_index=True, use_container_width=True)
                if len(targets) > 10:
                    st.caption(f"... et {len(targets)-10} autres.")
            else:
                st.info("Aucun resident dans ce rayon.")

        st.divider()

        # Apercu du message SMS
        if level in ("critical","moderate"):
            from config.settings import WHO_THRESHOLDS
            n_r = round(no2 / WHO_THRESHOLDS["NO2"]["daily"], 1)
            s_r = round(so2 / WHO_THRESHOLDS["SO2"]["daily"], 1)
            preview = (
                f"{'ALERTE CRITIQUE' if level=='critical' else 'ALERTE'} - AirWatch Tunisia\n"
                f"Zone: {selected_name}\n"
                f"NO2: {no2:.0f} ug/m3 (x{n_r} OMS) | SO2: {so2:.0f} ug/m3 (x{s_r} OMS)\n"
                f"{'Restez a l interieur, fenetres fermees.' if level=='critical' else 'Limitez les activites dehors.'}\n"
                f"Info: airwatch-tn.gov.tn"
            )
            st.markdown("**Apercu du message SMS :**")
            st.code(preview, language=None)

        if level == "normal":
            st.info("Aucune alerte SMS requise pour le niveau normal.")
        elif len(targets) == 0:
            st.warning("Aucun resident cible. Enregistrez des residents d'abord.")
        else:
            if not simulate:
                st.warning("Mode REEL : de vrais SMS seront envoyes via Twilio.")
            label = (f"Envoyer {len(targets)} SMS (simulation)"
                     if simulate else f"ENVOYER {len(targets)} SMS REELS")
            if st.button(label, type="secondary" if simulate else "primary",
                         use_container_width=True):
                with st.spinner(f"Envoi de {len(targets)} SMS..."):
                    result = send_zone_alert(
                        zone_id=selected_id, zone_name=selected_name,
                        center_lat=center_lat, center_lon=center_lon,
                        alert_level=level, no2=no2, so2=so2,
                        residents_df=res_df, simulate=simulate, max_recipients=500
                    )
                camp   = result.get("campaign", {})
                sent   = camp.get("sms_sent", 0)
                failed = camp.get("sms_failed", 0)
                if sent > 0:
                    st.success(
                        f"{sent} SMS {'simules' if simulate else 'envoyes'} ! "
                        f"{failed} echec(s)."
                    )
                else:
                    st.error("Echec de l'envoi.")
                if result.get("details"):
                    det  = pd.DataFrame(result["details"])
                    show = [c for c in ["resident_id","to","status","distance_km","simulated"]
                            if c in det.columns]
                    st.dataframe(det[show].head(20), hide_index=True, use_container_width=True)

    # ================================================================
    # TAB 2 : Carte des residents
    # ================================================================
    with tab2:
        st.subheader("Residents enregistres sur la plateforme")
        res_df = load_residents()

        if res_df.empty:
            st.info("Aucun resident enregistre.")
        else:
            st.metric("Total residents", len(res_df))

            import folium
            from streamlit_folium import st_folium
            from config.settings import MAP_CENTER_LAT, MAP_CENTER_LON

            m2 = folium.Map(location=[MAP_CENTER_LAT, MAP_CENTER_LON],
                            zoom_start=7, tiles="CartoDB positron")

            # Zones industrielles
            for _, zone in zones_gdf.iterrows():
                lat2 = zone.geometry.centroid.y
                lon2 = zone.geometry.centroid.x
                folium.Circle([lat2, lon2], radius=5000, color="#40916c",
                              fill=True, fill_opacity=0.1, weight=2,
                              tooltip=zone.get("name","")).add_to(m2)
                folium.Marker([lat2, lon2],
                              icon=folium.Icon(color="green", icon="industry", prefix="fa"),
                              tooltip=zone.get("name","")).add_to(m2)

            # Points residents
            for _, res in res_df.iterrows():
                folium.CircleMarker(
                    location=[res["latitude"], res["longitude"]],
                    radius=5, color="#4dabf7", fill=True, fill_opacity=0.7, weight=1,
                    popup=folium.Popup(
                        f"<b>{res['name']}</b><br>Tel:{res['phone']}<br>"
                        f"GPS:{res['latitude']:.4f},{res['longitude']:.4f}",
                        max_width=200
                    ),
                    tooltip=res["resident_id"]
                ).add_to(m2)

            st_folium(m2, width=None, height=450, returned_objects=[])
            st.dataframe(
                res_df[["resident_id","name","phone","latitude","longitude"]]
                .rename(columns={"resident_id":"ID","name":"Nom","phone":"Tel",
                                  "latitude":"Lat","longitude":"Lon"}),
                hide_index=True, use_container_width=True
            )

    # ================================================================
    # TAB 3 : Formulaire d'inscription
    # ================================================================
    with tab3:
        st.subheader("S'inscrire pour recevoir les alertes SMS")
        st.info(
            "Entrez votre nom, numero de telephone et position GPS "
            "pour recevoir automatiquement des SMS en cas de pollution pres de chez vous."
        )

        with st.form("reg_form"):
            reg_name  = st.text_input("Nom complet", placeholder="Ahmed Ben Ali")
            reg_phone = st.text_input(
                "Telephone", placeholder="+21698123456",
                help="Format international requis : +216..."
            )
            st.markdown("**Votre position GPS**")
            cc1, cc2 = st.columns(2)
            with cc1:
                reg_lat = st.number_input("Latitude",  value=33.88,
                                          min_value=30.0, max_value=38.0, format="%.6f")
            with cc2:
                reg_lon = st.number_input("Longitude", value=10.10,
                                          min_value=7.5,  max_value=12.0, format="%.6f")
            st.caption(
                "Astuce : ouvrez Google Maps, maintenez un appui long sur "
                "votre position pour copier les coordonnees GPS."
            )

            if st.form_submit_button("S'inscrire", type="primary", use_container_width=True):
                if not reg_name.strip():
                    st.error("Le nom est requis.")
                else:
                    res = register_resident(reg_name, reg_phone, reg_lat, reg_lon)
                    if res["success"]:
                        st.success(
                            f"{res['message']} Vous recevrez des alertes "
                            f"SMS en cas de pollution pres de "
                            f"({reg_lat:.4f}, {reg_lon:.4f})."
                        )
                        st.cache_data.clear()
                    else:
                        st.error(res["error"])

    # ================================================================
    # TAB 4 : Historique campagnes
    # ================================================================
    with tab4:
        st.subheader("Historique des campagnes SMS")
        history = load_sms_history()

        if history.empty:
            st.info("Aucune campagne lancee pour l'instant.")
        else:
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Campagnes totales",  len(history))
            h2.metric("SMS envoyes",        int(history["sms_sent"].sum()))
            h3.metric("Zones alertees",     history["zone_id"].nunique())
            h4.metric("Critical alerts",  int((history["alert_level"]=="critical").sum()))

            if len(history) > 1:
                fig_h = px.bar(
                    history, x="timestamp", y="sms_sent", color="alert_level",
                    color_discrete_map={"critical":"#dc3545","moderate":"#fd7e14"},
                    title="Historique SMS par campagne",
                    labels={"sms_sent":"SMS envoyes","timestamp":"Date"}
                )
                st.plotly_chart(fig_h, use_container_width=True)

            cols = [c for c in ["timestamp","zone_name","alert_level","sms_sent",
                                  "sms_failed","radius_km","simulated"]
                    if c in history.columns]
            st.dataframe(
                history[cols].sort_values("timestamp", ascending=False),
                hide_index=True, use_container_width=True
            )


# ---------------------------------------------------------------------------
# Point d'entree principal
# ---------------------------------------------------------------------------
def main():
    inject_custom_css()

    with st.sidebar:
        st.markdown("""
        <div style="text-align:center;padding:10px 0;">
            <h2 style="color:#40916c;margin:0;">AirWatch</h2>
            <p style="color:#666;margin:2px 0;font-size:0.85em;">Tunisia | EcoWave 2.0</p>
        </div>
        """, unsafe_allow_html=True)
        st.divider()

        page = st.radio(
            "Navigation",
            ["Carte interactive", "Zone detail",
             "Active alerts", "SMS alerts"],
            label_visibility="collapsed"
        )
        st.divider()

        if st.button("Refresh data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown("""
        <div style="position:fixed;bottom:20px;left:10px;right:10px;
                    text-align:center;color:#666;font-size:0.75em;">
            Donnees : ESA Copernicus<br>
            Modeles : Isolation Forest + LSTM<br>
            <b>EcoWave 2.0 Hackathon</b>
        </div>
        """, unsafe_allow_html=True)

    with st.spinner("Loading data..."):
        try:
            zones_gdf, pollution_df, current_alerts, gee_available = load_application_data()
        except Exception as e:
            st.error(f"Loading error : {e}")
            logger.error(f"Loading error dashboard : {e}")
            return

    if not gee_available:
        st.sidebar.warning("Simulation mode (GEE unavailable)")

    if   page == "Carte interactive": render_home_page(zones_gdf, pollution_df, current_alerts)
    elif page == "Zone detail":   render_zone_detail_page(zones_gdf, pollution_df, current_alerts)
    elif page == "Active alerts":   render_alerts_page(current_alerts)
    elif page == "SMS alerts":       render_sms_page(zones_gdf, current_alerts)


if __name__ == "__main__":
    main()

