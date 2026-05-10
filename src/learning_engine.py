"""
Motor de Aprendizaje (Learning Engine).
Analiza el resultado de los trades pasados y ajusta dinámicamente los pesos
de las reglas de scoring para maximizar el Win Rate.
"""

import json
import logging
from datetime import datetime, timezone

from src import database as db
from src.config import RULE_WEIGHTS
from src.alert_bot import _send_telegram_message

logger = logging.getLogger(__name__)

# Parámetros de ajuste
LEARNING_RATE = 0.05  # 5% de ajuste máximo por iteración
MIN_TRADES_TO_LEARN = 10  # Mínimo de trades necesarios para sacar conclusiones
MAX_WEIGHT = 0.50     # Ninguna regla puede valer más del 50%
MIN_WEIGHT = 0.05     # Ninguna regla puede valer menos del 5%

def analyze_and_optimize():
    """
    Analiza trades cerrados y ajusta pesos.
    Retorna (old_weights, new_weights, success_rate)
    """
    logger.info("🧠 Iniciando Learning Engine...")
    
    current_weights = db.get_current_weights()
    if not current_weights:
        current_weights = RULE_WEIGHTS.copy()
        
    # Obtener todos los trades cerrados
    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT pt.*, s.triggered_rules, s.total_score 
            FROM paper_trades pt
            JOIN signals s ON pt.signal_id = s.id
            WHERE pt.status = 'CLOSED'
        """).fetchall()
        
    trades = [dict(r) for r in rows]
    
    if len(trades) < MIN_TRADES_TO_LEARN:
        logger.info(f"⏭️ Insuficientes trades para aprender ({len(trades)}/{MIN_TRADES_TO_LEARN})")
        return current_weights, current_weights, 0.0
        
    # Contabilizar éxitos y fracasos por regla
    rule_stats = {rule: {"success": 0, "fail": 0} for rule in current_weights.keys()}
    
    winning_trades = 0
    for trade in trades:
        is_win = trade["pnl_percent"] > 0
        if is_win:
            winning_trades += 1
            
        try:
            triggered = json.loads(trade["triggered_rules"])
        except json.JSONDecodeError:
            continue
            
        for rule in triggered:
            if rule in rule_stats:
                if is_win:
                    rule_stats[rule]["success"] += 1
                else:
                    rule_stats[rule]["fail"] += 1
                    
    win_rate = winning_trades / len(trades)
    logger.info(f"📊 Win Rate global: {win_rate*100:.1f}% ({winning_trades}/{len(trades)})")
    
    # Calcular nuevos pesos
    new_weights = current_weights.copy()
    
    for rule, stats in rule_stats.items():
        total = stats["success"] + stats["fail"]
        if total < 3:  # Necesita un mínimo de activaciones para juzgar
            continue
            
        rule_win_rate = stats["success"] / total
        
        # Si la regla acierta más que el promedio global, subirle el peso
        if rule_win_rate > win_rate + 0.05:
            new_weights[rule] += LEARNING_RATE
        # Si acierta menos, bajarle el peso
        elif rule_win_rate < win_rate - 0.05:
            new_weights[rule] -= LEARNING_RATE
            
    # Asegurar límites y normalizar (para que sumen 1.0)
    total_weight = 0
    for rule in new_weights:
        new_weights[rule] = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weights[rule]))
        total_weight += new_weights[rule]
        
    for rule in new_weights:
        new_weights[rule] = round(new_weights[rule] / total_weight, 3)
        
    # Guardar en base de datos
    now = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        for rule, weight in new_weights.items():
            conn.execute("""
                INSERT INTO learning_weights (rule_name, weight, last_updated)
                VALUES (?, ?, ?)
                ON CONFLICT(rule_name) DO UPDATE SET
                    weight = excluded.weight,
                    last_updated = excluded.last_updated
            """, (rule, weight, now))
            
        # Registrar reporte de aprendizaje
        conn.execute("""
            INSERT INTO learning_reports (date, old_weights, new_weights, old_pnl)
            VALUES (?, ?, ?, ?)
        """, (now, json.dumps(current_weights), json.dumps(new_weights), db.get_total_pnl()))
        
    logger.info(f"✅ Pesos optimizados. Nuevos pesos: {new_weights}")
    
    return current_weights, new_weights, win_rate


def run_optimization():
    """Wrapper para usar desde main.py"""
    old, new, win_rate = analyze_and_optimize()
    
    if old != new:
        msg = f"""
🧠 <b>LEARNING ENGINE ACTIVADO</b> 🧠

Se han optimizado los parámetros del algoritmo basándose en los resultados históricos ({win_rate*100:.1f}% Win Rate).

<b>Nuevos pesos:</b>
"""
        for r, w in new.items():
            diff = w - old.get(r, 0)
            emoji = "⬆️" if diff > 0 else ("⬇️" if diff < 0 else "➖")
            msg += f"- {r}: {w*100:.1f}% ({emoji}{abs(diff)*100:.1f}%)\n"
            
        msg += "\n<i>🤖 Criminal Pump Detector v1.0</i>"
        _send_telegram_message(msg.strip())
        
    return True
