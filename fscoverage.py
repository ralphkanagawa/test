from __future__ import annotations
import io, os
from datetime import datetime, timedelta, date
from typing import Dict, List

import pandas as pd
import streamlit as st
import configparser
import pydeck as pdk

import streamlit.components.v1 as components


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

st.set_page_config(page_title="Potential Work Orders Management", layout="wide")

# ───────────────  Carga CSV ───────────────

geo_file = None
cov_file = None

if "processed" not in st.session_state:
    col_geo, col_cov = st.columns([1, 1])
    with col_geo:
        geo_file = st.file_uploader("📍 Georadar CSV", type="csv")
    with col_cov:
        cov_file = st.file_uploader("📶 Coverage CSV", type="csv")

    # Comprobación tras carga
    if geo_file and cov_file:
        # Procesamiento como ya tienes abajo
        geo_raw = pd.read_csv(geo_file)
        if not {"Latitud", "Longitud"}.issubset(geo_raw.columns):
            st.error("Georadar debe tener columnas Latitud y Longitud")
            st.stop()

        st.session_state.geo_df = geo_raw.copy()
        gdf = geo_raw.rename(columns={
            "Latitud": "Latitude - Functional Location",
            "Longitud": "Longitude - Functional Location",
        })
        gdf["Service Account - Work Order"] = "ANER_Senegal"
        gdf["Billing Account - Work Order"] = "ANER_Senegal"
        gdf["Work Order Type - Work Order"] = "Installation"
        st.session_state.df = gdf

        cov_raw = pd.read_csv(cov_file)
        if not {"Latitud", "Longitud", "RSSI / RSCP (dBm)"}.issubset(cov_raw.columns):
            st.error("Coverage debe tener Latitud, Longitud, RSSI / RSCP (dBm)")
            st.stop()

        st.session_state.cov_df = cov_raw.copy()

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
        st.rerun()  # Forzar actualización para ocultar los uploaders
else:
    st.markdown("✔️ CSVs cargados y procesados correctamente.")


# ───────────────  Procesamiento una única vez ───────────────
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

if "processed" not in st.session_state:
    st.info("⬆️ Sube ambos CSV para continuar")
    st.stop()

# ───────────────  Controles superiores ───────────────

# Inyectar estilo una sola vez, fuera de columnas
st.markdown("""
    <style>
    button[kind="primary"] {
        white-space: nowrap;
        padding: 0.4rem 1rem;
        font-size: 0.9rem;
    }
    </style>
""", unsafe_allow_html=True)

# Botones alineados
col_left, col_spacer, col_right = st.columns([2, 6, 2])

# ✅ AQUÍ defines 'edited', que siempre estará disponible para todos los botones debajo
edited = st.data_editor(
    st.session_state.edited_df,
    num_rows="dynamic",
    use_container_width=True,
    key="editor"
)

with col_left:
    if st.button("🔁 Volver a cargar archivos", key="reload_button"):
        for k in ["processed", "df", "geo_df", "cov_df", "edited_df"]:
            st.session_state.pop(k, None)
        st.rerun()

with col_right:
    if st.button("💾 Guardar cambios", key="save_changes_top"):
        st.session_state.edited_df = edited.copy()
        st.success("Cambios guardados.")

# ───────────────  Tabla editable + herramientas ───────────────

_template_cols = load_excel_template_columns(EXCEL_TEMPLATE_PATH)
disp = st.session_state.df.copy()
for c in _template_cols:
    if c not in disp.columns:
        disp[c] = ""

disp = disp[_template_cols]

# Asegura que 'edited_df' exista
if "edited_df" not in st.session_state:
    st.session_state.edited_df = disp.copy()

# Guarda una copia de trabajo sincronizada
st.session_state["latest_edited"] = edited.copy()

col1, col2, col3 = st.columns(3)

# --- Añadir datos en bloque ---
with col1:
    st.markdown("### ➕ Añadir datos en bloque")
    editable_cols = [c for c in edited.columns if c not in PROTECTED_COLUMNS]
    col_sel = st.selectbox("Columna", editable_cols, key="col_sel")

    if col_sel == "Name - Child Functional Location":
        parents = edited["Name - Parent Functional Location"].dropna().unique()
        par = parents[0] if len(parents) else None
        if par and par in PARENT_CHILD_MAP:
            val = st.selectbox("Valor hijo", PARENT_CHILD_MAP[par], key="child_val")
        else:
            st.warning("Define primero 'Parent Functional Location'.")
            val = ""
    elif col_sel in DROPDOWN_VALUES:
        val = st.selectbox("Valor", DROPDOWN_VALUES[col_sel], key="dropdown_val")
    else:
        val = st.text_input("Valor", key="text_val")

    if st.button("📌 Aplicar", key="apply_val"):
        if col_sel and val:
            st.session_state.edited_df[col_sel] = val
            st.success("Valor aplicado.")
            st.rerun()

# --- Autocompletar fechas/horas ---
with col2:
    st.markdown("### ⏱️ Autocompletar fechas/horas")
    d0 = st.date_input("Fecha inicial", value=date.today(), key="fecha_ini")
    t0 = st.time_input("Hora inicial", value=datetime.now().time().replace(second=0, microsecond=0), key="hora_ini")
    if st.button("🕒 Generar 27 min", key="gen_27min"):
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

# --- Descargar Excel ---
with col3:
    st.markdown("### 💾 Descargar Excel")
    if st.button("Generar y descargar Excel", key="gen_excel"):
        df_out = edited.copy()
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


# ───────────────  Mapa georadar y cobertura ───────────────
# Preparar datos de georadar con dBm ya calculado en st.session_state.df
geo_points = (
    st.session_state.edited_df[[  # ← Aquí usamos el DF editado por el usuario
        "Latitude - Functional Location",
        "Longitude - Functional Location",
        "dBm",
    ]]
    .dropna(subset=["Latitude - Functional Location", "Longitude - Functional Location"])
    .copy()
)
geo_points.rename(
    columns={
        "Latitude - Functional Location": "lat",
        "Longitude - Functional Location": "lon",
        "dBm": "coverage",
    },
    inplace=True,
)

# Asignar color según cobertura

def color_from_dbm(v: float | None):
    if pd.isna(v):
        return [255, 255, 255]  # gris si no hay valor
    if v >= -70:
        return [0, 153, 51]  # verde
    if -80 <= v < -70:
        return [255, 165, 0]  # naranja
    return [255, 0, 0]  # rojo

geo_points["color"] = geo_points["coverage"].apply(color_from_dbm)

# Datos de cobertura originales
cov_points = (
    st.session_state.cov_df[["Latitud", "Longitud", "RSSI / RSCP (dBm)"]]
    .dropna(subset=["Latitud", "Longitud"])
    .copy()
)
cov_points.rename(
    columns={
        "Latitud": "lat",
        "Longitud": "lon",
        "RSSI / RSCP (dBm)": "coverage",
    },
    inplace=True,
)
cov_points["color"] = [[128, 128, 128]] * len(cov_points)  # gris fijo

# Layers de PyDeck
layers = [
    # Capa de puntos de cobertura (gris, menor radio)
    pdk.Layer(
        "ScatterplotLayer",
        data=cov_points,
        get_position="[lon, lat]",
        get_radius=3,
        get_fill_color="color",
        opacity=0.4,
        pickable=True,
        tooltip=True,
    ),
    # Capa de puntos georadar con color por dBm
    pdk.Layer(
        "ScatterplotLayer",
        data=geo_points,
        get_position="[lon, lat]",
        get_radius=2,
        get_fill_color="color",
        pickable=True,
    ),
]

# Vista inicial (centrada en la media de los puntos georadar)
if not geo_points.empty:
    init_view_state = pdk.ViewState(
        latitude=geo_points["lat"].mean(),
        longitude=geo_points["lon"].mean(),
        zoom=17,
    )
else:
    init_view_state = pdk.ViewState(latitude=0, longitude=0, zoom=2)

# Tooltip
tooltip = {
    "html": "<b>dBm:</b> {coverage}",
    "style": {"color": "white"},
}

st.pydeck_chart(
    pdk.Deck(layers=layers, initial_view_state=init_view_state, tooltip=tooltip),
    height=900  # puedes ajustar a 800, 900 si quieres más espacio
)

st.caption("Desarrollado en Streamlit • Última actualización: 2025-06-30")
