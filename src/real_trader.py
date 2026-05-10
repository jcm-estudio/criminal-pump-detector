"""
Motor de Trading Real.
Conecta con la API privada de MEXC para ejecutar operaciones reales.
"""

import hmac
import hashlib
import time
import requests
import logging
from urllib.parse import urlencode

from src.config import (
    MEXC_API_KEY, MEXC_API_SECRET, MEXC_BASE_URL,
    MAX_TRADE_USD
)
from src.alert_bot import format_trade_alert, send_trade_alert

logger = logging.getLogger(__name__)

# ============================================================
# AUTENTICACIÓN MEXC (HMAC SHA256)
# ============================================================

def _generate_signature(query_string):
    """Genera la firma HMAC SHA256 requerida por MEXC para endpoints privados."""
    if not MEXC_API_SECRET:
        logger.error("❌ MEXC_API_SECRET no configurado.")
        return ""
        
    return hmac.new(
        MEXC_API_SECRET.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def _private_request(method, endpoint, params=None):
    """Envía una petición autenticada a MEXC."""
    if not MEXC_API_KEY or not MEXC_API_SECRET:
        logger.error("❌ Credenciales de MEXC faltantes. Abortando trading real.")
        return None
        
    if params is None:
        params = {}
        
    # Añadir timestamp (obligatorio)
    params['timestamp'] = int(time.time() * 1000)
    
    # Construir query string y firmar
    query_string = urlencode(params)
    signature = _generate_signature(query_string)
    
    # Añadir firma a la URL
    url = f"{MEXC_BASE_URL}{endpoint}?{query_string}&signature={signature}"
    
    headers = {
        "X-MEXC-APIKEY": MEXC_API_KEY,
        "Content-Type": "application/json"
    }
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, timeout=10)
        else:
            return None
            
        response.raise_for_status()
        return response.json()
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error en API MEXC: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Respuesta MEXC: {e.response.text}")
        return None


# ============================================================
# FUNCIONES DE CUENTA Y ÓRDENES
# ============================================================

def get_account_balance(asset="USDT"):
    """Obtiene el balance disponible de un activo específico."""
    res = _private_request("GET", "/api/v3/account")
    if not res or 'balances' not in res:
        return 0.0
        
    for balance in res['balances']:
        if balance['asset'] == asset:
            return float(balance['free'])
            
    return 0.0


def place_market_order(symbol, side, quote_order_qty=None, quantity=None):
    """
    Envía una orden de mercado a MEXC.
    - side: 'BUY' o 'SELL'
    - quote_order_qty: Cantidad a gastar en USDT (solo para BUY)
    - quantity: Cantidad de tokens a vender (solo para SELL)
    """
    params = {
        "symbol": symbol,
        "side": side.upper(),
        "type": "MARKET"
    }
    
    if quote_order_qty:
        params["quoteOrderQty"] = quote_order_qty
    elif quantity:
        params["quantity"] = quantity
    else:
        logger.error("Debe especificar quote_order_qty (compras) o quantity (ventas)")
        return None
        
    logger.info(f"🚀 Enviando orden REAL: {side} {symbol}")
    res = _private_request("POST", "/api/v3/order", params)
    
    if res and 'orderId' in res:
        logger.info(f"✅ ORDEN REAL EJECUTADA: ID {res['orderId']}")
        return res
    return None


# ============================================================
# INTERFAZ PÚBLICA (Similar a paper_trader)
# ============================================================

def process_new_signals(signals):
    """
    Evalúa señales nuevas y ABRE trades REALES si hay fondos.
    (La base de datos de 'paper_trades' se puede reutilizar para traquear
    internamente los trades reales activos, o podemos crear una tabla 'real_trades'.
    Por simplicidad usaremos logs y alertas por ahora, ya que MEXC es la fuente de verdad).
    """
    if not signals:
        return []

    opened_trades = []
    
    for signal in signals:
        if signal["level"] not in ["CRITICO", "ALTO"]:
            continue
            
        symbol = signal["symbol"]
        logger.warning(f"🚨 TRADING REAL INICIADO para {symbol}")
        
        # 1. Verificar balance
        usdt_balance = get_account_balance("USDT")
        if usdt_balance < MAX_TRADE_USD:
            logger.error(f"❌ Fondos insuficientes para {symbol}. Tienes ${usdt_balance:.2f}, necesitas ${MAX_TRADE_USD}.")
            continue
            
        # 2. Ejecutar compra
        order_res = place_market_order(
            symbol=symbol,
            side="BUY",
            quote_order_qty=MAX_TRADE_USD
        )
        
        if order_res:
            # Enviar alerta a Telegram de la compra real
            # (Asumimos que fill price es aprox el actual para la notificación)
            trade_data = {
                "symbol": symbol,
                "entry_price": 0, # En mercado el precio de llenado varía
                "amount_usd": MAX_TRADE_USD
            }
            msg = format_trade_alert(trade_data, is_open=True)
            msg = msg.replace("PAPER TRADE", "TRADE REAL (MEXC)")
            send_trade_alert(trade_data, is_open=True)
            opened_trades.append(order_res)
            
    return opened_trades


def update_open_trades():
    """
    Para el trading real, lo ideal es usar órdenes OCO (One Cancels the Other)
    o limit orders directo en el exchange para el SL y TP.
    Si se gestiona internamente, hay que guardar el quantity comprado y monitorear el precio.
    
    Por ahora, se deja como una estructura vacía que debería leer la base de datos
    de 'real_trades' y llamar a place_market_order(symbol, "SELL", quantity=...)
    si el precio actual toca el TP/SL.
    """
    # TODO: Implementar seguimiento y cierre de trades reales
    pass
