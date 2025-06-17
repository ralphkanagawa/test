import pandas as pd
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import filedialog, messagebox
import os
from datetime import datetime, timedelta
import configparser
import folium
import webview

#Carga datos .ini
def load_config(path="config.ini"):
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(path)

    protected_columns = [col.strip() for col in config.get("PROTECTED_COLUMNS", "columns").split(",")]
    base_save_path = config.get("GENERAL", "base_save_path")
    excel_autoload_path = config.get("GENERAL", "excel_autoload_path", fallback="")

    dropdown_values = {}
    for key in config["DROPDOWN_VALUES"]:
        dropdown_values[key] = [item.strip() for item in config.get("DROPDOWN_VALUES", key).split(",")]

    required_columns = [col.strip() for col in config.get("REQUIRED_COLUMNS", "columns").split(",")]

    parent_child_map = {}
    if "PARENT_CHILD_RELATIONS" in config:
        for parent in config["PARENT_CHILD_RELATIONS"]:
            parent_child_map[parent] = [x.strip() for x in config.get("PARENT_CHILD_RELATIONS", parent).split(",")]

    return protected_columns, dropdown_values, required_columns, base_save_path, parent_child_map, excel_autoload_path

#Clase para agrupar toda la app
class ExcelEditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Potential Work Orders Management Application")
        self.root.geometry("1000x600")

        self.df = pd.DataFrame()
        self.create_widgets()
        self.protected_columns, self.dropdown_values, self.required_columns, self.base_path, self.parent_child_map, self.excel_autoload_path = load_config()

        if os.path.isfile(self.excel_autoload_path):
            try:
                self.df = pd.read_excel(self.excel_autoload_path)
                self.update_table()
                self.btn_add_granular.config(state=NORMAL)
                self.btn_save_excel.config(state=NORMAL)
                self.btn_add_block.config(state=NORMAL)
            except Exception as e:
                messagebox.showerror("Error", f"Error loading initial Excel file:\n{e}")

    def create_widgets(self):
        self.style = ttk.Style()
        self.style.theme_use("darkly")

        frame_buttons = ttk.Frame(self.root, padding=10)
        frame_buttons.pack(fill="x")

        self.btn_load_georadar = ttk.Button(frame_buttons, text="Georadar CSV load", command=self.load_csv, bootstyle=SECONDARY)
        self.btn_load_georadar.pack(side="left", padx=5)

        self.btn_load_coverage = ttk.Button(frame_buttons, text="Coverage CSV load", command=self.load_coverage_csv, bootstyle=SECONDARY)
        self.btn_load_coverage.pack(side="left", padx=5)

        self.btn_add_granular = ttk.Button(frame_buttons, text="Add granular data", command=self.edit_selected_rows, bootstyle=SUCCESS, state=DISABLED)
        self.btn_add_granular.pack(side="left", padx=5)

        self.btn_add_block = ttk.Button(frame_buttons, text="Add block data", command=self.add_block_data, bootstyle=SUCCESS, state=DISABLED)
        self.btn_add_block.pack(side="left", padx=5)

        self.btn_save_excel = ttk.Button(frame_buttons, text="Save Excel", command=self.save_excel, bootstyle=INFO, state=DISABLED)
        self.btn_save_excel.pack(side="left", padx=5)

        self.datetime_label = ttk.Label(frame_buttons, text="", bootstyle=INFO)
        self.datetime_label.pack(side="left", padx=10)
        self.update_datetime_label()

        frame_table = ttk.Labelframe(self.root, text="Excel preview", bootstyle=INFO)
        frame_table.pack(fill="both", expand=True, padx=10, pady=5)

        self.tree = ttk.Treeview(frame_table, bootstyle=INFO)
        self.tree.pack(expand=True, fill="both", padx=5, pady=5)

        scrollbar = ttk.Scrollbar(frame_table, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

    def update_datetime_label(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.datetime_label.config(text=f"{now}")
        self.root.after(1000, self.update_datetime_label)


    #Para actualizar la vista
    def update_table(self):
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = list(self.df.columns)
        self.tree["show"] = "headings"
        
        for col in self.df.columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)
        
        for _, row in self.df.iterrows():
            self.tree.insert("", "end", values=list(row))

    def load_csv(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if not file_path:
            return

        csv_data = pd.read_csv(file_path)

        if "Latitud" in csv_data.columns and "Longitud" in csv_data.columns:
            self.df["Latitude - Functional Location"] = csv_data["Latitud"]
            self.df["Longitude - Functional Location"] = csv_data["Longitud"]

            self.df["Service Account - Work Order"] = "ANER_Senegal"
            self.df["Billing Account - Work Order"] = "ANER_Senegal"
            self.df["Work Order Type - Work Order"] = "Installation"

            self.update_table()
            messagebox.showinfo("Success", "Latitude and Longitude successfully added.")
        else:
            messagebox.showerror("Error", "CSV file must contain 'Latitud' and 'Longitud' columns.")

    def load_coverage_csv(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if not file_path:
            return

        try:
            df_cov = pd.read_csv(file_path)
            if not all(col in df_cov.columns for col in ["Latitud", "Longitud", "RSSI / RSCP (dBm)"]):
                messagebox.showerror("Error", "CSV must include 'Latitud', 'Longitud', and 'RSSI / RSCP (dBm)' columns.")
                return

            self.df["LatBin"] = self.df["Latitude - Functional Location"].round(10)
            self.df["LonBin"] = self.df["Longitude - Functional Location"].round(10)
            df_cov["LatBin"] = df_cov["Latitud"].round(10)
            df_cov["LonBin"] = df_cov["Longitud"].round(10)

            coverage_map = df_cov.set_index(["LatBin", "LonBin"])["RSSI / RSCP (dBm)"].to_dict()

            def apply_coverage(row):
                key = (row["LatBin"], row["LonBin"])
                return coverage_map.get(key, None)

            self.df["dBm"] = self.df.apply(apply_coverage, axis=1)

            def classify_gateway(rssi):
                if pd.isna(rssi):
                    return None
                elif -70 <= rssi <= -10:
                    return "YES"
                elif -200 <= rssi < -70:
                    return "NO"
                return None

            self.df["Gateway"] = self.df["dBm"].apply(classify_gateway)
            self.df.drop(columns=["LatBin", "LonBin"], inplace=True)

            self.update_table()
            messagebox.showinfo("Success", "Coverage data matched and applied.")

        except Exception as e:
            messagebox.showerror("Error", f"Error processing coverage CSV:\n{str(e)}")

    #Añadir datos en bloque en una misma columna
    def add_block_data(self):
        def apply_block_data():
            selected_column = col_var.get()
            value = value_input.get()

            if selected_column in self.dropdown_values and value not in self.dropdown_values[selected_column]:
                messagebox.showerror("Error", f"Select a valid option for '{selected_column}'.")
                return

            if selected_column and value:
                self.df[selected_column] = value
                block_window.destroy()
                self.update_table()
            else:
                messagebox.showerror("Error", "You must select a valid column and data.")
        
        block_window = ttk.Toplevel(self.root)
        block_window.title("Add data by column")
        block_window.geometry("300x200")
        
        col_var = ttk.StringVar()
        ttk.Label(block_window, text="Select column:").pack(pady=5)
        col_dropdown = ttk.Combobox(block_window,textvariable=col_var,values=[col for col in self.df.columns if col not in self.protected_columns])
        col_dropdown.pack(pady=5)
        
        ttk.Label(block_window, text="Add value to apply:").pack(pady=5)
        value_input = None

        def update_input_field(event=None):
            selected = col_var.get()
            for widget in input_frame.winfo_children():
                widget.destroy()

            nonlocal value_input

            if selected == "Name - Child Functional Location":
                # Necesitamos mostrar un Combobox dependiente del Parent
                value_input = ttk.Combobox(input_frame)

                # Mostrar dropdown vacío por ahora, actualizarlo si el Parent está disponible
                parent_column = "Name - Parent Functional Location"
                if parent_column in self.df.columns:
                    unique_parents = self.df[parent_column].dropna().unique()
                    if len(unique_parents) == 1:
                        parent_value = unique_parents[0]
                        children = self.parent_child_map.get(parent_value, [])
                        value_input["values"] = children
                        if children:
                            value_input.set(children[0])
                    else:
                        messagebox.showwarning(
                            "Warning",
                            "In order to apply data to a child, be sure that all rows has the same parent value."
                        )
            elif selected in self.dropdown_values:
                value_input = ttk.Combobox(input_frame, values=self.dropdown_values[selected])
            else:
                value_input = ttk.Entry(input_frame)

            value_input.pack()

        input_frame = ttk.Frame(block_window)
        input_frame.pack(pady=5)
        col_dropdown.bind("<<ComboboxSelected>>", update_input_field)

        btn_apply = ttk.Button(block_window, text="Apply", command=apply_block_data, bootstyle=SUCCESS)
        btn_apply.pack(pady=10)
    
    #Añadir datos por seleccion de filas
    def edit_selected_rows(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "Select at least one row to edit.")
            return
        
        #Función para guardar los cambios en la ventana de datos granulados
        def save_changes():
            for row_idx, item in enumerate(selected_items):
                df_index = self.tree.index(item)
                entry_idx = 0
                for col in self.df.columns:
                    if col in self.protected_columns:
                        continue
                    new_value = entries[entry_idx].get()
                    if new_value.strip():
                        self.df.at[df_index, col] = new_value
                    entry_idx += 1
            
            edit_window.destroy()
            self.update_table()
        
        edit_window = ttk.Toplevel(self.root)
        edit_window.title("Add data by row")
        edit_window.geometry("700x500")
        
        canvas = ttk.Canvas(edit_window)
        scrollbar = ttk.Scrollbar(edit_window, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        #Para hacer scroll con la rueda del ratón
        def on_mouse_wheel(event):
            if event.num == 5 or event.delta < 0:  # Scroll abajo
                canvas.yview_scroll(1, "units")
            if event.num == 4 or event.delta > 0:  # Scroll arriba
                canvas.yview_scroll(-1, "units")

        # Asignar scroll con rueda del ratón en Windows y Mac/Linux
        canvas.bind_all("<MouseWheel>", on_mouse_wheel)  # Windows
        #canvas.bind_all("<Button-4>", on_mouse_wheel)  # Linux (scroll arriba)
        #canvas.bind_all("<Button-5>", on_mouse_wheel)  # Linux (scroll abajo)
        
        #Iteración de todo lo que se entra para datos granulados
        entries = []
        parent_entry = None
        child_entry = None

        for i, col in enumerate(self.df.columns):
            if col in self.protected_columns:
                continue

            ttk.Label(scrollable_frame, text=col).grid(row=i, column=0, padx=10, pady=5)

            if col == "Name - Parent Functional Location":
                combo = ttk.Combobox(scrollable_frame, values=self.dropdown_values[col])
                combo.grid(row=i, column=1, padx=10, pady=5)
                parent_entry = combo
                entries.append(combo)

            elif col == "Name - Child Functional Location":
                combo = ttk.Combobox(scrollable_frame)
                combo.grid(row=i, column=1, padx=10, pady=5)
                child_entry = combo
                entries.append(combo)

            elif col in self.dropdown_values:
                combo = ttk.Combobox(scrollable_frame, values=self.dropdown_values[col])
                combo.grid(row=i, column=1, padx=10, pady=5)
                entries.append(combo)

            else:
                entry = ttk.Entry(scrollable_frame)
                entry.grid(row=i, column=1, padx=10, pady=5)
                entries.append(entry)

        if parent_entry and child_entry:
            def update_child_options(event=None):
                parent_val = parent_entry.get()
                children = self.parent_child_map.get(parent_val, [])
                child_entry["values"] = children
                if children:
                    child_entry.set(children[0])  # Selecciona el primero por defecto

            parent_entry.bind("<<ComboboxSelected>>", update_child_options)

        btn_save_top = ttk.Button(scrollable_frame, text="Apply", command=save_changes, bootstyle=SUCCESS)
        btn_save_top.grid(row=0, column=2, padx=10, pady=5)
        
        btn_save_bottom = ttk.Button(scrollable_frame, text="Apply", command=save_changes, bootstyle=SUCCESS)
        btn_save_bottom.grid(row=len(self.df.columns), column=2, padx=10, pady=5)

    #Carga del CSV con la latitud y la longitud
    def load_csv(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if not file_path:
            return

        csv_data = pd.read_csv(file_path)

        if "Latitud" in csv_data.columns and "Longitud" in csv_data.columns:
            self.df["Latitude - Functional Location"] = csv_data["Latitud"]
            self.df["Longitude - Functional Location"] = csv_data["Longitud"]

            # 🔒 Agregar datos hardcodeados
            self.df["Service Account - Work Order"] = "ANER_Senegal"
            self.df["Billing Account - Work Order"] = "ANER_Senegal"
            self.df["Work Order Type - Work Order"] = "Installation"

            self.update_table()
            messagebox.showinfo("Success", "Latitude and Longitude successfully added.")
        else:
            messagebox.showerror("Error", "CSV file must contain 'Latitud' and 'Longitud' columns.")

    # Guardar el excel ya tratado con estructura Año/Mes
    def save_excel(self):
        def continue_saving(with_datetime):
            only_time = with_datetime.strftime("%H:%M:%S")

            # Generar lista de tiempos incrementados por fila
            increments = [with_datetime + timedelta(minutes=27 * i) for i in range(len(self.df))]

            # Columnas con datetime completo
            for col in [
                "Promised window From - Work Order",
                "Promised window To - Work Order",
                "StartTime - Bookable Resource Booking",
                "EndTime - Bookable Resource Booking"
            ]:
                if col in self.df.columns:
                    self.df[col] = increments

            # Columnas con solo hora
            for col in [
                "Time window From - Work Order",
                "Time window To - Work Order"
            ]:
                if col in self.df.columns:
                    self.df[col] = [dt.time().strftime("%H:%M:%S") for dt in increments]

            # Validación de columnas requeridas
            required_columns = [
                "Name - Parent Functional Location",
                "Service Account - Work Order",
                "Work Order Type - Work Order",
                "Incident Type - Work Order",
                "Owner - Work Order",
                "Promised window From - Work Order",
                "Promised window To - Work Order",
                "Time window From - Work Order",
                "Time window To - Work Order",
                "Billing account - Work Order",
                "Name - Bookable Resource Booking",
                "StartTime - Bookable Resource Booking",
                "EndTime - Bookable Resource Booking"
            ]

            missing_data = []
            for col in required_columns:
                if col in self.df.columns and self.df[col].isnull().any():
                    missing_data.append(col)

            if missing_data:
                cols_str = "\n".join(missing_data)
                messagebox.showerror(
                    "Error: Missing data",
                    f"Can't save the file.\nMissing data in the following columns:\n\n{cols_str}"
                )
                return

            # Guardar el archivo
            timestamp = with_datetime.strftime("%d-%m-%Y-%H-%M")
            year = with_datetime.strftime("%Y")
            month = with_datetime.strftime("%m")
            save_dir = os.path.join(self.base_path, year, month)
            os.makedirs(save_dir, exist_ok=True)

            file_name = f"datos_{timestamp}.xlsx"
            file_path = os.path.join(save_dir, file_name)

            try:
                self.df.to_excel(file_path, index=False)
                messagebox.showinfo("Success", f"File saved in:\n{file_path}")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        def ask_for_datetime():
            now = datetime.now()

            confirm_window = ttk.Toplevel(self.root)
            confirm_window.title("Confirm Date & Time")
            confirm_window.geometry("400x250")

            ttk.Label(confirm_window, text="Date and time detected:").pack(pady=10)
            ttk.Label(confirm_window, text=now.strftime("%Y-%m-%d %H:%M:%S"), font=("Helvetica", 12, "bold")).pack()

            ttk.Label(confirm_window, text="Do you want to use this date and time?").pack(pady=10)

            def use_current():
                confirm_window.destroy()
                continue_saving(now)

            def manual_entry():
                for widget in confirm_window.winfo_children():
                    widget.destroy()

                ttk.Label(confirm_window, text="Add date and time manually: (YYYY-MM-DD HH:MM:SS)").pack(pady=10)
                entry = ttk.Entry(confirm_window, width=30)
                entry.pack(pady=5)
                entry.insert(0, now.strftime("%Y-%m-%d %H:%M:%S"))

                def submit_manual():
                    try:
                        user_dt = datetime.strptime(entry.get(), "%Y-%m-%d %H:%M:%S")
                        confirm_window.destroy()
                        continue_saving(user_dt)
                    except ValueError:
                        messagebox.showerror("Invalid format", "Use the correct format: YYYY-MM-DD HH:MM:SS")

                ttk.Button(confirm_window, text="Confirm", command=submit_manual, bootstyle=SUCCESS).pack(pady=10)

            ttk.Button(confirm_window, text="Use actual", command=use_current, bootstyle=PRIMARY).pack(pady=5)
            ttk.Button(confirm_window, text="Add manually", command=manual_entry, bootstyle=SECONDARY).pack(pady=5)

        # Inicia el proceso preguntando por la fecha/hora
        ask_for_datetime()

if __name__ == "__main__":
    root = ttk.Window(themename="superhero")
    app = ExcelEditorApp(root)
    root.mainloop()
