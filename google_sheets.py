import os
import tempfile
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ------------- Configuración Google Sheets -------------
SCOPE       = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
CREDS_FILE  = os.getenv("GOOGLE_CREDS_FILENAME","credenciales_google.json")
CREDS_JSON  = os.getenv("GOOGLE_CREDS_JSON")
SHEET_NAME  = os.getenv("GOOGLE_SHEETS_NAME","RegistroOperaciones")

# MISMO APALANCAMIENTO: 3×
LEVERAGE    = 3

def _ensure_creds_file() -> str:
    if CREDS_JSON:
        tmp = tempfile.NamedTemporaryFile(delete=False,suffix=".json")
        tmp.write(CREDS_JSON.encode()); tmp.close()
        return tmp.name
    if os.path.exists(CREDS_FILE):
        return CREDS_FILE
    raise FileNotFoundError("No se encontraron credenciales de Google Sheets.")

CREDS_PATH = _ensure_creds_file()

def conectar_hoja():
    creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH,SCOPE)
    client = gspread.authorize(creds)
    sheet  = client.open(SHEET_NAME).sheet1

    header = [
        "activo",
        "precio_entrada",
        "fecha_hora_entrada",
        "precio_salida",
        "fecha_hora_salida",
        "stop_programada",
        "profit_pct"
    ]
    if sheet.row_count == 0 or sheet.row_values(1) != header:
        sheet.clear()
        sheet.append_row(header)
    return sheet

def registrar_entrada(activo: str, precio: float):
    sheet = conectar_hoja()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    fila  = [activo, precio, fecha, "", "", "", ""]
    sheet.append_row(fila)

def registrar_salida(activo: str, precio: float):
    sheet  = conectar_hoja()
    fecha  = datetime.now().strftime("%Y-%m-%d %H:%M")
    data   = sheet.get_all_records()

    for idx in range(len(data)-1, -1, -1):
        row = data[idx]
        if row["activo"] == activo and row["precio_salida"] == "":
            fila_num = idx + 2  # +2 por cabecera

            # 1) precio_salida y fecha
            sheet.update_cell(fila_num, 4, precio)
            sheet.update_cell(fila_num, 5, fecha)

            # 2) precio de entrada
            entry_price = float(str(sheet.cell(fila_num,2).value).replace(",", "."))

            # 3) stop_programada = entrada * 0.80 (–20%)
            stop_prog = round(entry_price * 0.80, 6)
            sheet.update_cell(fila_num, 6, stop_prog)

            # 4) profit_pct = raw_pct × LEVERAGE
            exit_price = float(str(precio).replace(",", "."))
            raw_pct    = (exit_price - entry_price) / entry_price * 100
            profit_pct = round(raw_pct * LEVERAGE, 2)
            sheet.update_cell(fila_num, 7, profit_pct)

            # 5) colorear fila
            color = {"backgroundColor": {"red":1, "green":0, "blue":0}} if profit_pct < 0 \
                 else {"backgroundColor": {"red":0, "green":1, "blue":0}}
            sheet.format(f"A{fila_num}:G{fila_num}", color)

            return

    raise ValueError(f"No hay operación abierta para '{activo}'.")
