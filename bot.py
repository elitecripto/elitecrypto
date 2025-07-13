from flask import Flask, request
import requests
import os
from datetime import datetime
import threading
import time

# Importar funciones de Google Sheets
from google_sheets import registrar_entrada, registrar_salida, conectar_hoja

app = Flask(__name__)

# ------------------------------------------------------------------------------
# 1. CONFIGURACIONES ESENCIALES
# ------------------------------------------------------------------------------
BOT_TOKEN_ELITE = "7494590590:AAGjQU9vkmCaPfI-vIfly-PfHrEme27v4XE"

# IDs de grupo y canal (ES / EN)
GROUP_CHAT_ID_ES   = "-1002437381292"
CHANNEL_CHAT_ID_ES = "-1002440626725"
GROUP_CHAT_ID_EN   = "-1002432864193"
CHANNEL_CHAT_ID_EN = "-1002288256984"

TOPICS_ES = {"BTC":2,"ETH":4,"ADA":5,"XRP":6,"BNB":7}
TOPICS_EN = {"BTC":5,"ETH":7,"ADA":13,"XRP":11,"BNB":9}

WORDPRESS_ENDPOINT      = "hhttps://cryptosignalbot.com/wp-json/dashboard/v1/recibir-senales-fire"
WORDPRESS_ENDPOINT_ALT  = "https://cryptosignalbot.com/wp-json/dashboard/v1/ver-historial-fire"

TELEGRAM_KEY   = "Bossio.18357009"
APALANCAMIENTO = 3

# -------------------------------------------------------------------
# 2. WEBHOOK
# -------------------------------------------------------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    return process_signal(request.json or {})

# -------------------------------------------------------------------
# 3. LÓGICA PRINCIPAL
# -------------------------------------------------------------------
def process_signal(data):
    ticker      = data.get('ticker','').upper()
    action      = data.get('order_action','').lower()
    raw_price   = data.get('order_price',"")
    order_price = str(raw_price).replace(',','.')

    if not order_price:
        return "Precio no proporcionado", 400

    asset_es, topic_es = identificar_activo_es(ticker)
    asset_en, topic_en = identificar_activo_en(ticker)
    if not asset_es:
        return "Activo no reconocido", 400

    fecha_hoy = datetime.now().strftime("%d/%m/%Y")

    # --- BUY ---
    if action == "buy":
        registrar_entrada(ticker, float(order_price))

        stop_loss  = round(float(order_price) * 0.80, 4)
        msg_es     = construir_mensaje_compra_es(asset_es, order_price, stop_loss, fecha_hoy)
        msg_en     = build_buy_message_en      (asset_en, order_price, stop_loss, fecha_hoy)

        send_telegram_group_message_with_button_es(GROUP_CHAT_ID_ES, topic_es, msg_es)
        send_telegram_group_message_with_button_en(GROUP_CHAT_ID_EN, topic_en, msg_en)

        payload = {
            "telegram_key": TELEGRAM_KEY,
            "symbol":     asset_es,
            "action":     action,
            "price":      order_price,
            "stop_loss":  stop_loss,
            "strategy":   "fire_scalping"
        }
        enviar_a_wordpress(WORDPRESS_ENDPOINT,     payload)
        enviar_a_wordpress(WORDPRESS_ENDPOINT_ALT, payload)

        return "OK", 200

    # --- SELL/CLOSE ---
    if action in ("sell","close"):
        # 1) Recuperar la última entrada abierta
        sheet   = conectar_hoja()
        records = sheet.get_all_records(value_render_option='UNFORMATTED_VALUE')

        entry_price = None
        entry_date  = None
        for row in reversed(records):
            if row["activo"] == ticker and row["precio_salida"] == "":
                entry_price = float(str(row["precio_entrada"]).replace(',','.'))
                entry_date  = row["fecha_hora_entrada"]
                break
        if entry_price is None:
            return "No hay posición abierta", 400

        # 2) Registrar salida en Google Sheets (esto calculará stop_programada y profit_pct allí)
        registrar_salida(ticker, float(order_price))

        # 3) Calcular P&L en el bot (misma lógica: raw_pct × APALANCAMIENTO)
        exit_price      = float(order_price)
        raw_pct         = (exit_price - entry_price) / entry_price * 100
        profit_leverage = round(raw_pct * APALANCAMIENTO, 2)

        # 4) Construir y enviar mensajes
        msg_es = construir_mensaje_cierre_es(asset_es, entry_price, exit_price,
                                             profit_leverage, entry_date, fecha_hoy)
        msg_en = build_close_message_en(  asset_en, entry_price, exit_price,
                                          profit_leverage, entry_date, fecha_hoy)

        send_telegram_group_message_with_button_es(GROUP_CHAT_ID_ES,   topic_es, msg_es)
        send_telegram_group_message_with_button_en(GROUP_CHAT_ID_EN,   topic_en, msg_en)

        # 5) Si ganancia, publicar en canal
        if profit_leverage >= 0:
            ch_es = construir_mensaje_ganancia_canal_es(asset_es, entry_price,
                                                        exit_price, profit_leverage,
                                                        entry_date, fecha_hoy)
            ch_en = build_profit_channel_msg_en(asset_en, entry_price,
                                                exit_price, profit_leverage,
                                                entry_date, fecha_hoy)
            send_telegram_channel_message_with_button_es(CHANNEL_CHAT_ID_ES, ch_es)
            send_telegram_channel_message_with_button_en(CHANNEL_CHAT_ID_EN, ch_en)

        # 6) Enviar payload de cierre a WordPress
        payload = {
            "telegram_key": TELEGRAM_KEY,
            "symbol":       asset_es,
            "action":       action,
            "entry_price":  entry_price,
            "stop_loss":    round(entry_price * 0.80, 4),
            "price":        order_price,
            "strategy":     "elite_scalping_pro",
            "result":       profit_leverage  # será –60 cuando raw –20
        }
        enviar_a_wordpress(WORDPRESS_ENDPOINT,     payload)
        enviar_a_wordpress(WORDPRESS_ENDPOINT_ALT, payload)

        return "OK", 200

    return "OK", 200

# -------------------------------------------------------------------
# 4. KEEP-ALIVE para Render (ping cada 5m)
# -------------------------------------------------------------------
def _keep_alive():
    url = os.getenv("KEEPALIVE_URL", "https://elitecrypto.onrender.com/ping")
    while True:
        try:
            r = requests.get(url, timeout=10)
            print(f"[KEEPALIVE] {r.status_code} → {url}")
        except Exception as e:
            print(f"[KEEPALIVE] Error: {e}")
        time.sleep(300)

# -------------------------------------------------------------------
# 5. FUNCIONES MENSAJES (ESPAÑOL)
# -------------------------------------------------------------------
def construir_mensaje_compra_es(asset, order_price, stop_loss, fecha_hoy):
    return (
        f"🟢 **ABRIR LONG | ZONA CONFIRMADA**\n\n"
        f"🚨 **Estrategia: 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
        f"📈 **Operacion: Long**\n"
        f"💰 **Activo:** {asset}/USDT\n"
        f"✅ **Entrada:** {order_price} USDT\n"
        f"⚖️ **Apalancamiento:** {APALANCAMIENTO}x\n"
        f"⛔ **Stop Loss:** {stop_loss} USDT\n"
        f"📅 **Fecha:** {fecha_hoy}\n"
        f"🎯 **Take Profit:** **Señal generada en tiempo real**\n\n"
        f"🎯 **El Take Profit se activa cuando se detecta un punto óptimo de salida.** "
        f"Nuestro equipo de analistas monitorea el mercado en **tiempo real**, aplicando "
        f"análisis técnico y fundamental para identificar las mejores oportunidades. "
        f"Recibirás un mensaje con todos los detalles cuando la operación deba ser cerrada.\n\n"
        f"⏳ **Estado:** EN CURSO, esperando señal de cierre...\n\n"
    )

def construir_mensaje_cierre_es(asset, precio_entrada, precio_salida,
                                profit_leveraged, fecha_entrada, fecha_cierre):
    if profit_leveraged >= 0:
        resultado_str = f"🟢 +{profit_leveraged:.2f}%"
        return (
            f"🎯 **TARGET ALCANZADO | CERRAR TOMAR GANANCIAS** 🔴\n\n"
            f"🚨 **Estrategia: 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
            f"📈 **Operacion: Long**\n"
            f"💰 **Activo:** {asset}/USDT\n"
            f"✅ **Entrada:** {precio_entrada} USDT\n"
            f"🔒 **Cierre:** {precio_salida} USDT\n"
            f"⚖️ **Apalancamiento:** {APALANCAMIENTO}x\n"
            f"📅 **Apertura:** {fecha_entrada}\n"
            f"📅 **Cierre:** {fecha_cierre}\n"
            f"📊 **Resultado:** {resultado_str}\n\n"
            f"📡 **Estrategia 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 – Operación Cerrada**\n"
            f"¡Felicidades! Hemos cerrado la operación con beneficios.\n\n"
            f"⏳ **Estado:** Operación finalizada."
        )
    else:
        resultado_str = f"🔴 {profit_leveraged:.2f}%"
        return (
            f"🛑 **🔻 STOP LOSS ACTIVADO | CERRAR EN PÉRDIDA**\n\n"
            f"🚨 **Estrategia: 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
            f"📈 **Operacion: Long**\n"
            f"💰 **Activo:** {asset}/USDT\n"
            f"✅ **Entrada:** {precio_entrada} USDT\n"
            f"🔒 **Cierre:** {precio_salida} USDT\n"
            f"⚖️ **Apalancamiento:** {APALANCAMIENTO}x\n"
            f"📅 **Apertura:** {fecha_entrada}\n"
            f"📅 **Cierre:** {fecha_cierre}\n"
            f"📊 **Resultado:** {resultado_str}\n\n"
            f"📡 **Estrategia 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 – Gestión de Riesgo**\n"
            f"El mercado tomó una dirección inesperada, pero aplicamos nuestra gestión "
            f"de riesgo para minimizar pérdidas.\n\n"
            f"⏳ **Estado:** Operación finalizada."
        )
    return msg

def construir_mensaje_ganancia_canal_es(asset, precio_entrada, precio_salida,
                                        profit_leveraged, fecha_entrada, fecha_cierre):
    return (
        f"🚀 **TARGET ALCANZADO | ¡Otra operación cerrada con éxito! 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n\n"
        f"🚨 **Estrategia: 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
        f"💰 **Activo:** {asset}/USDT\n"
        f"✅ **Entrada:** {precio_entrada} USDT\n"
        f"🔒 **Cierre:** {precio_salida} USDT\n"
        f"📊 **Resultado:** 🟢 +{profit_leveraged:.2f}%\n\n"
        f"📡 **Estrategia 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
        f"Nuestro sistema Elite Scalping Pro detectó el momento óptimo para cerrar la operación y asegurar "
        f"**beneficios en esta oportunidad de mercado**. Si quieres recibir nuestras señales VIP de "
        f"la estrategia 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 en **tiempo real**, suscríbete y accede a Señales, "
        f"**gráficos en vivo, rendimiento detallado y la lista de operaciones cerradas**.\n\n"
        f"💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 – Prueba Gratuita por 15 Días🎉\n"
        f"📊 Señales, gráficos en vivo y análisis en tiempo real completamente GRATIS por 15 días.\n\n"
        f"🔑 ¡Obten tu Prueba Gratuita! 🚀\n"
    )

# -------------------------------------------------------------------
# 6. FUNCIONES MENSAJES (INGLÉS)
# -------------------------------------------------------------------
def build_buy_message_en(asset, order_price, stop_loss, fecha_hoy):
    return (
        f"🟢 **OPEN POSITION** 🟢\n\n"
        f"🚨 **Strategy: 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
        f"📈 **Operation: Long**\n"
        f"💰 **Asset:** {asset}/USDT\n"
        f"✅ **Price:** {order_price} USDT\n"
        f"⚖️ **Leverage:** {APALANCAMIENTO}x\n"
        f"⛔ **Stop Loss:** {stop_loss} USDT\n"
        f"📅 **Date:** {fecha_hoy}\n"
        f"🎯 **Take Profit:** **Real-time generated signal**\n\n"
        f"🎯 **The Take Profit is triggered when an optimal exit point is detected.** Our team of analysts "
        f"monitors the market in **real-time**, applying technical and fundamental analysis to identify "
        f"the best opportunities. You will receive a message with all the details when the trade needs to be closed.\n\n"
        f"⏳ **Status:** IN PROGRESS, waiting for a closing signal...\n\n"
    )

def build_close_message_en(asset, entry_price, exit_price,
                           profit_leveraged, entry_date, close_date):
    if profit_leveraged >= 0:
        result_str = f"🟢 +{profit_leveraged:.2f}%"
        msg = (
            f"🔴 **CLOSE POSITION** 🔴\n\n"
            f"🚨 **Strategy: 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
            f"📈 **Operation: Long**\n"
            f"💰 **Asset:** {asset}/USDT\n"
            f"✅ **Entry:** {entry_price} USDT\n"
            f"🔒 **Exit:** {exit_price} USDT\n"
            f"⚖️ **Leverage:** {APALANCAMIENTO}x\n"
            f"📅 **Opened:** {entry_date}\n"
            f"📅 **Closed:** {close_date}\n"
            f"📊 **Result:** {result_str}\n\n"
            f"📡 **💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 Strategy – Trade Closed**\n"
            f"Congratulations! We have successfully closed the trade with profits.\n\n"
            f"⏳ **Status:** Trade finalized."
        )
    else:
        result_str = f"🔴 {profit_leveraged:.2f}%"
        msg = (
            f"🔴 **CLOSE POSITION** 🔴\n\n"
            f"🚨 **Strategy: 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
            f"📈 **Operation: Long**\n"
            f"💰 **Asset:** {asset}/USDT\n"
            f"✅ **Entry:** {entry_price} USDT\n"
            f"🔒 **Exit:** {exit_price} USDT\n"
            f"⚖️ **Leverage:** {APALANCAMIENTO}x\n"
            f"📅 **Opened:** {entry_date}\n"
            f"📅 **Closed:** {close_date}\n"
            f"📊 **Result:** {result_str}\n\n"
            f"📡 **💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 Strategy – Risk Management**\n"
            f"The market took an unexpected turn, but we applied our risk management strategy to minimize losses.\n\n"
            f"⏳ **Status:** Trade finalized."
        )
    return msg

def build_profit_channel_msg_en(asset, entry_price, exit_price,
                                profit_leveraged, entry_date, close_date):
    return (
		f"🚀 **TARGET HIT | Another successful trade closed! 💎 𝐄𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n\n"
		f"🚨 **Strategy: 💎 𝐄𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
		f"💰 **Asset:** {asset}/USDT\n"
		f"✅ **Entry:** {entry_price} USDT\n"
		f"📉 **Exit:** {exit_price} USDT\n"
		f"🔒 **Leverage:** {APALANCAMIENTO}x\n"
		f"📅 **Opened:** {entry_date}\n"
		f"📅 **Closed:** {close_date}\n"
		f"📊 **Result:** 🟢 +{profit_leveraged:.2f}%\n\n"
		f"📡 We work hard analyzing 5 high-volume cryptocurrencies: "
		f"Bitcoin (BTC), ETH, BNB, ADA, and XRP.\n"
		f"Our system runs on a robust platform with our own website, "
		f"automated interface, real-time signals and 24/7 support.\n\n"
		f"💎 We show verified results, "
		f"all of our signals include a full 1-year trade history "
		f"and are backed by real stats and public verification on the website.\n\n"
		f"---\n"
		f"🎁 Join our Premium Zone and access VIP signals with real and verified results.\n"
		f"📌 *The data shown is from Bitcoin (1-year full history), but applying this strategy across 5 cryptocurrencies, results can be up to 5x greater.*\n\n"
		f"• Real-time signals sent to our website and Telegram\n"
		f"• Public trade history (12 full months)\n"
		f"• Live charting platform with multi-timeframe analysis\n"
		f"• Economic calendar and daily market news\n"
		f"• 24/7 support for any questions or setup help\n\n"
		f"---\n"
		f"💎 𝐄𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 – FREE 🎉\n"
		f"📊 Real-time signals, live charts and full market analysis completely FREE for 15 days.\n\n"
		f"🔑 Claim your FREE for 15 days now! 🚀\n"
	)

# -------------------------------------------------------------------
# 7. FUNCIONES DE ENVÍO A TELEGRAM
# -------------------------------------------------------------------
def send_telegram_group_message_with_button_es(chat_id, thread_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_ELITE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [{"text":"📊 Ver gráficos en vivo","url":"https://cryptosignalbot.com/senales-elite-scalping-intradia-criptomonedas/"}]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'message_thread_id': thread_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    requests.post(url, json=payload)

def send_telegram_channel_message_with_button_es(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_ELITE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [{"text":"🎁 Señales VIP","url":"https://t.me/CriptoSignalBotGestion_bot"}]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    requests.post(url, json=payload)

def send_telegram_group_message_with_button_en(chat_id, thread_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_ELITE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [{"text":"📊 View live charts","url":"https://cryptosignalbot.com/senales-elite-scalping-intradia-criptomonedas/"}]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'message_thread_id': thread_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    requests.post(url, json=payload)

def send_telegram_channel_message_with_button_en(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_ELITE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [{"text":"🎁 VIP Signals","url":"https://t.me/CriptoSignalBotGestion_bot"}]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    requests.post(url, json=payload)

# -------------------------------------------------------------------
# 8. UTILIDADES
# -------------------------------------------------------------------
def enviar_a_wordpress(endpoint, payload):
    try:
        requests.post(endpoint, json=payload)
    except:
        pass

def identificar_activo_es(ticker):
    t = ticker.upper()
    if "BTC" in t: return ("BTC", TOPICS_ES["BTC"])
    if "ETH" in t: return ("ETH", TOPICS_ES["ETH"])
    if "ADA" in t: return ("ADA", TOPICS_ES["ADA"])
    if "XRP" in t: return ("XRP", TOPICS_ES["XRP"])
    if "BNB" in t: return ("BNB", TOPICS_ES["BNB"])
    return (None, None)

def identificar_activo_en(ticker):
    t = ticker.upper()
    if "BTC" in t: return ("BTC", TOPICS_EN["BTC"])
    if "ETH" in t: return ("ETH", TOPICS_EN["ETH"])
    if "ADA" in t: return ("ADA", TOPICS_EN["ADA"])
    if "XRP" in t: return ("XRP", TOPICS_EN["XRP"])
    if "BNB" in t: return ("BNB", TOPICS_EN["BNB"])
    return (None, None)

# -------------------------------------------------------------------
# 9. ARRANQUE
# -------------------------------------------------------------------
@app.route('/ping', methods=['GET'])
def ping():
    return 'pong', 200

if __name__ == '__main__':
    threading.Thread(target=_keep_alive, daemon=True).start()
    port = int(os.environ.get("PORT", 1000))
    app.run(host='0.0.0.0', port=port)
