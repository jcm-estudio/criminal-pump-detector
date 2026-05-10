"""
Base de datos SQLite para el Criminal Pump Detector.
Schema, conexión y funciones CRUD.
"""

import sqlite3
import json
import logging
from datetime import datetime, timezone
from contextlib import contextmanager

from src.config import DB_PATH

logger = logging.getLogger(__name__)


# ============================================================
# CONEXIÓN
# ============================================================

@contextmanager
def get_db():
    """Context manager para conexiones a la DB."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# SCHEMA
# ============================================================

SCHEMA_SQL = """
-- Tokens descubiertos en exchanges
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT DEFAULT '',
    exchange TEXT NOT NULL DEFAULT 'MEXC',
    base_asset TEXT NOT NULL,
    quote_asset TEXT NOT NULL DEFAULT 'USDT',
    listing_date TEXT,
    first_seen TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(symbol, exchange)
);

-- Datos de precio capturados en cada ciclo
CREATE TABLE IF NOT EXISTS price_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    price REAL NOT NULL,
    volume_24h REAL DEFAULT 0,
    high_24h REAL DEFAULT 0,
    low_24h REAL DEFAULT 0,
    price_change_pct REAL DEFAULT 0,
    quote_volume REAL DEFAULT 0,
    FOREIGN KEY (token_id) REFERENCES tokens(id)
);

-- Métricas calculadas
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    vol_7d_avg REAL DEFAULT 0,
    price_change_1h REAL DEFAULT 0,
    price_change_4h REAL DEFAULT 0,
    price_change_24h REAL DEFAULT 0,
    volatility_score REAL DEFAULT 0,
    volume_ratio REAL DEFAULT 0,
    market_cap REAL DEFAULT 0,
    FOREIGN KEY (token_id) REFERENCES tokens(id)
);

-- Señales de pump detectadas
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    total_score REAL NOT NULL,
    level TEXT NOT NULL,
    individual_scores TEXT NOT NULL,
    triggered_rules TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    alerted_at TEXT,
    FOREIGN KEY (token_id) REFERENCES tokens(id)
);

-- Trades simulados (paper trading)
CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL,
    signal_id INTEGER,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_time TEXT,
    exit_price REAL,
    amount_usd REAL NOT NULL,
    token_amount REAL NOT NULL,
    pnl_percent REAL,
    pnl_usd REAL,
    exit_reason TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    FOREIGN KEY (token_id) REFERENCES tokens(id),
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- Pesos del learning engine
CREATE TABLE IF NOT EXISTS learning_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name TEXT NOT NULL UNIQUE,
    weight REAL NOT NULL,
    accuracy REAL DEFAULT 0,
    total_predictions INTEGER DEFAULT 0,
    correct_predictions INTEGER DEFAULT 0,
    last_updated TEXT NOT NULL
);

-- Reportes del learning engine
CREATE TABLE IF NOT EXISTS learning_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    old_weights TEXT NOT NULL,
    new_weights TEXT NOT NULL,
    old_pnl REAL DEFAULT 0,
    new_pnl REAL DEFAULT 0,
    improvements TEXT
);

-- Resultados de señales (para learning)
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL UNIQUE,
    price_at_signal REAL NOT NULL,
    price_1h_after REAL,
    price_4h_after REAL,
    price_24h_after REAL,
    max_price_24h REAL,
    outcome TEXT,
    max_profit_possible REAL,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- Índices para queries frecuentes
CREATE INDEX IF NOT EXISTS idx_price_data_token_time 
    ON price_data(token_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_token_time 
    ON metrics(token_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_status 
    ON signals(status, timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_level 
    ON signals(level, timestamp);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status 
    ON paper_trades(status);
"""


def init_db():
    """Inicializa la base de datos con el schema completo."""
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
        logger.info(f"Base de datos inicializada en: {DB_PATH}")
        _init_default_weights(conn)


def _init_default_weights(conn):
    """Inserta pesos por defecto si no existen."""
    from src.config import RULE_WEIGHTS
    now = datetime.now(timezone.utc).isoformat()
    for rule_name, weight in RULE_WEIGHTS.items():
        conn.execute("""
            INSERT OR IGNORE INTO learning_weights (rule_name, weight, last_updated)
            VALUES (?, ?, ?)
        """, (rule_name, weight, now))


# ============================================================
# FUNCIONES CRUD — TOKENS
# ============================================================

def upsert_token(symbol, name, exchange, base_asset, quote_asset="USDT",
                 listing_date=None):
    """Inserta o actualiza un token. Retorna el token_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        # Intentar insertar
        cursor = conn.execute("""
            INSERT INTO tokens (symbol, name, exchange, base_asset, quote_asset,
                              listing_date, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, exchange) DO UPDATE SET
                name = excluded.name,
                is_active = 1
            RETURNING id
        """, (symbol, name, exchange, base_asset, quote_asset, listing_date, now))
        row = cursor.fetchone()
        return row["id"]


def get_active_tokens():
    """Retorna todos los tokens activos."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM tokens WHERE is_active = 1"
        ).fetchall()
        return [dict(r) for r in rows]


def get_token_by_symbol(symbol, exchange="MEXC"):
    """Busca un token por símbolo y exchange."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tokens WHERE symbol = ? AND exchange = ?",
            (symbol, exchange)
        ).fetchone()
        return dict(row) if row else None


# ============================================================
# FUNCIONES CRUD — PRICE DATA
# ============================================================

def insert_price_data(token_id, price, volume_24h, high_24h=0, low_24h=0,
                      price_change_pct=0, quote_volume=0):
    """Inserta un registro de precio."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO price_data 
            (token_id, timestamp, price, volume_24h, high_24h, low_24h,
             price_change_pct, quote_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (token_id, now, price, volume_24h, high_24h, low_24h,
              price_change_pct, quote_volume))


def get_price_history(token_id, hours=168):
    """Obtiene historial de precios de las últimas N horas (default 7 días)."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM price_data 
            WHERE token_id = ?
            AND timestamp >= datetime('now', ? || ' hours')
            ORDER BY timestamp ASC
        """, (token_id, f"-{hours}")).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# FUNCIONES CRUD — METRICS
# ============================================================

def insert_metrics(token_id, vol_7d_avg=0, price_change_1h=0,
                   price_change_4h=0, price_change_24h=0,
                   volatility_score=0, volume_ratio=0, market_cap=0):
    """Inserta métricas calculadas."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO metrics
            (token_id, timestamp, vol_7d_avg, price_change_1h, price_change_4h,
             price_change_24h, volatility_score, volume_ratio, market_cap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (token_id, now, vol_7d_avg, price_change_1h, price_change_4h,
              price_change_24h, volatility_score, volume_ratio, market_cap))


def get_latest_metrics(token_id):
    """Obtiene las métricas más recientes de un token."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT * FROM metrics 
            WHERE token_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (token_id,)).fetchone()
        return dict(row) if row else None


# ============================================================
# FUNCIONES CRUD — SIGNALS
# ============================================================

def insert_signal(token_id, total_score, level, individual_scores,
                  triggered_rules):
    """Inserta una nueva señal de pump."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO signals
            (token_id, timestamp, total_score, level, individual_scores,
             triggered_rules, status)
            VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')
            RETURNING id
        """, (token_id, now, total_score, level,
              json.dumps(individual_scores),
              json.dumps(triggered_rules)))
        row = cursor.fetchone()
        return row["id"]


def get_active_signals(min_level=None):
    """Obtiene señales activas, opcionalmente filtradas por nivel."""
    with get_db() as conn:
        if min_level:
            rows = conn.execute("""
                SELECT s.*, t.symbol, t.name, t.exchange
                FROM signals s
                JOIN tokens t ON s.token_id = t.id
                WHERE s.status = 'ACTIVE' AND s.level = ?
                ORDER BY s.total_score DESC
            """, (min_level,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT s.*, t.symbol, t.name, t.exchange
                FROM signals s
                JOIN tokens t ON s.token_id = t.id
                WHERE s.status = 'ACTIVE'
                ORDER BY s.total_score DESC
            """).fetchall()
        return [dict(r) for r in rows]


def get_unalerted_signals():
    """Obtiene señales que aún no fueron notificadas."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT s.*, t.symbol, t.name, t.exchange
            FROM signals s
            JOIN tokens t ON s.token_id = t.id
            WHERE s.status = 'ACTIVE' AND s.alerted_at IS NULL
            ORDER BY s.total_score DESC
        """).fetchall()
        return [dict(r) for r in rows]


def mark_signal_alerted(signal_id):
    """Marca una señal como notificada."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute("""
            UPDATE signals SET alerted_at = ? WHERE id = ?
        """, (now, signal_id))


def has_recent_alert(token_id, hours=6):
    """Verifica si ya se envió alerta de este token en las últimas N horas."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT COUNT(*) as cnt FROM signals
            WHERE token_id = ?
            AND alerted_at IS NOT NULL
            AND alerted_at >= datetime('now', ? || ' hours')
        """, (token_id, f"-{hours}")).fetchone()
        return row["cnt"] > 0


# ============================================================
# FUNCIONES CRUD — LEARNING WEIGHTS
# ============================================================

def get_current_weights():
    """Obtiene los pesos actuales de las reglas."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT rule_name, weight FROM learning_weights"
        ).fetchall()
        return {row["rule_name"]: row["weight"] for row in rows}


def update_weight(rule_name, new_weight, accuracy=None):
    """Actualiza el peso de una regla."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        if accuracy is not None:
            conn.execute("""
                UPDATE learning_weights 
                SET weight = ?, accuracy = ?, last_updated = ?
                WHERE rule_name = ?
            """, (new_weight, accuracy, now, rule_name))
        else:
            conn.execute("""
                UPDATE learning_weights 
                SET weight = ?, last_updated = ?
                WHERE rule_name = ?
            """, (new_weight, now, rule_name))


# ============================================================
# UTILIDADES
# ============================================================

def get_db_stats():
    """Retorna estadísticas generales de la base de datos."""
    with get_db() as conn:
        stats = {}
        for table in ["tokens", "price_data", "metrics", "signals",
                       "paper_trades"]:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            stats[table] = row["cnt"]
        return stats


def cleanup_old_data(days=30):
    """Elimina datos de precio más viejos que N días para mantener la DB liviana."""
    with get_db() as conn:
        result = conn.execute("""
            DELETE FROM price_data 
            WHERE timestamp < datetime('now', ? || ' days')
        """, (f"-{days}",))
        deleted = result.rowcount
        if deleted > 0:
            logger.info(f"Limpieza: {deleted} registros de precio eliminados (>{days} días)")
        return deleted


if __name__ == "__main__":
    init_db()
    print(f"✅ Base de datos creada en: {DB_PATH}")
    print(f"📊 Stats: {get_db_stats()}")
