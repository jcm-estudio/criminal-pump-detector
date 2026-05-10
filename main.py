"""
Criminal Pump Detector — Punto de entrada principal.

Modos de ejecución:
    python main.py discover    → Escaneo completo diario
    python main.py update      → Actualización rápida + scoring + alertas
    python main.py report      → Reporte diario
    python main.py status      → Health check por Telegram
    python main.py init        → Inicializar DB
"""

import sys
import logging
from pathlib import Path

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import LOG_PATH
from src import database as db
from src.data_collector import run_discover, run_update
from src.pump_scorer import run_scoring
from src.alert_bot import check_and_alert, send_daily_report, send_status

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
    ]
)
logger = logging.getLogger("main")


# ============================================================
# JOBS
# ============================================================

def job_discover():
    """
    Escaneo completo diario (1x/día a las 3 AM UTC).
    - Descubre todos los tokens nuevos de MEXC
    - Actualiza la lista de tokens activos
    - Guarda precios iniciales
    """
    logger.info("=" * 60)
    logger.info("🔍 JOB: DISCOVER — Escaneo completo")
    logger.info("=" * 60)
    
    db.init_db()
    count = run_discover()
    logger.info(f"✅ Discover terminado: {count} tokens procesados")


def job_update():
    """
    Actualización rápida (cada 15 min).
    Pipeline completo: datos → métricas → scoring → alertas
    """
    logger.info("-" * 40)
    logger.info("🔄 JOB: UPDATE — Pipeline completo")
    logger.info("-" * 40)
    
    db.init_db()
    
    # Paso 1: Actualizar precios y métricas
    updated = run_update()
    if not updated:
        logger.warning("⚠️ No se actualizaron tokens. ¿Primera ejecución? Ejecutar 'discover' primero.")
        # Auto-discover si no hay tokens
        active = db.get_active_tokens()
        if not active:
            logger.info("🔍 Auto-discover: primera ejecución detectada")
            run_discover()
            updated = run_update()
    
    # Paso 2: Scoring
    signals = run_scoring()
    
    # Paso 3: Alertas
    alerts = check_and_alert()
    
    # Paso 4: Limpieza de datos viejos (cada ejecución, es rápido)
    db.cleanup_old_data(days=30)
    
    logger.info(
        f"✅ Update completo: {updated} precios, "
        f"{len(signals)} señales, {alerts} alertas"
    )


def job_report():
    """Reporte diario (1x/día a las 9 AM UTC)."""
    logger.info("📊 JOB: REPORTE DIARIO")
    db.init_db()
    send_daily_report()


def job_status():
    """Health check por Telegram."""
    db.init_db()
    send_status()


def job_init():
    """Solo inicializar la base de datos."""
    db.init_db()
    stats = db.get_db_stats()
    logger.info(f"✅ Base de datos inicializada: {stats}")


# ============================================================
# ENTRY POINT
# ============================================================

JOBS = {
    "discover": job_discover,
    "update": job_update,
    "report": job_report,
    "status": job_status,
    "init": job_init,
}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Criminal Pump Detector v1.0")
        print(f"\nUso: python main.py <comando>")
        print(f"\nComandos disponibles:")
        for cmd in JOBS:
            print(f"  {cmd:12s} — {JOBS[cmd].__doc__.strip().split(chr(10))[0]}")
        sys.exit(0)
    
    command = sys.argv[1].lower()
    
    if command not in JOBS:
        print(f"❌ Comando desconocido: {command}")
        print(f"Comandos: {', '.join(JOBS.keys())}")
        sys.exit(1)
    
    try:
        JOBS[command]()
    except KeyboardInterrupt:
        logger.info("⏹️ Detenido por el usuario")
    except Exception as e:
        logger.error(f"❌ Error fatal: {e}", exc_info=True)
        sys.exit(1)
