"""
Configuración centralizada del Criminal Pump Detector.
Todas las variables de entorno y constantes del sistema.
"""

import os
from pathlib import Path

# ============================================================
# RUTAS
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "pump_detector.db"
LOG_PATH = BASE_DIR / "logs" / "bot.log"

# Crear directorios si no existen
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ============================================================
# API KEYS (desde variables de entorno)
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
MORALIS_API_KEY = os.getenv("MORALIS_API_KEY", "")
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET", "")

# ============================================================
# MEXC API ENDPOINTS (públicos, sin API key)
# ============================================================
MEXC_BASE_URL = "https://api.mexc.com"
MEXC_TICKER_24H = f"{MEXC_BASE_URL}/api/v3/ticker/24hr"
MEXC_KLINES = f"{MEXC_BASE_URL}/api/v3/klines"
MEXC_EXCHANGE_INFO = f"{MEXC_BASE_URL}/api/v3/exchangeInfo"

# ============================================================
# COINGECKO API ENDPOINTS
# ============================================================
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
COINGECKO_COINS_MARKETS = f"{COINGECKO_BASE_URL}/coins/markets"

# ============================================================
# RATE LIMITS
# ============================================================
MEXC_MAX_REQUESTS_PER_SECOND = 10        # Conservador (límite real: 20)
COINGECKO_MAX_REQUESTS_PER_MINUTE = 25   # Conservador (límite real: 30)
UPDATE_INTERVAL_MINUTES = int(os.getenv("UPDATE_INTERVAL_MINUTES", "15"))

# ============================================================
# REGLAS DE SCORING — PESOS (suman 100%)
# ============================================================
RULE_WEIGHTS = {
    "volume_anomaly": 0.30,     # Regla 1: Volumen anómalo
    "price_momentum": 0.30,     # Regla 2: Momentum de precio
    "market_cap_efficiency": 0.20,  # Regla 3: Eficiencia de market cap
    "new_token": 0.20,          # Regla 4: Token nuevo/recién listado
    # Fase 2:
    # "holder_concentration": 0.15,
    # "exchange_inflow": 0.10,
}

# ============================================================
# UMBRALES DE SCORING
# ============================================================
SCORE_CRITICAL = 75     # Alerta inmediata
SCORE_HIGH = 60         # Alerta + monitoreo
SCORE_MEDIUM = 45       # Agregar a watchlist
# < 45 = Ignorar

# ============================================================
# REGLA 1: VOLUMEN ANÓMALO — Umbrales
# ============================================================
VOL_SPIKE_EXTREME = 3.0     # >300% vs promedio 7d = 100 pts
VOL_SPIKE_HIGH = 2.0        # >200% = 70 pts
VOL_SPIKE_MODERATE = 1.5    # >150% = 40 pts

# ============================================================
# REGLA 2: MOMENTUM DE PRECIO — Umbrales
# ============================================================
MOMENTUM_EARLY_1H = 5.0     # 5% en 1h
MOMENTUM_EARLY_4H = 15.0    # 15% en 4h
MOMENTUM_EARLY_24H_MAX = 50.0  # <50% en 24h (aún temprano)
MOMENTUM_LATE_24H = 100.0   # >100% = ya explotó

# ============================================================
# REGLA 3: MARKET CAP — Umbrales
# ============================================================
MCAP_LOW = 10_000_000       # $10M
MCAP_VERY_LOW = 1_000_000   # $1M
VOL_MCAP_RATIO_THRESHOLD = 0.5  # Ratio volumen/mcap

# ============================================================
# REGLA 4: TOKEN NUEVO — Umbrales (días desde listing)
# ============================================================
NEW_TOKEN_VERY_NEW = 3      # <3 días = 80 pts
NEW_TOKEN_NEW = 7           # <7 días = 50 pts
NEW_TOKEN_OLD = 30          # >30 días = 0 pts

# ============================================================
# TRADING (Paper + Real)
# ============================================================
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
MAX_TRADE_USD = float(os.getenv("MAX_TRADE_USD", "50"))
MAX_OPEN_POSITIONS = 3
MAX_DAILY_TRADES = 5

# Take profit escalonado
TP1_PERCENT = 50    # +50% → vender 33%
TP2_PERCENT = 100   # +100% → vender 33%
TP3_PERCENT = 200   # +200% → vender 34%
STOP_LOSS_PERCENT = -15  # -15% → vender todo
TIME_STOP_HOURS = 24     # 24h → vender a mercado

# ============================================================
# ALERTAS
# ============================================================
ALERT_COOLDOWN_HOURS = 6    # No repetir alerta del mismo token en 6h
DAILY_REPORT_HOUR = 9       # Enviar reporte a las 9 AM UTC

# ============================================================
# FILTROS MÍNIMOS (para no procesar basura)
# ============================================================
MIN_VOLUME_24H_USD = 10_000     # Mínimo $10k de volumen diario
MIN_PRICE_USD = 0.0000001       # Filtrar tokens con precio irreal
MAX_TOKENS_TO_TRACK = 500       # Máximo tokens en el sistema
