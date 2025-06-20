"""
Streamlit – Potential Work Orders Tool
(única carga de CSV, mapa + tabla en pestañas, utilidades completas)
"""
from __future__ import annotations

import io, os
from datetime import datetime, timedelta, date, time
from typing import Dict, List

import pandas as pd
import streamlit as st
import configparser
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

# ───────────────────────────── Config helpers ──────────────────────────────
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


def load_config(path="config.ini"):
    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    cfg.read(path)

    prot_cols = [c.strip() for c in _safe_get(cfg, "PROTECTED_COLUMNS", "columns").split(",") if c]
    dd_values: Dict[str, List[str]] = {}
    if cfg.has_section("DROPDOWN_VALUES"):
        for k in cfg["DROPDOWN_VALUES"]:
            dd_values[k] = [x.strip() for x in cfg.get("DROPDOWN_VALUES", k).split(",")]

    pc_map: Dict[str, List[str]] = {}
    if cfg.has_section("PARENT_CHILD_RELATIONS"):
        for p in cfg["PARENT_CHILD_RELATIONS"]:
            pc_map[p] = [x.strip() for x in cfg.get("PARENT_CHILD_RELATIONS", p).split(",")]

    return (
        prot_cols,
        dd_values,
        [c.strip() for c in _safe_get(cfg, "REQUIRED_COLUMNS", "columns").split(",") if c],
        _safe_get(cfg, "GENERAL", "base_save_path", "output"),
        pc_map,
        _safe_get(cfg, "GENERAL", "excel_autoload_path", ""),
        _safe_get(cfg, "GENERAL", "excel_template_path", "test.xlsx"),
    )


# ───────────────────────────── Inicialización ──────────────────────────────
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

# ───────────────────── 1) Subir los dos CSV (lado a lado) ───────────────────
c1, c2 = st.columns(2)
with c1:
    geo_file = st.file_uploader("📍 Georadar CSV", type="csv")
with c2:
    cov_file = st.file_uploader("📶 Coverage CSV", type="csv")

# ───────────────────── 2) Procesar CSVs una sola vez ────────────────────────
if geo_file and cov_file and "processed" not in st.session_state:
    # ---------- Georadar ----------
    geo_df = pd.read_csv(geo_file)
    if not {"Latitud", "Longitud"}.issubset(geo_df.columns):
        st.error("Georadar CSV debe incluir columnas 'Latitud' y 'Longitud'.")
        st.stop()

    st.session_state.geo_df = geo_df.copy()
    gdf = geo_df.rename(
        columns={"Latitud": "Latitude - Functional Location", "Longitud": "Longitude - Functional Location"}
    )
    gdf["Service Account - Work Order"] = "ANER_Senegal"
    gdf["Billing Account - Work Order"] = "ANER_Senegal"
    gdf["Work Order Type - Work Order"] = "Installation"
    st.session_state.df = gdf

    # ---------- Cobertura ----------
    cov_df = pd.read_csv(cov_file)
    if not {"Latitud", "Longitud", "RSSI / RSCP (dBm)"}.issubset(cov_df.columns):
        st.error("Coverage CSV debe incluir Latitud, Longitud, RSSI / RSCP (dBm).")
        st.stop()

    st.session_state.cov_df = cov_df.copy()

    # unir dBm / Gateway
    gdf["LatBin"] = gdf["Latitude - Functional Location"].round(10)
    gdf["LonBin"] = gdf["Longitude - Functional Location"].round(10)
    cov_df["LatBin"] = cov_df["Latitud"].round(10)
    cov_df["LonBin"] = cov_df["Longitud"].round(10)
    cov_map = cov_df.set_index(["LatBin", "LonBin"])["RSSI / RSCP (dBm)"].to_dict()
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

    st.session_state.processed = True
    st.success("✅ Archivos cargados y procesados.")

# ───────────────────── 3) Mostrar mapa + tabla en pestañas ──────────────────
if "processed" in st.session_state:
    geo = st.session_state.geo_df
    cov = st.session_state.cov_df
    work_df = st.session_state.df

    tab_mapa, tab_tabla = st.tabs(["🌍 Mapa", "📑 Tabla editable"])

    # -------- MAPA ----------
    with tab_mapa:
        fmap = folium.Map(
            location=[geo["Latitud"].mean(), geo["Longitud"].mean()],
            zoom_start=12
        )
        # luminarias
        MarkerCluster().add_to(fmap)
        for _, r in geo.iterrows():
            folium.Marker([r.Latitud, r.Longitud], icon=folium.Icon(color="blue")).add_to(fmap)

        # cobertura agrupada
        cov = cov.copy()
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

        st_folium(fmap, width=1050, height=520)

    # -------- TABLA + utilidades ----------
    with tab_tabla:
        # preparar columnas plantilla
        tmpl_cols = load_excel_template_columns(EXCEL_TEMPLATE_PATH)
        disp_df = work_df.copy()
        for c in tmpl_cols:
            if c not in disp_df.columns:
                disp_df[c] = ""
        disp_df = disp_df[tmpl_cols]

        if "edited_df" not in st.session_state:
            st.session_state.edited_df = disp_df.copy()

        edited = st.data_editor(
            st.session_state.edited_df,
            num_rows="dynamic",
            use_container_width=True,
            key="editor",
        )

        if st.button("✅ Aplicar cambios"):
            st.session_state.edited_df = edited.copy()
            st.success("Datos guardados en memoria.")

        # ───── Bulk-add bloque ─────
        st.markdown("### 🧩 Añadir datos en bloque")
        with st.expander("➕ Añadir valor a toda una columna"):
            editable_cols = [c for c in edited.columns if c not in PROTECTED_COLUMNS]
            col_sel = st.selectbox("Columna", editable_cols)

            if col_sel == "Name - Child Functional Location":
                parent_vals = edited["Name - Parent Functional Location"].dropna().unique()
                par = parent_vals[0] if len(parent_vals) else None
                if par and par in PARENT_CHILD_MAP:
                    val = st.selectbox("Valor hijo", PARENT_CHILD_MAP[par])
                else:
                    st.warning("Define primero un 'Parent Functional Location'.")
                    val = ""
            elif col_sel in DROPDOWN_VALUES:
                val = st.selectbox("Valor", DROPDOWN_VALUES[col_sel])
            else:
                val = st.text_input("Valor")

            if st.button("📌 Aplicar a columna"):
                if col_sel and val:
                    st.session_state.edited_df[col_sel] = val
                    st.success("Valor aplicado.")
                    st.rerun()

        # ───── Autocompletar fechas/horas ─────
        st.markdown("### ⏱️ Autocompletar fechas/horas")
        with st.expander("Rellenar columnas temporales"):
            d_ini = st.date_input("Fecha inicial", value=date.today())
            t_ini = st.time_input("Hora inicial", value=datetime.now().time().replace(second=0, microsecond=0))
            if st.button("🕒 Generar incrementos de 27 min"):
                start_dt = datetime.combine(d_ini, t_ini)
                incs = [start_dt + timedelta(minutes=27 * i) for i in range(len(st.session_state.edited_df))]
                full_cols = [
                    "Promised window From - Work Order",
                    "Promised window To - Work Order",
                    "StartTime - Bookable Resource Booking",
                    "EndTime - Bookable Resource Booking",
                ]
                time_cols = [
                    "Time window From - Work Order",
                    "Time window To - Work Order",
                ]
                for c in full_cols:
                    if c in st.session_state.edited_df.columns:
                        st.session_state.edited_df[c] = incs
                for c in time_cols:
                    if c in st.session_state.edited_df.columns:
                        st.session_state.edited_df[c] = [d.time().strftime("%H:%M:%S") for d in incs]
                st.success("Columnas temporales rellenadas.")
                st.rerun()

        # ───── Descargar Excel ─────
        st.markdown("### 💾 Descargar Excel")
        if st.button("Generar y descargar"):
            df_out = st.session_state.edited_df.copy()
            # asegurar columnas plantilla
            for c in tmpl_cols:
                if c not in df_out.columns:
                    df_out[c] = ""
            df_out = df_out[tmpl_cols]

            out = io.BytesIO()
            with pd.ExcelWriter(out, engine="openpyxl") as w:
                df_out.to_excel(w, index=False)
            out.seek(0)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                "⬇️ Descargar Excel",
                data=out,
                file_name=f"workorders_{ts}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

else:
    st.info("🔼 Sube **ambos** CSV para generar mapa y tabla.")

# ───────────
st.caption("Desarrollado en Streamlit • Última actualización: 2025-06-17")
