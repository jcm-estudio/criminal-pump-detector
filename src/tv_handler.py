"""
Módulo para procesar señales externas provenientes de TradingView (Pine Script).
"""

import logging
from datetime import datetime, timezone
from src import database as db
import src.paper_trader as paper_trader
from src.alert_bot import send_trade_alert
from src.config import PAPER_TRADING
# Si se activa el trading real, se importará src.real_trader
# import src.real_trader as real_trader

logger = logging.getLogger(__name__)

def process_tv_signal(action, symbol):
    """
    Recibe una acción ('BUY' o 'SELL') y un símbolo ('ETHUSDT') desde el webhook.
    """
    logger.info(f"🎯 Señal TradingView recibida: {action} {symbol}")
    
    db.init_db()
    
    # Asegurar que el token existe en la DB
    token = db.get_token_by_symbol(symbol)
    if not token:
        logger.error(f"❌ Token {symbol} no encontrado en la base de datos.")
        # Opcional: Podríamos hacer fetch a MEXC e insertarlo, pero si no tiene volumen 
        # previo es riesgoso operarlo. Por seguridad, lo rechazamos.
        return False
        
    token_id = token["id"]
    
    # Actualizar el precio actual rápidamente para tener el entry/exit price correcto
    from src.data_collector import fetch_klines
    klines = fetch_klines(symbol, interval="1m", limit=1)
    if klines:
        current_price = klines[-1]["close"]
        now = datetime.now(timezone.utc).isoformat()
        with db.get_db() as conn:
            conn.execute(
                "INSERT INTO price_data (token_id, timestamp, price, volume_24h) VALUES (?, ?, ?, ?)",
                (token_id, now, current_price, 0) # Volumen 0 porque solo nos importa el precio para la ejecución rápida
            )
    else:
        logger.error(f"❌ No se pudo obtener el precio actual para {symbol}")
        return False

    if action.upper() == "BUY":
        # Inyectar una señal ficticia en la DB con la regla TradingView
        with db.get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO signals (token_id, level, total_score, individual_scores, triggered_rules, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (token_id, "CRITICO", 100.0, '{"TradingView": 100.0}', '["TradingView_Sniper"]', datetime.now(timezone.utc).isoformat())
            )
            signal_id = cursor.lastrowid
            
        signal_data = {
            "signal_id": signal_id,
            "token_id": token_id,
            "symbol": symbol,
            "level": "CRITICO"
        }
        
        if PAPER_TRADING:
            opened = paper_trader.process_new_signals([signal_data])
            if opened:
                send_trade_alert(opened[0], is_open=True, strategy="TRADINGVIEW")
                logger.info(f"✅ Trade de TradingView ABIERTO: {symbol}")
                return True
        else:
            # Implementación futura para Real Trader
            pass
            
    elif action.upper() == "SELL":
        if PAPER_TRADING:
            closed_trade = paper_trader.force_close_trade(token_id, exit_reason="TV_SELL")
            if closed_trade:
                send_trade_alert(closed_trade, is_open=False, strategy="TRADINGVIEW")
                logger.info(f"✅ Trade de TradingView CERRADO: {symbol}")
                return True
            else:
                logger.warning(f"⚠️ Se recibió SELL de TV para {symbol} pero no había trade abierto.")
        else:
            # Implementación futura para Real Trader
            pass
            
    else:
        logger.error(f"❌ Acción desconocida: {action}")
        
    return False
