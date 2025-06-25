# google_sheets.py – versión robusta (evita cabeceras duplicadas)
import os, tempfile, gspread
from oauth2client.service_account import ServiceAccountCredentials

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

CREDS_FILE = os.getenv("GOOGLE_CREDS_FILENAME", "credenciales_google.json")
CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SHEET_NAME = os.getenv("GOOGLE_SHEETS_NAME", "EstadoOperaciones")

# ---------- credenciales ----------
def _ensure_creds_file() -> str:
    if CREDS_JSON:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tmp.write(CREDS_JSON.encode())
        tmp.close()
        return tmp.name
    if os.path.exists(CREDS_FILE):
        return CREDS_FILE
    raise FileNotFoundError(
        "❌ Credenciales de Google Sheets no encontradas.\n"
        "• Sube credenciales_google.json o crea GOOGLE_CREDS_JSON."
    )

CREDS_PATH = _ensure_creds_file()


# ---------- helpers ----------
def conectar_hoja():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, SCOPE)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1


EXPECTED = ["asset", "entry_price", "entry_date"]  # cabeceras oficiales


def _asegurar_header(sheet):
    """ Garantiza que la fila 1 tenga solo las cabeceras oficiales. """
    header = sheet.row_values(1)
    if header != EXPECTED:
        # Borra fila 1 completa y escribe cabeceras correctas
        sheet.delete_rows(1)
        sheet.insert_row(EXPECTED, 1)


# ---------- cargar estado ----------
def cargar_estado_desde_google():
    hoja = conectar_hoja()
    _asegurar_header(hoja)

    data = hoja.get_all_records(expected_headers=EXPECTED)
    precios, fechas = {}, {}
    for row in data:
        precios[row["asset"]] = (
            float(row["entry_price"]) if row["entry_price"] else None
        )
        fechas[row["asset"]] = row["entry_date"] or None
    return precios, fechas


# ---------- guardar estado ----------
def guardar_estado_en_google(precios, fechas):
    hoja = conectar_hoja()
    _asegurar_header(hoja)

    # lee filas existentes evitando error de duplicados
    records = hoja.get_all_records(expected_headers=EXPECTED)
    index = {row["asset"]: i + 2 for i, row in enumerate(records)}  # fila real

    for asset in precios:
        precio, fecha = precios[asset], fechas[asset]
        fila = index.get(asset)

        if precio is None:
            # cierre de posición: elimina fila si existe
            if fila:
                hoja.delete_rows(fila)
            continue

        if fila:
            hoja.update(f"A{fila}:C{fila}", [[asset, precio, fecha]])
        else:
            hoja.append_row([asset, precio, fecha])
