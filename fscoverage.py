"""
Streamlit version of the Potential Work Orders tool.
---------------------------------------------------
- Replaces all Tk/ttkbootstrap UI with Streamlit widgets.
- Keeps the core data‑processing logic (load CSVs, match coverage, bulk add, granular editing, save to Excel).
- Persists the working DataFrame in `st.session_state` so users can perform many actions without losing data.
- Gracefully handles the absence of `config.ini` by falling back to sensible defaults, avoiding the previous
  `configparser.NoSectionError`.
- Uses `st.date_input` + `st.time_input` instead of the non‑existent `st.datetime_input` to fix the AttributeError.
- Provides a "Añadir datos en bloque" expander with a column selector that populates correctly.

How to run locally
------------------
```bash
pip install -r requirements.txt  # streamlit pandas openpyxl folium (optional)
streamlit run streamlit_app.py
```
On Streamlit Cloud push this file and a `requirements.txt` (see above) to GitHub and Deploy.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, date, time
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st
import configparser

# -----------------------------------------------------------------------------
# Configuration helpers
# -----------------------------------------------------------------------------

def _safe_get(config: configparser.ConfigParser, section: str, option: str, default: str = "") -> str:
    """Return the value for *option* in *section* or *default* if the section/option is missing."""
    try:
        return config.get(section, option)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default


def load_config(path: str = "config.ini") -> tuple[
    List[str], Dict[str, List[str]], List[str], str, Dict[str, List[str]], str
]:
    """Load configuration from *path*; fall back to safe defaults if file or keys are missing."""

    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # preserve case
    cfg.read(path)

    protected_columns = [c.strip() for c in _safe_get(cfg, "PROTECTED_COLUMNS", "columns", "").split(",") if c]
    base_save_path = _safe_get(cfg, "GENERAL", "base_save_path", "output")
    excel_autoload_path = _safe_get(cfg, "GENERAL", "excel_autoload_path", "")

    dropdown_values: Dict[str, List[str]] = {}
    if cfg.has_section("DROPDOWN_VALUES"):
        for key in cfg["DROPDOWN_VALUES"]:
            dropdown_values[key] = [x.strip() for x in cfg.get("DROPDOWN_VALUES", key).split(",")]

    required_columns = [c.strip() for c in _safe_get(cfg, "REQUIRED_COLUMNS", "columns", "").split(",") if c]

    parent_child_map: Dict[str, List[str]] = {}
    if cfg.has_section("PARENT_CHILD_RELATIONS"):
        for parent in cfg["PARENT_CHILD_RELATIONS"]:
            parent_child_map[parent] = [x.strip() for x in cfg.get("PARENT_CHILD_RELATIONS", parent).split(",")]

    return (
        protected_columns,
        dropdown_values,
        required_columns,
        base_save_path,
        parent_child_map,
        excel_autoload_path,
    )


# -----------------------------------------------------------------------------
# App state initialisation
# -----------------------------------------------------------------------------

DEFAULT_DF = pd.DataFrame()

if "df" not in st.session_state:
    st.session_state.df = DEFAULT_DF.copy()

(
    PROTECTED_COLUMNS,
    DROPDOWN_VALUES,
    REQUIRED_COLUMNS,
    BASE_SAVE_PATH,
    PARENT_CHILD_MAP,
    EXCEL_AUTOLOAD,
) = load_config()

st.set_page_config(page_title="Work Orders Tool", layout="wide")
st.title("📋 Potential Work Orders Management (Streamlit)")

# -----------------------------------------------------------------------------
# File uploaders
# -----------------------------------------------------------------------------

col1, col2 = st.columns(2)

with col1:
    geo_file = st.file_uploader("📍 Subir Georadar CSV", type="csv", key="geo")

with col2:
    cov_file = st.file_uploader("📶 Subir Coverage CSV", type="csv", key="cov")

# -----------------------------------------------------------------------------
# Helpers for data processing
# -----------------------------------------------------------------------------

def load_georadar(csv_bytes: bytes) -> None:
    df = pd.read_csv(io.BytesIO(csv_bytes))
    if not {"Latitud", "Longitud"}.issubset(df.columns):
        st.error("El CSV debe contener las columnas 'Latitud' y 'Longitud'.")
        return

    st.session_state.df = df.rename(
        columns={"Latitud": "Latitude - Functional Location", "Longitud": "Longitude - Functional Location"}
    )
    # Hard‑coded fields
    st.session_state.df["Service Account - Work Order"] = "ANER_Senegal"
    st.session_state.df["Billing Account - Work Order"] = "ANER_Senegal"
    st.session_state.df["Work Order Type - Work Order"] = "Installation"

    st.success("Coordenadas añadidas con éxito ✅")


def load_coverage(csv_bytes: bytes) -> None:
    if st.session_state.df.empty:
        st.warning("Primero sube el CSV de Georadar.")
        return

    cov_df = pd.read_csv(io.BytesIO(csv_bytes))
    required = {"Latitud", "Longitud", "RSSI / RSCP (dBm)"}
    if not required.issubset(cov_df.columns):
        st.error("El CSV de cobertura debe contener Latitud, Longitud y RSSI / RSCP (dBm).")
        return

    # Binning to 1e‑10 deg for matching
    st.session_state.df["LatBin"] = st.session_state.df["Latitude - Functional Location"].round(10)
    st.session_state.df["LonBin"] = st.session_state.df["Longitude - Functional Location"].round(10)
    cov_df["LatBin"] = cov_df["Latitud"].round(10)
    cov_df["LonBin"] = cov_df["Longitud"].round(10)

    cov_map = cov_df.set_index(["LatBin", "LonBin"])["RSSI / RSCP (dBm)"].to_dict()
    st.session_state.df["dBm"] = st.session_state.df.apply(lambda r: cov_map.get((r.LatBin, r.LonBin)), axis=1)

    def classify(rssi):
        if pd.isna(rssi):
            return None
        if -70 <= rssi <= -10:
            return "YES"
        if -200 <= rssi < -70:
            return "NO"
        return None

    st.session_state.df["Gateway"] = st.session_state.df["dBm"].apply(classify)
    st.session_state.df.drop(columns=["LatBin", "LonBin"], inplace=True)

    st.success("Cobertura procesada y aplicada ✅")


# -----------------------------------------------------------------------------
# Trigger processing on upload
# -----------------------------------------------------------------------------

if geo_file is not None and geo_file.name not in st.session_state.get("_geo_loaded", ""):
    load_georadar(geo_file.getvalue())
    st.session_state._geo_loaded = geo_file.name

if cov_file is not None and cov_file.name not in st.session_state.get("_cov_loaded", ""):
    load_coverage(cov_file.getvalue())
    st.session_state._cov_loaded = cov_file.name

# -----------------------------------------------------------------------------
# Data editor (granular editing)
# -----------------------------------------------------------------------------

if st.session_state.df.empty:
    st.info("Sube un CSV para comenzar.")
else:
    st.subheader("📑 Vista y edición de la tabla")

    # Creamos una copia temporal para la edición
    if "edited_df" not in st.session_state:
        st.session_state.edited_df = st.session_state.df.copy()

    # Editor de tabla
    result_df = st.data_editor(
        st.session_state.edited_df,
        num_rows="dynamic",
        use_container_width=True,
        key="editor"
    )

    # Botón explícito para aplicar cambios
    if st.button("✅ Aplicar cambios a la tabla principal"):
        st.session_state.df = result_df.copy()
        st.session_state.edited_df = result_df.copy()
        st.success("Cambios aplicados.")

    # ---------------------------------------------------------------------
    # Bloque: añadir datos en una columna
    # ---------------------------------------------------------------------

    with st.expander("🛠️ Añadir datos en bloque (todas las filas)"):
        editable_cols = [c for c in st.session_state.df.columns if c not in PROTECTED_COLUMNS]
        if editable_cols:
            col_to_edit = st.selectbox("Selecciona columna", editable_cols, key="block_col")
            if col_to_edit:
                if col_to_edit in DROPDOWN_VALUES:
                    value = st.selectbox("Valor a aplicar", DROPDOWN_VALUES[col_to_edit], key="block_val")
                else:
                    value = st.text_input("Valor a aplicar", key="block_val_text")

                if st.button("Aplicar a todas las filas", key="apply_block") and value != "":
                    st.session_state.df[col_to_edit] = value
                    st.success(f"Valor '{value}' aplicado en la columna '{col_to_edit}'.")
        else:
            st.warning("No hay columnas editables.")

    # ---------------------------------------------------------------------
    # Guardar / descargar Excel
    # ---------------------------------------------------------------------

    st.subheader("💾 Guardar / Descargar Excel")
    col_date, col_time = st.columns(2)
    with col_date:
        date_input: date = st.date_input("Fecha inicial", value=date.today(), key="start_date")
    with col_time:
        time_input: time = st.time_input("Hora inicial", value=datetime.now().time().replace(second=0, microsecond=0), key="start_time")

    if st.button("Generar y descargar Excel", key="save_excel"):
        start_dt = datetime.combine(date_input, time_input)
        increments = [start_dt + timedelta(minutes=27 * i) for i in range(len(st.session_state.df))]

        full_dt_cols = [
            "Promised window From - Work Order",
            "Promised window To - Work Order",
            "StartTime - Bookable Resource Booking",
            "EndTime - Bookable Resource Booking",
        ]
        time_only_cols = [
            "Time window From - Work Order",
            "Time window To - Work Order",
        ]

        for col in full_dt_cols:
            if col in st.session_state.df.columns:
                st.session_state.df[col] = increments
        for col in time_only_cols:
            if col in st.session_state.df.columns:
                st.session_state.df[col] = [d.time().strftime("%H:%M:%S") for d in increments]

        missing = [c for c in REQUIRED_COLUMNS if c in st.session_state.df.columns and st.session_state.df[c].isna().any()]
        if missing:
            st.error("Faltan datos en las columnas obligatorias:\n" + "\n".join(missing))
        else:
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                st.session_state.df.to_excel(writer, index=False)
            out.seek(0)
            timestamp = start_dt.strftime("%Y%m%d_%H%M%S")
            file_name = f"datos_{timestamp}.xlsx"
            st.download_button("⬇️ Descargar Excel", data=out, file_name=file_name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -----------------------------------------------------------------------------
# Footer
# -----------------------------------------------------------------------------

st.caption("Desarrollado en Streamlit • Última actualización: 2025‑06‑17")
