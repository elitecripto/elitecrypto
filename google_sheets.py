# google_sheets.py  ─ versión que soporta GOOGLE_CREDS_JSON
import os
import tempfile
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ---------- Config vía variables de entorno ----------
SCOPE        = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
CREDS_FILE   = os.getenv("GOOGLE_CREDS_FILENAME", "credenciales_google.json")
CREDS_JSON   = os.getenv("GOOGLE_CREDS_JSON")          # ← tu JSON completo
SHEET_NAME   = os.getenv("GOOGLE_SHEETS_NAME", "EstadoOperaciones")

# ---------- Si existe GOOGLE_CREDS_JSON, crear archivo temp ----------
def _ensure_creds_file():
    global CREDS_FILE
    if CREDS_JSON:                       # hay JSON en variable de entorno
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tmp.write(CREDS_JSON.encode())   # guardar contenido
        tmp.close()
        CREDS_FILE = tmp.name            # usar esa ruta para auth

_ensure_creds_file()

# ---------- Helpers de conexión ----------
def conectar_hoja():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1

def cargar_estado_desde_google():
    sheet = conectar_hoja()
    data = sheet.get_all_records()
    precios_entrada, fechas_entrada = {}, {}
    for row in data:
        precios_entrada[row["asset"]] = float(row["entry_price"]) if row["entry_price"] else None
        fechas_entrada[row["asset"]]  = row["entry_date"]  if row["entry_date"]  else None
    return precios_entrada, fechas_entrada

def guardar_estado_en_google(precios_entrada, fechas_entrada):
    sheet = conectar_hoja()
    sheet.clear()
    sheet.append_row(["asset", "entry_price", "entry_date"])
    for asset in precios_entrada:
        sheet.append_row([
            asset,
            precios_entrada.get(asset, ""),
            fechas_entrada.get(asset,  ""),
        ])
