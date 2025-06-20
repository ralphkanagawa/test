"""
Work Orders Tool (Streamlit)
───────────────────────────
Versión completa con:
• Agrupación de puntos georadar (círculos) y cobertura (cuadrados) mediante MarkerCluster.
• Colores basados en la media de cobertura (`dBm`) para georadar y en el RSSI individual para cobertura.
• Tooltip al pasar el ratón y popup al hacer clic mostrando el valor de cobertura.
• Resto de utilidades: edición masiva, autocompletado temporal, descarga a Excel.
"""

from __future__ import annotations
import io, os
from datetime import datetime, timedelta, date
from typing import Dict, List

import pandas as pd
import streamlit as st
import configparser

import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

# ─────────────────────────── Config helpers ─────────────────────────────

def _safe_get(cfg: configparser.ConfigParser, sect: str, opt: str, default: str = "") -> str:
    """Read an option from a config section safely, returning *default* if it does not exist."""
    try:
        return cfg.get(sect, opt)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default


def load_excel_template_columns(path: str) -> List[str]:
    """Return column names from the Excel template, so the editor shows all expected columns."""
    if os.path.exists(path):
        try:
            return pd.read_excel(path, engine="openpyxl").columns.tolist()
        except Exception:
            pass
    return []


def load_config(path: str = "config.ini") -> tuple[
    List[str], Dict[str, List[str]], List[str], str, Dict[str, List[str]], str, str
]:
    """Load configuration from INI file and expose several helpers used in the UI."""

    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # preserve case for column names
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
        _safe_get(cfg, "GENERAL", "excel_template_path", "template.xlsx"),
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

# ─────────────── 2) Procesamiento ───────────────
if geo_file and cov_file and "processed" not in st.session_state:
    # Leer Georadar
    geo_raw = pd.read_csv(geo_file)
    if not {"Latitud", "Longitud"}.issubset(geo_raw.columns):
        st.error("Georadar debe tener columnas Latitud y Longitud")
        st.stop()

    st.session_state.geo_df = geo_raw.copy()

    # Adaptar a columnas del modelo de Excel
    gdf = geo_raw.rename(
        columns={
            "Latitud": "Latitude - Functional Location",
            "Longitud": "Longitude - Functional Location",
        }
    )
    gdf["Service Account - Work Order"] = gdf["Billing Account - Work Order"] = "ANER_Senegal"
    gdf["Work Order Type - Work Order"] = "Installation"
    st.session_state.df = gdf

    # Leer Cobertura
    cov_raw = pd.read_csv(cov_file)
    if not {"Latitud", "Longitud", "RSSI / RSCP (dBm)"}.issubset(cov_raw.columns):
        st.error("Coverage debe tener Latitud, Longitud, RSSI / RSCP (dBm)")
        st.stop()

    st.session_state.cov_df = cov_raw.copy()

    # Calcular la media de cobertura para cada punto georadar
    # Agrupamos cobertura en bins de ~1‑2 m (5 decimales ≈ 1.1 m)
    gdf["LatBin"] = gdf["Latitude - Functional Location"].round(5)
    gdf["LonBin"] = gdf["Longitude - Functional Location"].round(5)
    cov_raw["LatBin"] = cov_raw["Latitud"].round(5)
    cov_raw["LonBin"] = cov_raw["Longitud"].round(5)

    avg_cov = (
        cov_raw.groupby(["LatBin", "LonBin"])["RSSI / RSCP (dBm)"].mean().to_dict()
    )
    gdf["dBm"] = gdf.apply(lambda r: avg_cov.get((r.LatBin, r.LonBin)), axis=1)

    # Clasificación Gateway (ejemplo heredado)
    def classify(v):
        if pd.isna(v):
            return None
        return "YES" if -70 <= v <= -10 else "NO" if -200 <= v < -70 else None

    gdf["Gateway"] = gdf["dBm"].apply(classify)
    gdf.drop(columns=["LatBin", "LonBin"], inplace=True)

    st.session_state.processed = True
    st.success("✔ Datos procesados")

if "processed" not in st.session_state:
    st.info("⬆️ Sube ambos CSV para continuar")
    st.stop()

# ─────────────── 3) Mapa ───────────────


def color_from_dbm(v: float | None) -> str:
    if pd.isna(v):
        return "gray"
    return "green" if v >= -70 else "orange" if -80 <= v < -70 else "red"


def add_markers(m: folium.Map, geo_df: pd.DataFrame, cov_df: pd.DataFrame):
    cluster = MarkerCluster(name="Puntos Agrupados", spiderfy_on_max_zoom=True).add_to(m)

    # Círculos (georadar)  
    for _, r in geo_df.iterrows():
        color = color_from_dbm(r["dBm"])
        folium.CircleMarker(
            location=[r["Latitude - Functional Location"], r["Longitude - Functional Location"]],
            radius=6,
            color=color,
            fill=True,
            fill_color=color,
            tooltip=f"Georadar\nMedia dBm: {r['dBm']:.1f}" if not pd.isna(r["dBm"]) else "Georadar\nSin dBm",
            popup=folium.Popup(
                f"<b>Georadar</b><br>Media dBm: {r['dBm']:.1f}" if not pd.isna(r["dBm"]) else "<b>Georadar</b><br>Sin dBm",
                max_width=200,
            ),
        ).add_to(cluster)

    # Cuadrados (cobertura)
    for _, r in cov_df.iterrows():
        color = color_from_dbm(r["RSSI / RSCP (dBm)"])
        folium.RegularPolygonMarker(
            location=[r["Latitud"], r["Longitud"]],
            number_of_sides=4,
            radius=6,
            color=color,
            fill=True,
            fill_color=color,
            tooltip=f"Coverage\nRSSI: {r['RSSI / RSCP (dBm)']:.1f}",
            popup=folium.Popup(
                f"<b>Coverage</b><br>RSSI: {r['RSSI / RSCP (dBm)']:.1f}", max_width=200
            ),
        ).add_to(cluster)


gdf = st.session_state.df.copy()
cov_df = st.session_state.cov_df.copy()

st.subheader("🗺️ Mapa de georradar y cobertura")
center_lat, center_lon = (
    st.session_state.geo_df["Latitud"].mean(),
    st.session_state.geo_df["Longitud"].mean(),
)
map_obj = folium.Map(location=[center_lat, center_lon], zoom_start=13, control_scale=True)
add_markers(map_obj, gdf, cov_df)
folium.LayerControl().add_to(map_obj)

st_folium(map_obj, height=450, width="100%")

# ─────────────── 4) Tabla editable + herramientas ───────────────

st.subheader("📑 Tabla editable")
_template_cols = load_excel_template_columns(EXCEL_TEMPLATE_PATH)

# Asegurar que todas las columnas del template existen

disp = st.session_state.df.copy()
for c in _template_cols:
    if c not in disp.columns:
        disp[c] = ""

disp = disp[_template_cols]

# Guardar la edición en estado
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

# ─────────────── 4.1 Añadir datos en bloque ───────────────

st.markdown("### 🧩 Añadir datos en bloque")
with st.expander("➕ Añadir valor a toda una columna"):
    editable_cols = [c for c in edited.columns if c not in PROTECTED_COLUMNS]
    col_sel = st.selectbox("Columna", editable_cols)

    if col_sel == "Name - Child Functional Location":
        # Relleno dependiente
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

# ─────────────── 4.2 Autocompletar fechas/horas ───────────────

st.markdown("### ⏱️ Autocompletar fechas/horas")
with st.expander("Rellenar columnas temporales"):
    d0 = st.date_input("Fecha inicial", value=date.today())
    t0 = st.time_input(
        "Hora inicial", value=datetime.now().time().replace(second=0, microsecond=0)
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
            if c in st.session_state.edited_df.columns:
                st.session_state.edited_df[c] = [d.time().strftime("%H:%M:%S") for d in incs]
        st.success("Columnas temporales rellenadas.")
        st.rerun()

# ─────────────── 4.3 Descargar a Excel ───────────────

st.markdown("### 💾 Descargar Excel")
if st.button("Generar y descargar Excel"):
    df_out = st.session_state.edited_df.copy()
    for c in _template_cols:
        if c not in df_out.columns:
            df_out[c] = ""
    df_out = df_out[_template_cols]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df_out.to_excel(w, index=False)
    buf.seek(0)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.download_button(
        "⬇️ Descargar Excel",
        data=buf,
        file_name=f"workorders_{ts}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.caption("Desarrollado en Streamlit • Última actualización: 2025-06-20")
