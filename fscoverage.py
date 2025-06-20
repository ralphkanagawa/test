"""
Streamlit version of the Potential Work Orders tool
(con mapa y tabla generados con **un solo** upload de CSV).
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, date, time
from typing import Dict, List

import pandas as pd
import streamlit as st
import configparser
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _safe_get(cfg: configparser.ConfigParser, sect: str, opt: str, default: str = "") -> str:
    try:
        return cfg.get(sect, opt)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default


def load_excel_template_columns(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    try:
        return pd.read_excel(path, engine="openpyxl").columns.tolist()
    except Exception:
        return []


def load_config(path: str = "config.ini"):
    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    cfg.read(path)

    protected_columns = [c.strip() for c in _safe_get(cfg, "PROTECTED_COLUMNS", "columns").split(",") if c]
    dropdown_values: Dict[str, List[str]] = {}
    if cfg.has_section("DROPDOWN_VALUES"):
        for k in cfg["DROPDOWN_VALUES"]:
            dropdown_values[k] = [x.strip() for x in cfg.get("DROPDOWN_VALUES", k).split(",")]

    parent_child_map: Dict[str, List[str]] = {}
    if cfg.has_section("PARENT_CHILD_RELATIONS"):
        for p in cfg["PARENT_CHILD_RELATIONS"]:
            parent_child_map[p] = [x.strip() for x in cfg.get("PARENT_CHILD_RELATIONS", p).split(",")]

    return (
        protected_columns,
        dropdown_values,
        [c.strip() for c in _safe_get(cfg, "REQUIRED_COLUMNS", "columns").split(",") if c],
        _safe_get(cfg, "GENERAL", "base_save_path", "output"),
        parent_child_map,
        _safe_get(cfg, "GENERAL", "excel_autoload_path", ""),
        _safe_get(cfg, "GENERAL", "excel_template_path", "test.xlsx"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# INITIAL STATE & CONFIG
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# 1️⃣ SINGLE UPLOAD BLOCK  (georadar + cobertura)
# ──────────────────────────────────────────────────────────────────────────────
geo_file = st.file_uploader("📍 Upload Georadar CSV", type="csv")
cov_file = st.file_uploader("📶 Upload Coverage CSV", type="csv")

if geo_file and cov_file:
    # ---------------- Georadar ----------------
    geo_df_raw = pd.read_csv(geo_file)
    if not {"Latitud", "Longitud"}.issubset(geo_df_raw.columns):
        st.error("Georadar CSV must contain 'Latitud' and 'Longitud'")
        st.stop()

    st.session_state.geo_df = geo_df_raw.copy()
    st.session_state.df = geo_df_raw.rename(
        columns={"Latitud": "Latitude - Functional Location", "Longitud": "Longitude - Functional Location"}
    )
    st.session_state.df["Service Account - Work Order"] = "ANER_Senegal"
    st.session_state.df["Billing Account - Work Order"] = "ANER_Senegal"
    st.session_state.df["Work Order Type - Work Order"] = "Installation"

    # ---------------- Cobertura --------------
    cov_df_raw = pd.read_csv(cov_file)
    if not {"Latitud", "Longitud", "RSSI / RSCP (dBm)"}.issubset(cov_df_raw.columns):
        st.error("Coverage CSV must contain Latitud, Longitud, RSSI / RSCP (dBm)")
        st.stop()

    st.session_state.cov_df = cov_df_raw.copy()

    # attach dBm / Gateway info to main DF
    gdf = st.session_state.df
    cov_df_raw["LatBin"] = cov_df_raw["Latitud"].round(10)
    cov_df_raw["LonBin"] = cov_df_raw["Longitud"].round(10)
    gdf["LatBin"] = gdf["Latitude - Functional Location"].round(10)
    gdf["LonBin"] = gdf["Longitude - Functional Location"].round(10)
    cov_map = cov_df_raw.set_index(["LatBin", "LonBin"])["RSSI / RSCP (dBm)"].to_dict()
    gdf["dBm"] = gdf.apply(lambda r: cov_map.get((r.LatBin, r.LonBin)), axis=1)

    def classify(rssi):
        if pd.isna(rssi):
            return None
        if -70 <= rssi <= -10:
            return "YES"
        if -200 <= rssi < -70:
            return "NO"
        return None

    gdf["Gateway"] = gdf["dBm"].apply(classify)
    gdf.drop(columns=["LatBin", "LonBin"], inplace=True)

# ──────────────────────────────────────────────────────────────────────────────
# 2️⃣ MAP (only if both CSVs are loaded)
# ──────────────────────────────────────────────────────────────────────────────
if "geo_df" in st.session_state and "cov_df" in st.session_state:
    geo = st.session_state.geo_df
    cov = st.session_state.cov_df

    st.subheader("🗺️ Georadar & Cobertura")

    fmap = folium.Map(location=[geo["Latitud"].mean(), geo["Longitud"].mean()], zoom_start=12)

    # Georadar markers (blue)
    cluster = MarkerCluster().add_to(fmap)
    for _, r in geo.iterrows():
        folium.Marker([r.Latitud, r.Longitud], icon=folium.Icon(color="blue")).add_to(cluster)

    # Cobertura circles (rss-based colour)
    cov["LatBin"] = cov["Latitud"].round(10)
    cov["LonBin"] = cov["Longitud"].round(10)
    agg = cov.groupby(["LatBin", "LonBin"]).agg(
        Latitud=("Latitud", "mean"),
        Longitud=("Longitud", "mean"),
        RSSI=("RSSI / RSCP (dBm)", "mean"),
    ).reset_index(drop=True)

    def col(r):
        if r >= -70:
            return "green"
        elif r >= -80:
            return "orange"
        return "red"

    for _, r in agg.iterrows():
        folium.CircleMarker(
            [r.Latitud, r.Longitud],
            radius=6,
            color=col(r.RSSI),
            fill=True,
            fill_opacity=0.7,
            popup=f"RSSI: {r.RSSI:.1f} dBm",
        ).add_to(fmap)

    st_folium(fmap, width=1100, height=550)

else:
    st.info("🔼 Sube **ambos** CSV para generar mapa y tabla.")

# ──────────────────────────────────────────────────────────────────────────────
# 3️⃣ TABLE / DATA EDITOR   (solo si hay datos)
# ──────────────────────────────────────────────────────────────────────────────
if not st.session_state.df.empty:
    st.subheader("📑 Tabla editable")

    template_cols = load_excel_template_columns(EXCEL_TEMPLATE_PATH)
    display_df = st.session_state.df.copy()
    for c in template_cols:
        if c not in display_df.columns:
            display_df[c] = ""
    display_df = display_df[template_cols]

    if "edited_df" not in st.session_state:
        st.session_state.edited_df = display_df.copy()

    edited = st.data_editor(
        st.session_state.edited_df,
        num_rows="dynamic",
        use_container_width=True,
        key="editor",
    )

    if st.button("✅ Guardar cambios en tabla"):
        st.session_state.edited_df = edited.copy()
        st.success("Tabla actualizada.")

# ──────────────────────────────────────────────────────────────────────────────
st.caption("Desarrollado en Streamlit • Última actualización: 2025-06-17")
