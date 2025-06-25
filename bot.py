# bot_elite.py – persistencia en Google Sheets + keep-alive
# --------------------------------------------------------
from flask import Flask, request
from datetime import datetime
import requests, os, threading, time

# ------------- Google Sheets -------------
from google_sheets import (
    cargar_estado_desde_google,
    guardar_estado_en_google,
)

precios_entrada, fechas_entrada = cargar_estado_desde_google()

def guardar_estado():
    guardar_estado_en_google(precios_entrada, fechas_entrada)

# ------------- Config básica -------------
app = Flask(__name__)

BOT_TOKEN_ELITE  = "7494590590:AAGjQU9vkmCaPfI-vIfly-PfHrEme27v4XE"

GROUP_CHAT_ID_ES = "-1002437381292"
CHANNEL_CHAT_ID_ES = "-1002440626725"

GROUP_CHAT_ID_EN = "-1002432864193"
CHANNEL_CHAT_ID_EN = "-1002288256984"

TOPICS_ES = {"BTC": 2, "ETH": 4, "ADA": 5, "XRP": 6, "BNB": 7}
TOPICS_EN = {"BTC": 5, "ETH": 7, "ADA": 13, "XRP": 11, "BNB": 9}

WORDPRESS_ENDPOINT      = "https://cryptosignalbot.com/wp-json/dashboard/v1/recibir-senales-intradia"
WORDPRESS_ENDPOINT_ALT  = "https://cryptosignalbot.com/wp-json/dashboard/v1/ver-historial-intradia"

TELEGRAM_KEY   = "Bossio.18357009"
APALANCAMIENTO = 3

# ------------- Rutas Flask ---------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print(f"[DEBUG] Datos recibidos: {data}")
    return process_signal(data)

@app.route("/ping", endpoint="ping2", methods=["GET"])
def ping():
    return "pong", 200

# ---------- Keep-alive 5 min -------------
def _keep_alive():
    url = os.getenv("KEEPALIVE_URL", "https://delta-f42n.onrender.com/ping")
    while True:
        try:
            requests.get(url, timeout=10)
            print(f"[KEEPALIVE] Ping OK → {url}")
        except Exception as e:
            print(f"[KEEPALIVE] Error: {e}")
        time.sleep(300)  # 5 min

# ---------- Lógica principal -------------
def process_signal(data):
    global precios_entrada, fechas_entrada

    ticker      = data.get("ticker", "No especificado")
    action      = data.get("order_action", "").lower()   # buy / sell / close
    order_price = data.get("order_price")

    if order_price is None:
        return "Precio no proporcionado", 400

    asset_es, topic_es = identificar_activo_es(ticker)
    asset_en, topic_en = identificar_activo_en(ticker)
    if not asset_es or not asset_en:
        return "Activo no reconocido", 400

    fecha_hoy = datetime.now().strftime("%d/%m/%Y")

    # ----------- BUY ----------
    if action == "buy":
        # evita duplicados
        if precios_entrada.get(asset_es) is not None:
            print(f"[DEBUG] Ya hay operación abierta en {asset_es}")
            return "Duplicada", 200

        stop_loss = round(float(order_price) * 0.80, 4)
        precios_entrada[asset_es] = float(order_price)
        fechas_entrada[asset_es]  = fecha_hoy
        guardar_estado()

        msg_es = construir_mensaje_compra_es(asset_es, order_price, stop_loss, fecha_hoy)
        msg_en = build_buy_message_en(asset_en, order_price, stop_loss, fecha_hoy)

        send_telegram_group_message_with_button_es(GROUP_CHAT_ID_ES, topic_es, msg_es)
        send_telegram_group_message_with_button_en(GROUP_CHAT_ID_EN, topic_en, msg_en)

        payload_wp = {
            "telegram_key": TELEGRAM_KEY,
            "symbol": asset_es,
            "action": action,
            "price": order_price,
            "stop_loss": stop_loss,
            "strategy": "elite_scalping_pro",
        }
        enviar_a_wordpress(WORDPRESS_ENDPOINT, payload_wp)
        enviar_a_wordpress(WORDPRESS_ENDPOINT_ALT, payload_wp)
        return "OK", 200

    # -------- SELL / CLOSE ---
    if action in ("sell", "close"):
        if precios_entrada.get(asset_es) is None:
            return "No hay posición abierta para cerrar", 400

        precio_entrada   = precios_entrada[asset_es]
        precio_salida    = float(order_price)
        fecha_entrada_op = fechas_entrada.get(asset_es, "Desconocida")

        profit_pct      = (precio_salida - precio_entrada) / precio_entrada * 100
        profit_leverage = profit_pct * APALANCAMIENTO

        msg_es = construir_mensaje_cierre_es(
            asset_es, precio_entrada, precio_salida,
            profit_leverage, fecha_entrada_op, fecha_hoy
        )
        msg_en = build_close_message_en(
            asset_en, precio_entrada, precio_salida,
            profit_leverage, fecha_entrada_op, fecha_hoy
        )

        send_telegram_group_message_with_button_es(GROUP_CHAT_ID_ES, topic_es, msg_es)
        send_telegram_group_message_with_button_en(GROUP_CHAT_ID_EN, topic_en, msg_en)

        # mensaje resumen a canal
        if profit_leverage >= 0:
            canal_es = construir_mensaje_ganancia_canal_es(
                asset_es, precio_entrada, precio_salida,
                profit_leverage, fecha_entrada_op, fecha_hoy
            )
            canal_en = build_profit_channel_msg_en(
                asset_en, precio_entrada, precio_salida,
                profit_leverage, fecha_entrada_op, fecha_hoy
            )
        else:
            canal_es = construir_mensaje_perdida_canal_es(
                asset_es, precio_entrada, precio_salida,
                profit_leverage, fecha_entrada_op, fecha_hoy
            )
            canal_en = build_loss_channel_msg_en(
                asset_en, precio_entrada, precio_salida,
                profit_leverage, fecha_entrada_op, fecha_hoy
            )

        send_telegram_channel_message_with_button_es(CHANNEL_CHAT_ID_ES, canal_es)
        send_telegram_channel_message_with_button_en(CHANNEL_CHAT_ID_EN, canal_en)

        # reset y guarda
        precios_entrada[asset_es] = None
        fechas_entrada[asset_es]  = None
        guardar_estado()

        payload_wp = {
            "telegram_key": TELEGRAM_KEY,
            "symbol": asset_es,
            "action": action,
            "price": order_price,
            "strategy": "elite_scalping_pro",
            "result": round(profit_leverage, 2),
        }
        enviar_a_wordpress(WORDPRESS_ENDPOINT, payload_wp)
        enviar_a_wordpress(WORDPRESS_ENDPOINT_ALT, payload_wp)
        return "OK", 200

    return "OK", 200

# ------------------------------------------------------------------------------
# 4. FUNCIONES MENSAJES (ESPAÑOL)
# ------------------------------------------------------------------------------
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
        msg = (
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
        msg = (
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
        f"🚀 **TARGET ALCANZADO | ¡Otra operación cerrada con éxito!**\n"
        f"💎 **𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 – 𝐏𝐫𝐞𝐜𝐢𝐬𝐢𝐨́𝐧 𝐲 𝐏𝐚𝐜𝐢𝐞𝐧𝐜𝐢𝐚 𝐞𝐧 𝐞𝐥 𝐌𝐞𝐫𝐜𝐚𝐝𝐨**\n\n"
        f"🚨 **Estrategia: 💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
        f"💰 **Activo:** {asset}/USDT\n"
        f"✅ **Entrada:** {precio_entrada} USDT\n"
        f"🔒 **Cierre:** {precio_salida} USDT\n"
        f"⚖️ **Apalancamiento:** {APALANCAMIENTO}x\n"
        f"📅 **Apertura:** {fecha_entrada}\n"
        f"📅 **Cierre:** {fecha_cierre}\n"
        f"📊 **Resultado:** 🟢 +{profit_leveraged:.2f}%\n\n"
        f"📡 Trabajamos arduamente analizando 𝟓 𝐜𝐫𝐢𝐩𝐭𝐨𝐦𝐨𝐧𝐞𝐝𝐚𝐬 de alto volumen: "
        f"𝐁𝐢𝐭𝐜𝐨𝐢𝐧 (𝐁𝐓𝐂), 𝐄𝐓𝐇, 𝐁𝐍𝐁, 𝐀𝐃𝐀 y 𝐗𝐑𝐏.\n"
        f"Todo el sistema funciona desde una plataforma robusta con sitio web propio, "
        f"interfaz automatizada, señales en vivo y soporte 24/7.\n\n"
        f"💎 Mostramos resultados verificados, "
        f"todas nuestras señales incluyen histórico completo de 𝟏 𝐚𝐧̃𝐨, "
        f"y están respaldadas por estadísticas reales y 𝐯𝐞𝐫𝐢𝐟𝐢𝐜𝐚𝐜𝐢𝐨́𝐧 𝐩𝐮́𝐛𝐥𝐢𝐜𝐚 𝐞𝐧 𝐞𝐥 𝐬𝐢𝐭𝐢𝐨 𝐰𝐞𝐛.\n\n"
        f"🌐 𝐀𝐜𝐜𝐞𝐬𝐨 𝐠𝐫𝐚𝐭𝐮𝐢𝐭𝐨 𝐝𝐞 𝟏 𝐦𝐞𝐬 – como los grandes (Disney, Netflix… nosotros también sabemos que es tan bueno que lo vas a querer pagar 😉)\n\n"
        f"💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 – 𝐏𝐫𝐞𝐜𝐢𝐬𝐢𝐨́𝐧 𝐲 𝐏𝐚𝐜𝐢𝐞𝐧𝐜𝐢𝐚 𝐞𝐧 𝐞𝐥 𝐌𝐞𝐫𝐜𝐚𝐝𝐨, 𝐫𝐞𝐬𝐮𝐥𝐭𝐚𝐝𝐨𝐬 𝐞𝐧 𝐁𝐢𝐭𝐜𝐨𝐢𝐧:\n"
        f"🏅 Rendimiento: 97.33%\n"
        f"🟢 Ganadoras: 182\n"
        f"🔴 Perdedoras: 5\n\n"
        f"---\n"
        f"🎁 𝐔́𝐧𝐞𝐭𝐞 𝐚 𝐧𝐮𝐞𝐬𝐭𝐫𝐚 𝐙𝐨𝐧𝐚 𝐏𝐫𝐞𝐦𝐢𝐮𝐦 𝐲 𝐚𝐜𝐜𝐞𝐝𝐞 𝐚 𝐬𝐞𝐧̃𝐚𝐥𝐞𝐬 𝐕𝐈𝐏 𝐜𝐨𝐧 𝐫𝐞𝐬𝐮𝐥𝐭𝐚𝐝𝐨𝐬 𝐫𝐞𝐚𝐥𝐞𝐬 𝐲 𝐜𝐨𝐦𝐩𝐫𝐨𝐛𝐚𝐝𝐨𝐬.\n"
        f"📌 *Los datos mostrados son solo de Bitcoin histórico completo de 𝟏 𝐚𝐧̃𝐨, pero aplicando la estrategia en 5 criptomonedas, los resultados pueden ser hasta 𝟓 𝐯𝐞𝐜𝐞𝐬 𝐦𝐚𝐲𝐨𝐫𝐞𝐬.*\n\n"
        f"🔥 𝐅𝐈𝐑𝐄 𝐒𝐜𝐚𝐥𝐩𝐢𝐧𝐠\n"
        f"🏅 Rendimiento: 78.74%\n"
        f"🟢 Ganadoras: 1,533\n"
        f"🔴 Perdedoras: 414\n\n"
        f"💎 𝐄𝐋𝐈𝐓𝐄 𝐒𝐜𝐚𝐥𝐩𝐢𝐧𝐠 𝐏𝐑𝐎\n"
        f"🏅 Rendimiento: 97.33%\n"
        f"🟢 Ganadoras: 182\n"
        f"🔴 Perdedoras: 5\n\n"
        f"🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠\n"
        f"🏅 Rendimiento: 90.48%\n"
        f"🟢 Ganadoras: 19\n"
        f"🔴 Perdedoras: 2\n\n"
        f"• Señales en tiempo real directo a nuestro sitio web y Telegram\n"
        f"• Historial público de todas las operaciones (12 meses completos)\n"
        f"• Plataforma con gráficos en vivo y análisis multitemporal\n"
        f"• Calendario económico y noticias relevantes\n"
        f"• Soporte 24/7 para cualquier duda o configuración\n\n"
        f"---\n"
        f"💎 𝐄́𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 – 𝐏𝐑𝐈𝐌𝐄𝐑 𝐌𝐄𝐒 𝐆𝐑𝐀𝐓𝐈𝐒 🎉\n"
        f"📊 Señales, gráficos en vivo y análisis en tiempo real completamente GRATIS por 30 días.\n\n"
        f"🔑 𝐎𝐛𝐭𝐞́𝐧 𝐭𝐮 𝐦𝐞𝐬 𝐠𝐫𝐚𝐭𝐢𝐬 𝐚𝐡𝐨𝐫𝐚! 🚀\n"    
    )

# ------------------------------------------------------------------------------
# 5. FUNCIONES MENSAJES (INGLÉS)
# ------------------------------------------------------------------------------
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
        f"🚀 **TARGET HIT | Another successful trade closed!**\n"
        f"💎 **𝐄𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 – Precision & Patience in the Market**\n\n"
        f"🚨 **Strategy: 💎 𝐄𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎**\n"
        f"💰 **Asset:** {asset}/USDT\n"
        f"✅ **Entry:** {entry_price} USDT\n"
        f"🔒 **Exit:** {exit_price} USDT\n"
        f"⚖️ **Leverage:** {APALANCAMIENTO}x\n"
        f"📅 **Opened:** {entry_date}\n"
        f"📅 **Closed:** {close_date}\n"
        f"📊 **Result:** 🟢 +{profit_leveraged:.2f}%\n\n"
        f"📡 We work hard analyzing 5 major cryptocurrencies with high volume: "
        f"𝐁𝐢𝐭𝐜𝐨𝐢𝐧 (𝐁𝐓𝐂), 𝐄𝐓𝐇, 𝐁𝐍𝐁, 𝐀𝐃𝐀, and 𝐗𝐑𝐏.\n"
        f"Our system is supported by a robust platform including a live website, "
        f"automated dashboard, real-time signals, and 24/7 support.\n\n"
        f"💎 The results shown below are from **𝐁𝐢𝐭𝐜𝐨𝐢𝐧** only, "
        f"but all strategies include a fully verified 1-year track record, "
        f"publicly accessible on our website.\n\n"
        f"🌐 Enjoy 30 days of full access — just like Disney or Netflix, "
        f"we’re confident you’ll want to stay after trying it 😉\n\n"
        f"💎 𝐄𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 – 𝐁𝐢𝐭𝐜𝐨𝐢𝐧 Results Example:\n"
        f"🏅 Return: 97.33%\n"
        f"🟢 Winning trades: 182\n"
        f"🔴 Losing trades: 5\n\n"
        f"---\n"
        f"🎁 Join our Premium Zone and access real VIP signals with verified performance.\n"
        f"📌 *The above results are from Bitcoin only (12-month track record). "
        f"When applied to all 5 assets, total performance can reach up to 𝟓𝐱.*\n\n"
        f"🔥 𝐅𝐈𝐑𝐄 𝐒𝐜𝐚𝐥𝐩𝐢𝐧𝐠\n"
        f"🏅 Return: 78.74%\n"
        f"🟢 Wins: 1,533\n"
        f"🔴 Losses: 414\n\n"
        f"💎 𝐄𝐋𝐈𝐓𝐄 𝐒𝐜𝐚𝐥𝐩𝐢𝐧𝐠 𝐏𝐑𝐎\n"
        f"🏅 Return: 97.33%\n"
        f"🟢 Wins: 182\n"
        f"🔴 Losses: 5\n\n"
        f"🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠\n"
        f"🏅 Return: 90.48%\n"
        f"🟢 Wins: 19\n"
        f"🔴 Losses: 2\n\n"
        f"• Real-time signals via website and Telegram\n"
        f"• Fully public trade history (12 months verified)\n"
        f"• Live charts and multi-timeframe technical analysis\n"
        f"• Daily macroeconomic news and calendar\n"
        f"• 24/7 support to help you succeed\n\n"
        f"---\n"
        f"💎 𝐄𝐋𝐈𝐓𝐄 𝐒𝐂𝐀𝐋𝐏𝐈𝐍𝐆 𝐏𝐑𝐎 – 𝐅𝐈𝐑𝐒𝐓 𝐌𝐎𝐍𝐓𝐇 𝐅𝐑𝐄𝐄 🎉\n"
        f"📊 Live signals, real-time charts, and expert analysis — 𝐅𝐑𝐄𝐄 𝐟𝐨𝐫 𝟑𝟎 𝐝𝐚𝐲𝐬.\n\n"
        f"🔑 𝐆𝐞𝐭 𝐲𝐨𝐮𝐫 𝐟𝐫𝐞𝐞 𝐦𝐨𝐧𝐭𝐡 𝐧𝐨𝐰! 🚀\n"
    )

# ------------------------------------------------------------------------------
# 6. FUNCIONES DE ENVÍO A TELEGRAM
# ------------------------------------------------------------------------------
def send_telegram_group_message_with_button_es(chat_id, thread_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_ELITE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [
                {
                    "text": "📊 Ver gráficos, señales en vivo",
                    "url": "https://cryptosignalbot.com/senales-elite-scalping-intradia-criptomonedas/"
                }
            ]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'message_thread_id': thread_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    resp = requests.post(url, json=payload)
    print(f"[DEBUG][ES] Grupo (con botón): {resp.json()}")

def send_telegram_channel_message_with_button_es(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_ELITE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [
                {
                    "text": "🎯 Señales VIP – 30D Gratis",
                    "url": "https://t.me/CriptoSignalBotGestion_bot?start=676731307b8344cb070ac996"
                }
            ]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    resp = requests.post(url, json=payload)
    print(f"[DEBUG][ES] Canal (con botón): {resp.json()}")

def send_telegram_group_message_with_button_en(chat_id, thread_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_ELITE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [
                {
                    "text": "📊 View charts & live signals",
                    "url": "https://cryptosignalbot.com/senales-elite-scalping-intradia-criptomonedas/"
                }
            ]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'message_thread_id': thread_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    resp = requests.post(url, json=payload)
    print(f"[DEBUG][EN] Group (with button): {resp.json()}")

def send_telegram_channel_message_with_button_en(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_ELITE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [
                {
                    "text": "🎯 VIP Signals – 30D FREE",
                    "url": "https://t.me/CriptoSignalBotGestion_bot?start=676731307b8344cb070ac996"
                }
            ]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    resp = requests.post(url, json=payload)
    print(f"[DEBUG][EN] Channel (with button): {resp.json()}")

# ------------------------------------------------------------------------------
# 7. FUNCIONES DE UTILIDAD
# ------------------------------------------------------------------------------
def enviar_a_wordpress(endpoint, payload):
    try:
        resp = requests.post(endpoint, json=payload)
        print(f"[DEBUG] WP resp ({endpoint}): {resp.text}")
    except Exception as e:
        print(f"[ERROR] Enviando a WordPress: {e}")

def identificar_activo_es(ticker):
    """
    Devuelve (asset, topic_id) según el ticker en español.
    """
    t = ticker.upper()
    if "BTC" in t:
        return ("BTC", TOPICS_ES["BTC"])
    elif "ETH" in t:
        return ("ETH", TOPICS_ES["ETH"])
    elif "ADA" in t:
        return ("ADA", TOPICS_ES["ADA"])
    elif "XRP" in t:
        return ("XRP", TOPICS_ES["XRP"])
    elif "BNB" in t:
        return ("BNB", TOPICS_ES["BNB"])
    else:
        return (None, None)

def identificar_activo_en(ticker):
    """
    Devuelve (asset, topic_id) según el ticker en inglés.
    """
    t = ticker.upper()
    if "BTC" in t:
        return ("BTC", TOPICS_EN["BTC"])
    elif "ETH" in t:
        return ("ETH", TOPICS_EN["ETH"])
    elif "ADA" in t:
        return ("ADA", TOPICS_EN["ADA"])
    elif "XRP" in t:
        return ("XRP", TOPICS_EN["XRP"])
    elif "BNB" in t:
        return ("BNB", TOPICS_EN["BNB"])
    else:
        return (None, None)

# ------------------------------------------------------------------
# 8. RUTA /PING PARA MANTENER EL SERVIDOR ACTIVO (CRON-JOB)
# ------------------------------------------------------------------
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200


# ------------------------------------------------------------------
# 9. EJECUCIÓN DEL SERVIDOR FLASK
# ------------------------------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 1000))
    app.run(host="0.0.0.0", port=port)
