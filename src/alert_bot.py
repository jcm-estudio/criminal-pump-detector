"""
Bot de alertas por Telegram para el Criminal Pump Detector.

Funciones:
- Envío de alertas formateadas cuando se detecta un pump
- Deduplicación de alertas (no repetir en 6h)
- Reporte diario de performance
- Comando /status para health check
"""

import json
import logging
import requests
from datetime import datetime, timezone

from src.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    ALERT_COOLDOWN_HOURS,
)
from src import database as db

logger = logging.getLogger(__name__)


# ============================================================
# ENVÍO DE MENSAJES (API directa, sin dependencia de librería)
# ============================================================

def _send_telegram_message(text, parse_mode="HTML"):
    """
    Envía un mensaje a Telegram usando la API REST directamente.
    Más simple que usar python-telegram-bot para alertas unidireccionales.
    
    Args:
        text: Texto del mensaje (soporta HTML)
        parse_mode: "HTML" o "Markdown"
    
    Returns:
        bool: True si se envió correctamente
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ Telegram no configurado (falta BOT_TOKEN o CHAT_ID)")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            logger.info("✅ Mensaje de Telegram enviado")
            return True
        else:
            logger.error(f"❌ Telegram API error: {result}")
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error enviando mensaje Telegram: {e}")
        return False


# ============================================================
# FORMATO DE ALERTAS
# ============================================================

def _level_emoji(level):
    """Retorna emoji según nivel de alerta."""
    return {
        "CRITICO": "🔴",
        "ALTO": "🟠",
        "MEDIO": "🟡",
    }.get(level, "⚪")


def _score_emoji(score):
    """Retorna emoji según score individual de una regla."""
    if score >= 80:
        return "🔥"
    elif score >= 60:
        return "⚡"
    elif score >= 40:
        return "📊"
    elif score > 0:
        return "📉"
    else:
        return "⬜"


def format_pump_alert(signal_data, price_data=None):
    """
    Formatea una alerta de pump para Telegram.
    
    Args:
        signal_data: dict con datos de la señal
        price_data: dict opcional con datos de precio actuales
    
    Returns:
        str: Mensaje formateado en HTML
    """
    level = signal_data.get("level", "DESCONOCIDO")
    symbol = signal_data.get("symbol", "???")
    total_score = signal_data.get("total_score", 0)
    
    # Parsear scores individuales
    individual = signal_data.get("individual_scores", {})
    if isinstance(individual, str):
        individual = json.loads(individual)
    
    triggered = signal_data.get("triggered_rules", [])
    if isinstance(triggered, str):
        triggered = json.loads(triggered)
    
    # Construir mensaje
    emoji = _level_emoji(level)
    
    msg = f"""
{emoji} <b>ALERTA DE PUMP DETECTADO</b> {emoji}

<b>Token:</b> {symbol}
<b>Nivel:</b> {level} (Score: {total_score}/100)
<b>Exchange:</b> {signal_data.get('exchange', 'MEXC')}

━━━━━━━━━━━━━━━━━━━━

<b>📊 Reglas Activadas:</b>
"""
    
    # Agregar scores individuales
    rule_names_es = {
        "volume_anomaly": "Volumen Anómalo",
        "price_momentum": "Momentum de Precio",
        "market_cap_efficiency": "Eficiencia Market Cap",
        "new_token": "Token Nuevo",
        "holder_concentration": "Concentración Holders",
        "exchange_inflow": "Inflow a Exchanges",
    }
    
    for rule, score in individual.items():
        rule_emoji = _score_emoji(score)
        rule_name = rule_names_es.get(rule, rule)
        is_triggered = "✓" if rule in triggered else " "
        msg += f"  {rule_emoji} {rule_name}: <b>{score}</b>/100 [{is_triggered}]\n"
    
    # Agregar datos de precio si están disponibles
    if price_data:
        msg += f"""
━━━━━━━━━━━━━━━━━━━━

<b>💰 Precio:</b> ${price_data.get('price', 0):.8g}
<b>📈 Cambio 1h:</b> {price_data.get('price_change_1h', 0):+.2f}%
<b>📈 Cambio 4h:</b> {price_data.get('price_change_4h', 0):+.2f}%
<b>📈 Cambio 24h:</b> {price_data.get('price_change_24h', 0):+.2f}%
<b>📊 Volumen 24h:</b> ${price_data.get('quote_volume', 0):,.0f}
"""
    
    msg += f"""
━━━━━━━━━━━━━━━━━━━━
<i>⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>
<i>🤖 Criminal Pump Detector v1.0</i>
"""
    
    return msg.strip()


# ============================================================
# WORKFLOW PRINCIPAL
# ============================================================

def check_and_alert():
    """
    Revisa señales no alertadas y envía notificaciones por Telegram.
    Implementa deduplicación: no repetir alerta del mismo token en 6h.
    
    Returns:
        int: Cantidad de alertas enviadas
    """
    logger.info("📱 Verificando señales para alertar...")
    
    # Obtener señales no alertadas
    signals = db.get_unalerted_signals()
    
    if not signals:
        logger.info("Sin señales nuevas para alertar")
        return 0
    
    alerts_sent = 0
    
    for signal in signals:
        token_id = signal["token_id"]
        
        # Verificar cooldown (deduplicación)
        if db.has_recent_alert(token_id, hours=ALERT_COOLDOWN_HOURS):
            logger.debug(f"Cooldown activo para token {signal['symbol']}, saltando")
            db.mark_signal_alerted(signal["id"])
            continue
        
        # Obtener métricas actuales para enriquecer la alerta
        metrics = db.get_latest_metrics(token_id)
        price_data = None
        if metrics:
            # Obtener último precio
            prices = db.get_price_history(token_id, hours=1)
            if prices:
                latest_price = prices[-1]
                price_data = {
                    "price": latest_price.get("price", 0),
                    "quote_volume": latest_price.get("quote_volume", 0),
                    "price_change_1h": metrics.get("price_change_1h", 0),
                    "price_change_4h": metrics.get("price_change_4h", 0),
                    "price_change_24h": metrics.get("price_change_24h", 0),
                }
        
        # Formatear y enviar
        message = format_pump_alert(signal, price_data)
        success = _send_telegram_message(message)
        
        if success:
            db.mark_signal_alerted(signal["id"])
            alerts_sent += 1
            logger.info(f"📱 Alerta enviada: {signal['symbol']} ({signal['level']})")
        
    logger.info(f"✅ {alerts_sent} alertas enviadas de {len(signals)} señales")
    return alerts_sent


def format_trade_alert(trade_data, is_open=True, strategy="PUMP_DETECTOR"):
    """
    Formatea una alerta de paper trade para Telegram.
    Distingue visualmente si la señal viene de TradingView o del Pump Detector.
    """
    symbol = trade_data.get("symbol", "???")
    
    if strategy == "TRADINGVIEW":
        header = f"🎯 <b>SEÑAL TRADINGVIEW: {symbol}</b>"
    else:
        header = f"💼 <b>NUEVO PAPER TRADE: {symbol}</b>" if is_open else f"🏁 <b>PAPER TRADE CERRADO: {symbol}</b>"

    if is_open:
        entry_price = trade_data.get("entry_price", 0)
        amount_usd = trade_data.get("amount_usd", 0)
        
        if strategy == "TRADINGVIEW":
            msg = f"""
{header}

🔹 <b>Acción:</b> COMPRA (Señal Pine Script)
💵 <b>Monto:</b> ${amount_usd:.2f}
📌 <b>Precio Entrada:</b> ${entry_price:.8g}

━━━━━━━━━━━━━━━━━━━━
<i>🤖 Criminal Pump Detector v1.0</i>
"""
        else:
            msg = f"""
{header}

<b>Acción:</b> COMPRA Mercado
<b>Precio Entrada:</b> ${entry_price:.8g}
<b>Monto:</b> ${amount_usd:.2f}

━━━━━━━━━━━━━━━━━━━━
<i>🤖 Criminal Pump Detector v1.0</i>
"""
    else:
        pnl_percent = trade_data.get("pnl_percent", 0)
        pnl_usd = trade_data.get("pnl_usd", 0)
        exit_reason = trade_data.get("exit_reason", "UNKNOWN")
        
        if strategy == "TRADINGVIEW":
            emoji = "🎯" if pnl_percent > 0 else "🛑"
            msg = f"""
{header}

🔹 <b>Acción:</b> VENTA (Señal Pine Script)
<b>PNL:</b> {pnl_percent:+.2f}% (${pnl_usd:+.2f})

━━━━━━━━━━━━━━━━━━━━
<i>🤖 Criminal Pump Detector v1.0</i>
"""
        else:
            emoji = "🎯" if pnl_percent > 0 else "🛑"
            if exit_reason == "TIME_STOP":
                emoji = "⏱️"
                
            msg = f"""
{emoji} <b>TRADE CERRADO ({exit_reason})</b> {emoji}

<b>Token:</b> {symbol}
<b>PNL:</b> {pnl_percent:+.2f}% (${pnl_usd:+.2f})

━━━━━━━━━━━━━━━━━━━━
<i>🤖 Criminal Pump Detector v1.0</i>
"""
    return msg.strip()

def send_trade_alert(trade_data, is_open=True, strategy="PUMP_DETECTOR"):
    """Envía alerta por apertura o cierre de trade simulado."""
    message = format_trade_alert(trade_data, is_open, strategy)
    success = _send_telegram_message(message)
    if success:
        logger.info(f"📱 Alerta de trade enviada: {trade_data.get('symbol')} ({'OPEN' if is_open else 'CLOSE'}) [{strategy}]")
    return success


def send_daily_report():
    """
    Envía un reporte diario con resumen de actividad y PNL.
    """
    logger.info("📊 Generando reporte diario...")
    
    stats = db.get_db_stats()
    
    # Contar señales de hoy
    with db.get_db() as conn:
        today_signals = conn.execute("""
            SELECT level, COUNT(*) as cnt 
            FROM signals 
            WHERE timestamp >= datetime('now', '-24 hours')
            GROUP BY level
        """).fetchall()
        
        # Paper trades stats
        open_trades = conn.execute("""
            SELECT COUNT(*) as cnt FROM paper_trades WHERE status = 'OPEN'
        """).fetchone()
        
        closed_today = conn.execute("""
            SELECT COUNT(*) as cnt, SUM(pnl_usd) as pnl 
            FROM paper_trades 
            WHERE status = 'CLOSED' AND exit_time >= datetime('now', '-24 hours')
        """).fetchone()
    
    total_pnl = db.get_total_pnl()
    
    signals_summary = ""
    for row in today_signals:
        emoji = _level_emoji(row["level"])
        signals_summary += f"  {emoji} {row['level']}: {row['cnt']}\n"
    
    if not signals_summary:
        signals_summary = "  Sin señales en las últimas 24h\n"
        
    pnl_today = closed_today['pnl'] if closed_today and closed_today['pnl'] else 0
    pnl_today_emoji = "🟩" if pnl_today > 0 else ("🟥" if pnl_today < 0 else "⬜")
    total_pnl_emoji = "🟩" if total_pnl > 0 else ("🟥" if total_pnl < 0 else "⬜")
    
    msg = f"""
📊 <b>REPORTE DIARIO</b> 📊

<b>🗓️ {datetime.now(timezone.utc).strftime('%Y-%m-%d')}</b>

━━━━━━━━━━━━━━━━━━━━

<b>📡 Tokens rastreados:</b> {stats.get('tokens', 0)}
<b>📝 Señales totales:</b> {stats.get('signals', 0)}

<b>Señales últimas 24h:</b>
{signals_summary}
━━━━━━━━━━━━━━━━━━━━

<b>💼 PAPER TRADING</b>
<b>Trades abiertos:</b> {open_trades['cnt'] if open_trades else 0}
<b>Cerrados hoy:</b> {closed_today['cnt'] if closed_today else 0}
<b>PNL Hoy:</b> {pnl_today_emoji} ${pnl_today:+.2f}
<b>PNL Total Acumulado:</b> {total_pnl_emoji} ${total_pnl:+.2f}

━━━━━━━━━━━━━━━━━━━━
<i>🤖 Criminal Pump Detector v1.0</i>
"""
    
    success = _send_telegram_message(msg.strip())
    if success:
        logger.info("✅ Reporte diario enviado")
    return success


def send_status():
    """Envía un mensaje de status/health check."""
    stats = db.get_db_stats()
    
    msg = f"""
✅ <b>BOT ACTIVO</b>

<b>Status:</b> Funcionando
<b>Tokens:</b> {stats.get('tokens', 0)}
<b>Señales:</b> {stats.get('signals', 0)}
<b>Hora:</b> {datetime.now(timezone.utc).strftime('%H:%M UTC')}
"""
    return _send_telegram_message(msg.strip())


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    
    if mode == "check":
        check_and_alert()
    elif mode == "report":
        send_daily_report()
    elif mode == "status":
        send_status()
    elif mode == "test":
        # Enviar alerta de prueba
        test_signal = {
            "symbol": "TESTUSDT",
            "level": "CRITICO",
            "total_score": 85.5,
            "exchange": "MEXC",
            "individual_scores": {
                "volume_anomaly": 100,
                "price_momentum": 70,
                "market_cap_efficiency": 90,
                "new_token": 80,
            },
            "triggered_rules": ["volume_anomaly", "price_momentum",
                               "market_cap_efficiency", "new_token"],
        }
        test_price = {
            "price": 0.0345,
            "quote_volume": 1_234_567,
            "price_change_1h": 8.5,
            "price_change_4h": 22.3,
            "price_change_24h": 45.7,
        }
        msg = format_pump_alert(test_signal, test_price)
        print(msg)
        _send_telegram_message(msg)
    else:
        print("Uso: python -m src.alert_bot [check|report|status|test]")
