from __future__ import annotations
import io, os
from datetime import datetime, timedelta, date
from typing import Dict, List

import pandas as pd
import streamlit as st
import configparser

# ─────────────────────────── Nuevas importaciones para el mapa ───────────────
import folium
from folium.plugins import MarkerCluster
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


def load_config(
    path: str = "config.ini",
) -> tuple[
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
        columns={
            "Latitud": "Latitude - Functional Location",
            "Longitud": "Longitude - Functional Location",
        }
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

    def classify(v: float | None):
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

# ─────────────── 2b) Mapa interactivo ───────────────

def color_from_dbm(v: float | None) -> str:
    """Devuelve color según reglas de cobertura."""
    if pd.isna(v):
        return "gray"
    if v >= -70:
        return "green"
    if -80 <= v < -70:
        return "orange"
    return "red"

with st.container():
    st.subheader("🗺️ Mapa de puntos de georradar y cobertura")

    geo_df = st.session_state.geo_df
    cov_df = st.session_state.cov_df

    # Centro del mapa
    center_lat = geo_df["Latitud"].mean()
    center_lon = geo_df["Longitud"].mean()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=13, control_scale=True)

    cluster = MarkerCluster(name="Puntos agrupados").add_to(m)

    # Puntos de georradar (círculos)
    for _, row in geo_df.iterrows():
        dbm_val = row.get("dBm")
        color = color_from_dbm(dbm_val)
        tooltip = folium.Tooltip(f"Georadar\nMedia dBm: {dbm_val if not pd.isna(dbm_val) else 'N/A'}")
        folium.CircleMarker(
            location=[row["Latitud"], row["Longitud"]],
            radius=6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            tooltip=tooltip,
        ).add_to(cluster)

    # Puntos de cobertura (cuadrados)
    for _, row in cov_df.iterrows():
        rssi_val = row["RSSI / RSCP (dBm)"]
        color = color_from_dbm(rssi_val)
        tooltip = folium.Tooltip(f"Coverage\nRSSI/RSCP: {rssi_val}")
        folium.RegularPolygonMarker(
            location=[row["Latitud"], row["Longitud"]],
            number_of_sides=4,
            radius=6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            tooltip=tooltip,
        ).add_to(cluster)

    st_folium(m, height=450, width="100%")

# ─────────────── 3) Tabla editable + herramientas ───────────────
st.subheader("📑 Tabla editable")

_template_cols = load_excel_template_columns(EXCEL_TEMPLATE_PATH)
disp = st.session_state.df.copy()
for c in _template_cols:
    if c not in disp.columns:
        disp[c] = ""

disp = disp[_template_cols]
if "edited_df" not in st.session_state:
    st.session_state.edited_df = disp.copy()

edited = st.data_editor(
    st.session_state.edited_df,
    num_rows="dynamic",
    use_container_width=True,
    key="editor",
)
if st.button("💾 Guardar cambios"):
    st.session_state.edited_df = edited.copy()
    st.success("Cambios guardados.")

# Añadir datos en bloque
st.markdown("### 🧩 Añadir datos en bloque")
with st.expander("➕ Añadir valor a toda una columna"):
    editable_cols = [c for c in edited.columns if c not in PROTECTED_COLUMNS]
    col_sel = st.selectbox("Columna", editable_cols)

    if col_sel == "Name - Child Functional Location":
        parents = edited["Name - Parent Functional Location"].dropna().unique()
        par = parents[0] if len(parents) else None
        if par and par in PARENT_CHILD_MAP:
            val = st.selectbox("Valor hijo", PARENT_CHILD_MAP[par])
        else:
            st.warning("Define primero 'Parent Functional Location'.")
            val = ""
    elif col_sel in DROPDOWN_VALUES:
        val = st.selectbox("Valor", DROPDOWN_VALUES[col_sel])
    else:
        val = st.text_input("Valor")

    if st.button("📌 Aplicar"):
        if col_sel and val:
            st.session_state.edited_df[col_sel] = val
            st.success("Valor aplicado.")
            st.rerun()

# Autocompletar fechas/horas
st.markdown("### ⏱️ Autocompletar fechas/horas")
with st.expander("Rellenar columnas temporales"):
    d0 = st.date_input("Fecha inicial", value=date.today())
    t0 = st.time_input(
        "Hora inicial",
        value=datetime.now().time().replace(second=0, microsecond=0),
    )
    if st.button("🕒 Generar 27 min"):
        start_dt = datetime.combine(d0, t0)
        incs = [start_dt + timedelta(minutes=27 * i) for i in range(len(st.session_state.edited_df))]
        full = [
            "Promised window From - Work Order",
            "Promised window To - Work Order",
            "StartTime - Bookable Resource Booking",
            "EndTime - Bookable Resource Booking",
        ]
        time_only = [
            "Time window From - Work Order",
            "Time window To - Work Order",
        ]
        for c in full:
            if c in st.session_state.edited_df.columns:
                st.session_state.edited_df[c] = incs
        for c in time_only:
            if c in st.session_state.edited
