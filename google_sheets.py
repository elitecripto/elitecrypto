# google_sheets.py – acceso a Google Sheets
# • Variable GOOGLE_CREDS_JSON (JSON completo)  ← recomendado
# • o archivo credenciales_google.json en disco
# Si falta cualquiera de las dos, lanza un error claro.

import os, tempfile, gspread
from oauth2client.service_account import ServiceAccountCredentials

# ---------- Config desde entorno ----------
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

CREDS_FILE  = os.getenv("GOOGLE_CREDS_FILENAME", "credenciales_google.json")
CREDS_JSON  = os.getenv("GOOGLE_CREDS_JSON")        # JSON completo
SHEET_NAME  = os.getenv("GOOGLE_SHEETS_NAME", "EstadoOperaciones")

# ---------- Credenciales -------------------
def _ensure_creds_file() -> str:
    # 1) JSON en variable de entorno
    if CREDS_JSON:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tmp.write(CREDS_JSON.encode())
        tmp.close()
        return tmp.name
    # 2) Archivo físico en imagen
    if os.path.exists(CREDS_FILE):
        return CREDS_FILE
    # 3) Ninguna fuente disponible
    raise FileNotFoundError(
        "❌ Credenciales de Google Sheets no encontradas.\n"
        "• Sube credenciales_google.json o crea GOOGLE_CREDS_JSON."
    )

CREDS_PATH = _ensure_creds_file()

# ---------- Conexión ------------------------
def conectar_hoja():
    creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, SCOPE)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1           # primera pestaña

# ---------- Cargar estado --------------------
def cargar_estado_desde_google():
    hoja = conectar_hoja()
    data = hoja.get_all_records()
    precios, fechas = {}, {}
    for row in data:
        precios[row["asset"]] = float(row["entry_price"]) if row["entry_price"] else None
        fechas[row["asset"]]  = row["entry_date"]         if row["entry_date"]  else None
    return precios, fechas

# ---------- Guardar estado -------------------
def guardar_estado_en_google(precios, fechas):
    sheet = conectar_hoja()

    # 1. Asegurar cabecera
    if sheet.row_count == 0 or sheet.cell(1, 1).value != "asset":
        sheet.update("A1:C1", [["asset", "entry_price", "entry_date"]])

    # 2. Índice actual (asset → fila)
    records = sheet.get_all_records()                    # list[dict]
    index_by_asset = {row["asset"]: idx + 2 for idx, row in enumerate(records)}
    # (+2 porque fila 1 = cabecera)

    for asset in precios:
        precio = precios[asset]
        fecha  = fechas[asset]
        fila   = index_by_asset.get(asset)

        # A) Cerrar posición → borrar fila si existe
        if precio is None:
            if fila:
                sheet.delete_rows(fila)
            continue

        # B) Actualizar fila existente
        if fila:
            sheet.update(f"A{fila}:C{fila}", [[asset, precio, fecha]])
        # C) Fila nueva
        else:
            sheet.append_row([asset, precio, fecha])
