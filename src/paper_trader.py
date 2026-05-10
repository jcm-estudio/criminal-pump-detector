"""
Simulador de Paper Trading.
Toma las señales generadas y simula operaciones de compra/venta usando
los parámetros de config.py.
"""

import logging
from datetime import datetime, timezone

from src.config import (
    PAPER_TRADING, MAX_TRADE_USD, MAX_OPEN_POSITIONS, MAX_DAILY_TRADES,
    TP1_PERCENT, STOP_LOSS_PERCENT, TIME_STOP_HOURS
)
from src import database as db

logger = logging.getLogger(__name__)

def process_new_signals(signals):
    """
    Evalúa señales nuevas y abre trades si se cumplen las condiciones.
    Solo abre trades para señales CRITICO o ALTO.
    """
    if not PAPER_TRADING:
        return []

    if not signals:
        return []

    opened_trades = []
    
    # Obtener estado actual
    open_trades = db.get_open_paper_trades()
    daily_count = db.get_daily_trades_count()
    
    for signal in signals:
        # Solo operar señales fuertes
        if signal["level"] not in ["CRITICO", "ALTO"]:
            continue
            
        # Verificar límites de la cuenta
        if len(open_trades) >= MAX_OPEN_POSITIONS:
            logger.info("⏸️ Paper Trader: Límite de posiciones abiertas alcanzado.")
            break
            
        if daily_count >= MAX_DAILY_TRADES:
            logger.info("⏸️ Paper Trader: Límite de trades diarios alcanzado.")
            break
            
        # Verificar si ya tenemos este token abierto
        already_open = any(t["token_id"] == signal["token_id"] for t in open_trades)
        if already_open:
            continue
            
        # Obtener el precio actual para entrar
        prices = db.get_price_history(signal["token_id"], hours=1)
        if not prices:
            continue
            
        entry_price = prices[-1]["price"]
        if entry_price <= 0:
            continue
            
        # Calcular tamaño de la posición
        token_amount = MAX_TRADE_USD / entry_price
        
        # Abrir trade
        trade_id = db.insert_paper_trade(
            token_id=signal["token_id"],
            signal_id=signal.get("signal_id"),
            entry_price=entry_price,
            amount_usd=MAX_TRADE_USD,
            token_amount=token_amount
        )
        
        # Registrar y actualizar contadores
        trade_info = {
            "id": trade_id,
            "symbol": signal["symbol"],
            "entry_price": entry_price,
            "amount_usd": MAX_TRADE_USD,
            "token_amount": token_amount
        }
        
        open_trades.append({"token_id": signal["token_id"]})  # Dummy data para mantener el conteo
        daily_count += 1
        opened_trades.append(trade_info)
        
        logger.info(f"✅ PAPER TRADE ABIERTO: {signal['symbol']} a ${entry_price:.8g} (${MAX_TRADE_USD})")
        
    return opened_trades


def update_open_trades():
    """
    Evalúa los trades abiertos contra los precios actuales para ver si tocan TP, SL o Time Stop.
    """
    if not PAPER_TRADING:
        return []
        
    open_trades = db.get_open_paper_trades()
    if not open_trades:
        return []
        
    closed_trades = []
    now = datetime.now(timezone.utc)
    
    for trade in open_trades:
        # Obtener precio actual
        prices = db.get_price_history(trade["token_id"], hours=1)
        if not prices:
            continue
            
        current_price = prices[-1]["price"]
        if current_price <= 0:
            continue
            
        # Calcular PNL actual
        entry_price = trade["entry_price"]
        pnl_percent = ((current_price - entry_price) / entry_price) * 100
        pnl_usd = (trade["amount_usd"] * pnl_percent) / 100
        
        # Obtener tiempo transcurrido
        try:
            entry_time = datetime.fromisoformat(trade["entry_time"].replace("Z", "+00:00"))
            hours_open = (now - entry_time).total_seconds() / 3600
        except (ValueError, TypeError):
            hours_open = 0
            
        exit_reason = None
        
        # Evaluar Stop Loss
        if pnl_percent <= STOP_LOSS_PERCENT:
            exit_reason = "STOP_LOSS"
            
        # Evaluar Take Profit (por ahora simple a TP1)
        elif pnl_percent >= TP1_PERCENT:
            exit_reason = "TAKE_PROFIT"
            
        # Evaluar Time Stop
        elif hours_open >= TIME_STOP_HOURS:
            exit_reason = "TIME_STOP"
            
        # Si se cumplió alguna condición, cerrar el trade
        if exit_reason:
            db.close_paper_trade(
                trade_id=trade["id"],
                exit_price=current_price,
                pnl_percent=pnl_percent,
                pnl_usd=pnl_usd,
                exit_reason=exit_reason
            )
            
            trade["exit_price"] = current_price
            trade["pnl_percent"] = pnl_percent
            trade["pnl_usd"] = pnl_usd
            trade["exit_reason"] = exit_reason
            closed_trades.append(trade)
            
            logger.info(
                f"❌ PAPER TRADE CERRADO: {trade['symbol']} | "
                f"Razón: {exit_reason} | "
                f"PNL: {pnl_percent:+.2f}% (${pnl_usd:+.2f})"
            )
            
    return closed_trades
