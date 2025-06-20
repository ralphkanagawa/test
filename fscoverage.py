# -------------------------------------------------------------------------
# Data editor (granular editing)
# -------------------------------------------------------------------------

if "editor_refresh_count" not in st.session_state:
    st.session_state.editor_refresh_count = 0

if st.session_state.df.empty:
    st.info("Upload a CSV to start.")
else:
    st.subheader("📑 View and table edition")

    # Cargar columnas desde la plantilla Excel
    template_columns = load_excel_template_columns(EXCEL_TEMPLATE_PATH)
    df = st.session_state.df.copy()

    # Añadir columnas faltantes y reordenar según la plantilla
    for col in template_columns:
        if col not in df.columns:
            df[col] = ""

    df = df[template_columns]

    # Inicializar editable solo una vez (si no existe o se ha vaciado)
    if "edited_df" not in st.session_state or st.session_state.edited_df.empty:
        st.session_state.edited_df = df.copy()

    # Refrescar editor con clave dinámica
    result_df = st.data_editor(
        st.session_state.edited_df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"editor_{st.session_state.editor_refresh_count}"  # ⚡ clave cambia al modificar en bloque
    )

    # Botón para aplicar cambios manuales
    if st.button("✅ Apply changes to the table"):
        st.session_state.df = result_df.copy()
        st.session_state.edited_df = result_df.copy()
        st.success("Changes applied.")

    # -------------------------------------------------------------------------
    # Autocompletar fechas y horas en columnas temporales
    # -------------------------------------------------------------------------
    with st.expander("⏱️ Autocompletar fechas y horas en columnas temporales"):
        date_ref = st.date_input("Fecha inicial", value=date.today(), key="seq_date_start")
        time_ref = st.time_input("Hora inicial", value=datetime.now().time().replace(second=0, microsecond=0), key="seq_time_start")

        if st.button("🕒 Rellenar columnas con incrementos de 27 min"):
            start_dt = datetime.combine(date_ref, time_ref)
            increments = [start_dt + timedelta(minutes=27 * i) for i in range(len(st.session_state.edited_df))]

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
                if col in st.session_state.edited_df.columns:
                    st.session_state.edited_df[col] = increments
            for col in time_only_cols:
                if col in st.session_state.edited_df.columns:
                    st.session_state.edited_df[col] = [d.time().strftime("%H:%M:%S") for d in increments]

            st.success("Fechas y horas rellenadas en la tabla.")
            st.rerun()

    # -------------------------------------------------------------------------
    # Añadir datos en bloque a una columna
    # -------------------------------------------------------------------------
    st.subheader("🧩 Añadir datos en bloque")

    with st.expander("➕ Añadir un valor a toda una columna"):
        if "edited_df" not in st.session_state or st.session_state.edited_df.empty:
            st.warning("La tabla aún no ha sido cargada.")
        else:
            editable_columns = [col for col in st.session_state.edited_df.columns if col not in PROTECTED_COLUMNS]

            selected_column = st.selectbox("Selecciona columna:", editable_columns, key="block_col_selector")

            # Lógica especial si es columna hijo
            if selected_column == "Name - Child Functional Location":
                # Buscar valor padre en el DataFrame
                if "Name - Parent Functional Location" in st.session_state.edited_df.columns:
                    parent_vals = st.session_state.edited_df["Name - Parent Functional Location"].dropna().unique()
                    parent_val = parent_vals[0] if len(parent_vals) > 0 else None

                    if parent_val and parent_val in PARENT_CHILD_MAP:
                        children = PARENT_CHILD_MAP[parent_val]
                        value_to_apply = st.selectbox(
                            f"Selecciona valor hijo para '{parent_val}':",
                            children,
                            key="block_child_value"
                        )
                    else:
                        st.warning("No se ha detectado un valor válido para el campo padre.")
                        value_to_apply = ""
                else:
                    st.warning("La columna 'Name - Parent Functional Location' no existe.")
                    value_to_apply = ""
            elif selected_column in DROPDOWN_VALUES:
                value_to_apply = st.selectbox("Selecciona valor a aplicar:", DROPDOWN_VALUES[selected_column], key="block_value_selector")
            else:
                value_to_apply = st.text_input("Escribe el valor a aplicar:", key="block_value_input")

            if st.button("📌 Aplicar valor a columna"):
                if selected_column and value_to_apply:
                    st.session_state.edited_df[selected_column] = value_to_apply
                    st.success(f"Se aplicó '{value_to_apply}' a la columna '{selected_column}'.")
                    st.rerun()
                else:
                    st.error("Debes seleccionar una columna y un valor válidos.")

    # ---------------------------------------------------------------------
    # Guardar / descargar Excel
    # ---------------------------------------------------------------------
    st.subheader("💾 Save / Download Excel")
    col_date, col_time = st.columns(2)
    with col_date:
        date_input: date = st.date_input("Fecha inicial", value=date.today(), key="start_date")
    with col_time:
        time_input: time = st.time_input("Hora inicial", value=datetime.now().time().replace(second=0, microsecond=0), key="start_time")

    if st.button("Generar y descargar Excel", key="save_excel"):
        df_to_save = result_df.copy()
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

            # 👉 Insertar aquí el uso de la plantilla
            template_columns = load_excel_template_columns(EXCEL_TEMPLATE_PATH)
            df_to_save = st.session_state.edited_df.copy()

            for col in template_columns:
                if col not in df_to_save.columns:
                    df_to_save[col] = ""

            df_to_save = df_to_save[template_columns]

            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                df_to_save.to_excel(writer, index=False)

            out.seek(0)
            timestamp = start_dt.strftime("%Y%m%d_%H%M%S")
            file_name = f"datos_{timestamp}.xlsx"
            st.download_button("⬇️ Descargar Excel", data=out, file_name=file_name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
