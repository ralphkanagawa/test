"""
Streamlit • Potential Work Orders Tool
- Carga única de 2 CSV
- Mapa arriba (ajustado a los puntos) + Tabla editable justo debajo
- Funciones: bulk‑add, autocompletar fechas/horas, descarga Excel
"""

from __future__ import annotations
import io, os
from datetime import datetime, timedelta, date
from typing import Dict, List

import pandas as pd
import streamlit as st
import configparser
import folium
from streamlit_folium import st_folium

# ─────────────────────────── Config helpers ─────────────────────────────

def _safe_get(cfg, sect, opt, default=""):
    try:
        return cfg.get(sect, opt)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default

def load_excel_template_columns(path: str) -> List[str]:
    if os.path.exists(path):
        try:
            return pd.read_excel(path, engine="openpyxl").columns.tolist()
        except Exception:
            pass
    return []

def load_config(path: str = "config.ini") -> tuple[
    List[str], Dict[str, List[str]], List[str], str, Dict[str, List[str]], str, str
]:
    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    cfg.read(path)

    prot = [c.strip() for c in _safe_get(cfg, "PROTECTED_COLUMNS", "columns").split(",") if c]

    dd_vals: Dict[str, List[str]] = {}
    if cfg.has_section("DROPDOWN_VALUES"):
        for k in cfg["DROPDOWN_VALUES"]:
            dd_vals[k] = [x.strip() for x in cfg.get("DROPDOWN_VALUES", k).split(",")]

    pc_map: Dict[str, List[str]] = {}
    if cfg.has_section("PARENT_CHILD_RELATIONS"):
        for p in cfg["PARENT_CHILD_RELATIONS"]:
            pc_map[p] = [x.strip() for x in cfg.get("PARENT_CHILD_RELATIONS", p).split(",")]

    return (
        prot,
        dd_vals,
        [c.strip() for c in _safe_get(cfg, "REQUIRED_COLUMNS", "columns").split(",") if c],
        _safe_get(cfg, "GENERAL", "base_save_path", "output"),
        pc_map,
        _safe_get(cfg, "GENERAL", "excel_autoload_path", ""),
        _safe_get(cfg, "GENERAL", "excel_template_path", "test.xlsx"),
    )

# ────────────────────────── Init & session ──────────────────────────────
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame()
(
    PROTECTED_COLUMNS,
    DROPDOWN_VALUES,
    REQUIRED_COLUMNS,
    BASE_SAVE_PATH,
    PARENT_CHILD_MAP,
    EXCEL_AUTOLOAD,
    EXCEL_TEMPLATE_PATH,
) = load_config()

st.set_page_config(page_title="Work Orders Tool", layout="wide")
st.title("Potential Work Orders Management (Streamlit)")

# ─────────────── 1) Carga CSV ───────────────
col_geo, col_cov = st.columns(2)
with col_geo:
    geo_file = st.file_uploader("📍 Georadar CSV", type="csv")
with col_cov:
    cov_file = st.file_uploader("📶 Coverage CSV", type="csv")

# ─────────────── 2) Procesamiento una única vez ───────────────
if geo_file and cov_file and "processed" not in st.session_state:
    # Georadar
    geo_raw = pd.read_csv(geo_file)
    if not {"Latitud", "Longitud"}.issubset(geo_raw.columns):
        st.error("Georadar debe tener columnas Latitud y Longitud")
        st.stop()

    st.session_state.geo_df = geo_raw.copy()
    gdf = geo_raw.rename(
        columns={"Latitud": "Latitude - Functional Location", "Longitud": "Longitude - Functional Location"}
    )
    gdf["Service Account - Work Order"] = "ANER_Senegal"
    gdf["Billing Account - Work Order"] = "ANER_Senegal"
    gdf["Work Order Type - Work Order"] = "Installation"
    st.session_state.df = gdf

    # Cobertura
    cov_raw = pd.read_csv(cov_file)
    if not {"Latitud", "Longitud", "RSSI / RSCP (dBm)"}.issubset(cov_raw.columns):
        st.error("Coverage debe tener Latitud, Longitud, RSSI / RSCP (dBm)")
        st.stop()

    st.session_state.cov_df = cov_raw.copy()

    # Añadir dBm & Gateway
    gdf["LatBin"] = gdf["Latitude - Functional Location"].round(10)
    gdf["LonBin"] = gdf["Longitude - Functional Location"].round(10)
    cov_raw["LatBin"] = cov_raw["Latitud"].round(10)
    cov_raw["LonBin"] = cov_raw["Longitud"].round(10)
    cov_map = cov_raw.set_index(["LatBin", "LonBin"])["RSSI / RSCP (dBm)"].to_dict()
    gdf["dBm"] = gdf.apply(lambda r: cov_map.get((r.LatBin, r.LonBin)), axis=1)

    def classify(v):
        if pd.isna(v):
            return None
        if -70 <= v <= -10:
            return "YES"
        if -200 <= v < -70:
            return "NO"
        return None

    gdf["Gateway"] = gdf["dBm"].apply(classify)
    gdf.drop(columns=["LatBin", "LonBin"], inplace=True)

    st.session_state.processed = True
    st.success("✔ Datos procesados")

if "processed" not in st.session_state:
    st.info("⬆️ Sube ambos CSV para continuar")
    st.stop()

# ─────────────── 3) Mapa ───────────────
geo = st.session_state.geo_df
cov = st.session_state.cov_df

st.subheader("🗺️ Mapa Georadar & Cobertura")

# Calcular bounds globales para auto‑zoom
min_lat = min(geo.Latitud.min(), cov.Latitud.min())
max_lat = max(geo.Latitud.max(), cov.Latitud.max())
min_lon = min(geo.Longitud.min(), cov.Longitud.min())
max_lon = max(geo.Longitud.max(), cov.Longitud.max())

fmap = folium.Map()
fmap.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

# Cobertura agrupada en círculos coloreados (sin marcador azul extra)
cov = cov.copy()
cov["LatBin"] = cov["Latitud"].round(10)
cov["LonBin"] = cov["Longitud"].round(10)
agg = cov.groupby(["LatBin", "LonBin"]).agg(
    Latitud=("Latitud", "mean"),
    Longitud=("Longitud", "mean"),
    RSSI=("RSSI / RSCP (dBm)", "mean"),
).reset_index(drop=True)

def color_rssi(v):
    if v >= -70:
        return "green"
    if v >= -80:
        return "orange"
    return "red"

for _, r in agg.iterrows():
    folium.CircleMarker(
        location=[r.Latitud, r.Longitud],
        radius=6,
        color=color_rssi(r.RSSI),
        fill=True,
        fill_opacity=0.7,
        popup=f"RSSI: {r.RSSI:.1f} dBm",
    ).add_to(fmap)

st_folium(fmap, width=1050, height=500)
# reducir hueco
st.markdown("<div style='margin-top:-15px'></div>", unsafe_allow_html=True)

# ─────────────── 4) Tabla editable + utilidades ───────────────
st.subheader("📑 Tabla editable")

_template_cols = load_excel_template_columns(EXCEL_TEMPLATE_PATH)
disp = st.session_state.df.copy()
for c in _template_cols:
    if c not in disp.columns:
        disp[c] = ""

disp = disp[_template_cols]
if "edited_df" not in st.session_state:
    st.session_state.edited_df = disp.copy()

edited = st.data_editor(st.session_state.edited_df, num_rows="dynamic", use_container_width=True, key="editor")
if st.button("💾 Guardar cambios"):
    st.session_state.edited_df
