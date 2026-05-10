import sys
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import database as db
import src.paper_trader as paper_trader
import src.learning_engine as le

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("audit")

def run_audit():
    logger.info("=== INICIANDO AUDITORÍA ESTRICTA ===")
    
    # 1. Asegurar DB
    db.init_db()
    
    with db.get_db() as conn:
        # Tomar un token válido
        token = conn.execute("SELECT id, symbol FROM tokens LIMIT 1").fetchone()
        if not token:
            logger.error("No hay tokens en la base de datos.")
            return
            
        token_id = token["id"]
        symbol = token["symbol"]
        logger.info(f"Usando token {symbol} (ID: {token_id}) para el simulacro.")
        
        # 2. Limpiar estado
        conn.execute("DELETE FROM paper_trades")
        conn.execute("DELETE FROM signals")
        conn.execute("DELETE FROM learning_weights")
        conn.execute("DELETE FROM price_data WHERE token_id = ?", (token_id,))
        
        # 3. Inyectar precios iniciales ($1.0)
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO price_data (token_id, timestamp, price, volume_24h) VALUES (?, ?, ?, ?)",
            (token_id, now.isoformat(), 1.0, 50000)
        )
        
        # 4. Inyectar señal CRÍTICA
        cursor = conn.execute(
            "INSERT INTO signals (token_id, level, total_score, individual_scores, triggered_rules, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (token_id, "CRITICO", 85.0, '{"volume_anomaly": 85.0}', '["volume_anomaly"]', now.isoformat())
        )
        signal_id = cursor.lastrowid

    # 5. Forzar Paper Trader a procesar la señal
    signal_data = {
        "signal_id": signal_id,
        "token_id": token_id,
        "symbol": symbol,
        "level": "CRITICO"
    }
    paper_trader.process_new_signals([signal_data])
        
    logger.info("✅ Inyectada señal CRITICA y trade abierto")

    # 6. Inyectar precio de Take Profit ($1.6 = +60%)
    with db.get_db() as conn:
        tp_time = now + timedelta(minutes=15)
        conn.execute(
            "INSERT INTO price_data (token_id, timestamp, price, volume_24h) VALUES (?, ?, ?, ?)",
            (token_id, tp_time.isoformat(), 1.6, 50000)
        )
        logger.info("✅ Precio inyectado a $1.60 (+60%)")
        
    # 7. Forzar Paper Trader a actualizar (debe cerrar por TP)
    closed = paper_trader.update_open_trades()
    
    if len(closed) == 1:
        logger.info(f"✅ Paper Trader cerró el trade correctamente por TP.")
    else:
        logger.error(f"❌ Paper Trader NO cerró los trades. Cerrados: {len(closed)}")
        return
        
    # 8. Probar Learning Engine forzando un límite bajo
    le.MIN_TRADES_TO_LEARN = 1
    logger.info("🧠 Ejecutando Learning Engine...")
    le.run_optimization()
    
    # Verificar si el peso de 'volume_anomaly' subió
    weights = db.get_current_weights()
    if weights.get("volume_anomaly", 0) > 0.30:  # Original es 0.30
        logger.info(f"✅ Learning Engine ajustó pesos correctamente: {weights}")
    else:
        logger.error(f"❌ Learning Engine falló en ajustar los pesos. Pesos actuales: {weights}")
        return
        
    logger.info("=== AUDITORÍA FINALIZADA CON ÉXITO ===")

if __name__ == "__main__":
    run_audit()
