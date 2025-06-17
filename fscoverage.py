"""
Streamlit adaptation of the original Tkinter/ttkbootstrap desktop application.

Main goals:
- Keep the core CSV → DataFrame → Excel workflow.
- Replace all GUI elements with Streamlit widgets.
- Store the working DataFrame in st.session_state so the user can perform
  multiple actions without losing data.
- Offer a data‑grid style editor via st.data_editor so rows can be edited
  directly in the browser (replaces granular‐row dialogs).
- Provide “Add block data” functionality via a simple form inside an expander.
- Allow the user to download the processed Excel file instead of saving it
  to a fixed path on the server (safer for Streamlit Cloud).

Save this file as `streamlit_app.py` in the root of your GitHub repo and make
sure you have a `requirements.txt` with at least:

streamlit
pandas
openpyxl
folium

Then deploy in Streamlit Cloud with `Main file path` → `streamlit_app.py`.
"""

from __future__ import annotations

import os
import io
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st
import configparser
import folium  # kept for future map display if desired

###############################################################################
# Config helpers
###############################################################################

def load_config(path: str = "config.ini") -> Tuple[
    List[str], Dict[str, List[str]], List[str], str, Dict[str, List[str]], str
]:
    """Read the INI configuration and return the key settings."""

    config = configparser.ConfigParser()
    config.optionxform = str  # preserve case
    config.read(path)

    protected_columns = [c.strip() for c in config.get("PROTECTED_COLUMNS", "columns").split(",")]
    base_save_path = config.get("GENERAL", "base_save_path", fallback="./output")
    excel_autoload_path = config.get("GENERAL", "excel_autoload_path", fallback="")

    dropdown_values: Dict[str, List[str]] = {}
    if "DROPDOWN_VALUES" in config:
        for key in config["DROPDOWN_VALUES"]:
            dropdown_values[key] = [item.strip() for item in config.get("DROPDOWN_VALUES", key).split(",")]

    required_columns = [c.strip() for c in config.get("REQUIRED_COLUMNS", "columns").split(",")]

    parent_child_map: Dict[str, List[str]] = {}
    if "PARENT_CHILD_RELATIONS" in config:
        for parent in config["PARENT_CHILD_RELATIONS"]:
            parent_child_map[parent] = [x.strip() for x in config.get("PARENT_CHILD_RELATIONS", parent).split(",")]

    return (
        protected_columns,
        dropdown_values,
        required_columns,
        base_save_path,
        parent_child_map,
        excel_autoload_path,
    )

###############################################################################
# Utility functions
###############################################################################

def apply_coverage(df_base: pd.DataFrame, df_cov: pd.DataFrame) -> pd.DataFrame:
    """Match coverage RSSI/RSCP values by rounded lat/lon bins."""
    df = df_base.copy()

    df["LatBin"] = df["Latitude - Functional Location"].round(10)
    df["LonBin"] = df["Longitude - Functional Location"].round(10)
    df_cov["LatBin"] = df_cov["Latitud"].round(10)
    df_cov["LonBin"] = df_cov["Longitud"].round(10)

    cov_map = df_cov.set_index(["LatBin", "LonBin"])["RSSI / RSCP (dBm)"].to_dict()

    df["dBm"] = df.apply(lambda r: cov_map.get((r["LatBin"], r["LonBin"])), axis=1)

    def classify_gateway(rssi):
        if pd.isna(rssi):
            return None
        if -70 <= rssi <= -10:
            return "YES"
        if -200 <= rssi < -70:
            return "NO"
        return None

    df["Gateway"] = df["dBm"].apply(classify_gateway)
    return df.drop(columns=["LatBin", "LonBin"])


def generate_time_columns(df: pd.DataFrame, start_dt: datetime) -> pd.DataFrame:
    """Generate the Work‑Order/Booking time columns based on a starting datetime."""
    increments = [start_dt + timedelta(minutes=27 * i) for i in range(len(df))]

    df_out = df.copy()

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
        if col in df_out.columns:
            df_out[col] = increments

    for col in time_only_cols:
        if col in df_out.columns:
            df_out[col] = [dt.time().strftime("%H:%M:%S") for dt in increments]

    return df_out


def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Return the DataFrame as Excel bytes for download."""
    with io.BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        return buffer.getvalue()

###############################################################################
# Streamlit UI
###############################################################################

st.set_page_config(page_title="Work Orders Management", layout="wide")

(
    PROTECTED_COLUMNS,
    DROPDOWN_VALUES,
    REQUIRED_COLUMNS,
    BASE_SAVE_PATH,
    PARENT_CHILD_MAP,
    EXCEL_AUTOLOAD,
) = load_config()

# Initialise session‑state DataFrame
if "df" not in st.session_state:
    if EXCEL_AUTOLOAD and os.path.isfile(EXCEL_AUTOLOAD):
        st.session_state.df = pd.read_excel(EXCEL_AUTOLOAD)
    else:
        st.session_state.df = pd.DataFrame()

st.title("📋 Potential Work Orders Management (Streamlit)")

###############################################################################
# File uploaders
###############################################################################

col1, col2 = st.columns(2)

with col1:
    geo_file = st.file_uploader(
        "Sube archivo CSV de Georadar (Latitud/Longitud)",
        type="csv",
        key="geo_file",
    )

with col2:
    cov_file = st.file_uploader(
        "Sube archivo CSV de Cobertura (RSSI/RSCP)",
        type="csv",
        key="cov_file",
    )

# Process Georadar CSV
if geo_file is not None:
    df_geo = pd.read_csv(geo_file)
    if {"Latitud", "Longitud"}.issubset(df_geo.columns):
        st.session_state.df = pd.DataFrame()  # reset
        st.session_state.df["Latitude - Functional Location"] = df_geo["Latitud"]
        st.session_state.df["Longitude - Functional Location"] = df_geo["Longitud"]
        st.session_state.df["Service Account - Work Order"] = "ANER_Senegal"
        st.session_state.df["Billing Account - Work Order"] = "ANER_Senegal"
        st.session_state.df["Work Order Type - Work Order"] = "Installation"
        st.success("Coordenadas cargadas y columnas base añadidas ✔️")
    else:
        st.error("El CSV debe contener las columnas 'Latitud' y 'Longitud'.")

# Process Coverage CSV
if cov_file is not None and not st.session_state.df.empty:
    df_cov = pd.read_csv(cov_file)
    needed = {"Latitud", "Longitud", "RSSI / RSCP (dBm)"}
    if needed.issubset(df_cov.columns):
        st.session_state.df = apply_coverage(st.session_state.df, df_cov)
        st.success("Cobertura emparejada y columna 'Gateway' generada ✔️")
    else:
        st.error("El CSV de cobertura debe contener columnas Latitud, Longitud y RSSI / RSCP (dBm).")

###############################################################################
# Add block data form
###############################################################################

if not st.session_state.df.empty:
    with st.expander("➕ Añadir datos en bloque", expanded=False):
        editable_cols = [c for c in st.session_state.df.columns if c not in PROTECTED_COLUMNS]
        col_to_edit = st.selectbox("Selecciona columna", editable_cols)

        # Dynamic input depending on dropdown config
        if col_to_edit in DROPDOWN_VALUES:
            value = st.selectbox("Valor a aplicar", DROPDOWN_VALUES[col_to_edit])
        else:
            value = st.text_input("Valor a aplicar (texto libre)")

        if st.button("Aplicar a toda la columna"):
            st.session_state.df[col_to_edit] = value
            st.success(f"Valor aplicado a la columna '{col_to_edit}'.")

###############################################################################
# Data editor / preview
###############################################################################

if not st.session_state.df.empty:
    st.subheader("📑 Preview & edición de la tabla")
    st.session_state.df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        key="data_editor",
    )

###############################################################################
# Save / download Excel
###############################################################################

if not st.session_state.df.empty:
    st.subheader("💾 Guardar / Descargar Excel")

    col_dt, col_btn = st.columns([2, 1])

    with col_dt:
        dt_input = st.datetime_input("Fecha y hora inicial", value=datetime.now())

    with col_btn:
        if st.button("Generar Excel"):
            # Generate time‑related columns
            df_final = generate_time_columns(st.session_state.df, dt_input)

            # Validate required columns
            missing_cols = [c for c in REQUIRED_COLUMNS if c in df_final.columns and df_final[c].isna().any()]
            if missing_cols:
                st.error(
                    "No se puede generar Excel. Faltan datos en las columnas:\n" + "\n".join(missing_cols)
                )
            else:
                xlsx_bytes = df_to_excel_bytes(df_final)
                file_name = f"datos_{dt_input.strftime('%d-%m-%Y-%H-%M')}.xlsx"
                st.download_button(
                    label="Descargar Excel procesado",
                    data=xlsx_bytes,
                    file_name=file_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                st.success("Excel generado. ¡Descarga lista!")

###############################################################################
# Footer
###############################################################################

st.markdown("---")
st.caption("Versión Streamlit. Adaptado por ChatGPT · Junio 2025")
