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

# ... (todo el código anterior hasta la tabla se mantiene igual)

# ─────────────── Tabla editable + herramientas ───────────────
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
    t0 = st.time_input("Hora inicial", value=datetime.now().time().replace(second=0, microsecond=0))
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

# Descargar Excel
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
