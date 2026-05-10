"""
Recolector de datos de mercado desde MEXC Exchange API (pública, sin key).

Funciones principales:
- fetch_all_pairs_mexc(): Obtiene todos los pares SPOT USDT
- fetch_klines(): Obtiene velas históricas para calcular promedios
- calculate_metrics(): Calcula métricas derivadas para el scoring
- run_discover(): Escaneo completo diario
- run_update(): Actualización rápida cada 15 min
"""

import time
import logging
import requests
from datetime import datetime, timezone, timedelta

from src.config import (
    MEXC_TICKER_24H, MEXC_KLINES, MEXC_EXCHANGE_INFO,
    MEXC_MAX_REQUESTS_PER_SECOND,
    MIN_VOLUME_24H_USD, MIN_PRICE_USD, MAX_TOKENS_TO_TRACK,
)
from src import database as db

logger = logging.getLogger(__name__)

# Rate limiter simple
_last_request_time = 0


def _rate_limit():
    """Espera si es necesario para respetar rate limits."""
    global _last_request_time
    min_interval = 1.0 / MEXC_MAX_REQUESTS_PER_SECOND
    elapsed = time.time() - _last_request_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _last_request_time = time.time()


def _safe_request(url, params=None, retries=3):
    """Request con retry y backoff exponencial."""
    for attempt in range(retries):
        try:
            _rate_limit()
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                wait = (2 ** attempt) * 5
                logger.warning(f"Rate limited (429). Esperando {wait}s...")
                time.sleep(wait)
            elif response.status_code == 400:
                # Bad request = endpoint no soporta este símbolo, no reintentar
                logger.debug(f"Bad request (400) para {url}")
                return None
            else:
                logger.error(f"HTTP error {response.status_code}: {e}")
                if attempt == retries - 1:
                    raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error (intento {attempt + 1}/{retries}): {e}")
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


# ============================================================
# RECOLECCIÓN DE DATOS — MEXC
# ============================================================

def fetch_all_pairs_mexc():
    """
    Obtiene TODOS los pares SPOT de MEXC con ticker 24h.
    Un solo API call retorna todos los pares.
    Filtra solo pares USDT con volumen mínimo.
    
    Returns:
        list[dict]: Lista de pares con precio, volumen, etc.
    """
    logger.info("📡 Obteniendo tickers 24h de MEXC...")
    
    data = _safe_request(MEXC_TICKER_24H)
    if not data:
        logger.error("No se pudieron obtener tickers de MEXC")
        return []
    
    # Filtrar pares USDT con volumen mínimo
    usdt_pairs = []
    for ticker in data:
        symbol = ticker.get("symbol", "")
        
        # Solo pares USDT
        if not symbol.endswith("USDT"):
            continue
        
        # Extraer datos
        try:
            last_price = float(ticker.get("lastPrice", 0))
            volume_24h = float(ticker.get("volume", 0))
            quote_volume = float(ticker.get("quoteVolume", 0))
            high_price = float(ticker.get("highPrice", 0))
            low_price = float(ticker.get("lowPrice", 0))
            price_change_pct = float(ticker.get("priceChangePercent", 0))
        except (ValueError, TypeError):
            continue
        
        # Filtrar por volumen y precio mínimo
        if quote_volume < MIN_VOLUME_24H_USD:
            continue
        if last_price < MIN_PRICE_USD:
            continue
        
        base_asset = symbol.replace("USDT", "")
        
        usdt_pairs.append({
            "symbol": symbol,
            "base_asset": base_asset,
            "quote_asset": "USDT",
            "price": last_price,
            "volume_24h": volume_24h,
            "quote_volume": quote_volume,
            "high_24h": high_price,
            "low_24h": low_price,
            "price_change_pct": price_change_pct,
        })
    
    # Ordenar por volumen y tomar los top N
    usdt_pairs.sort(key=lambda x: x["quote_volume"], reverse=True)
    if len(usdt_pairs) > MAX_TOKENS_TO_TRACK:
        usdt_pairs = usdt_pairs[:MAX_TOKENS_TO_TRACK]
    
    logger.info(f"✅ {len(usdt_pairs)} pares USDT encontrados (vol > ${MIN_VOLUME_24H_USD:,})")
    return usdt_pairs


def fetch_klines(symbol, interval="60m", limit=168):
    """
    Obtiene velas históricas de MEXC para un par.
    
    Args:
        symbol: Par de trading (e.g., "BTCUSDT")
        interval: Intervalo de velas MEXC format ("1m", "5m", "15m", "30m", "60m", "4h", "1d")
        limit: Cantidad de velas (max 1000)
    
    Returns:
        list[dict]: Velas con open, high, low, close, volume
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": min(limit, 1000),
    }
    
    data = _safe_request(MEXC_KLINES, params=params)
    if not data:
        return []
    
    klines = []
    for k in data:
        try:
            klines.append({
                "timestamp": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "quote_volume": float(k[7]) if len(k) > 7 else 0,
            })
        except (IndexError, ValueError, TypeError):
            continue
    
    return klines


def fetch_exchange_info():
    """
    Obtiene info de exchange para detectar listing_date de tokens.
    
    Returns:
        dict: Mapeo symbol -> info del par
    """
    logger.info("📡 Obteniendo info de exchange MEXC...")
    data = _safe_request(MEXC_EXCHANGE_INFO)
    if not data or "symbols" not in data:
        return {}
    
    info = {}
    for sym in data["symbols"]:
        if sym.get("quoteAsset") == "USDT" and sym.get("status") == "ENABLED":
            info[sym["symbol"]] = {
                "base_asset": sym.get("baseAsset", ""),
                "quote_asset": sym.get("quoteAsset", ""),
                "status": sym.get("status", ""),
            }
    
    logger.info(f"✅ {len(info)} pares USDT activos en MEXC")
    return info


# ============================================================
# CÁLCULO DE MÉTRICAS
# ============================================================

def calculate_metrics_for_token(token_id, symbol):
    """
    Calcula métricas derivadas para un token específico.
    
    Métricas:
    - vol_7d_avg: Promedio de volumen de 7 días
    - price_change_1h/4h/24h: Cambio porcentual de precio
    - volume_ratio: Volumen actual / promedio 7d
    - volatility_score: Desviación estándar del precio
    """
    # Obtener velas de 60m (7 días = 168 horas)
    try:
        klines = fetch_klines(symbol, interval="60m", limit=168)
    except Exception as e:
        logger.debug(f"Error obteniendo klines para {symbol}: {e}")
        return None
    
    if len(klines) < 2:
        logger.debug(f"Insuficientes datos para {symbol} ({len(klines)} velas)")
        return None
    
    # Volumen promedio 7 días
    volumes = [k["quote_volume"] for k in klines]
    vol_7d_avg = sum(volumes) / len(volumes) if volumes else 0
    
    # Precio actual y cambios
    current_price = klines[-1]["close"]
    
    # Cambio 1h (última vela vs anterior)
    price_1h_ago = klines[-2]["close"] if len(klines) >= 2 else current_price
    price_change_1h = ((current_price - price_1h_ago) / price_1h_ago * 100
                        if price_1h_ago > 0 else 0)
    
    # Cambio 4h
    price_4h_ago = klines[-5]["close"] if len(klines) >= 5 else current_price
    price_change_4h = ((current_price - price_4h_ago) / price_4h_ago * 100
                        if price_4h_ago > 0 else 0)
    
    # Cambio 24h
    price_24h_ago = klines[-25]["close"] if len(klines) >= 25 else current_price
    price_change_24h = ((current_price - price_24h_ago) / price_24h_ago * 100
                         if price_24h_ago > 0 else 0)
    
    # Volumen actual (últimas 24 velas) vs promedio
    vol_recent = sum(k["quote_volume"] for k in klines[-24:])
    vol_7d_daily_avg = vol_7d_avg * 24 if vol_7d_avg > 0 else 1
    volume_ratio = vol_recent / vol_7d_daily_avg if vol_7d_daily_avg > 0 else 0
    
    # Volatilidad (desviación estándar de cambios porcentuales)
    if len(klines) >= 10:
        closes = [k["close"] for k in klines[-24:]]
        changes = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                changes.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100)
        
        if changes:
            mean_change = sum(changes) / len(changes)
            variance = sum((c - mean_change) ** 2 for c in changes) / len(changes)
            volatility_score = variance ** 0.5
        else:
            volatility_score = 0
    else:
        volatility_score = 0
    
    metrics = {
        "vol_7d_avg": vol_7d_avg,
        "price_change_1h": round(price_change_1h, 2),
        "price_change_4h": round(price_change_4h, 2),
        "price_change_24h": round(price_change_24h, 2),
        "volume_ratio": round(volume_ratio, 4),
        "volatility_score": round(volatility_score, 4),
        "market_cap": 0,  # Se llena con CoinGecko en discover
    }
    
    return metrics


# ============================================================
# WORKFLOWS PRINCIPALES
# ============================================================

def run_discover():
    """
    Escaneo completo diario. Descubre nuevos tokens y actualiza la lista.
    Se ejecuta 1 vez por día a las 3 AM UTC via GitHub Actions.
    """
    logger.info("=" * 60)
    logger.info("🔍 DISCOVER JOB — Escaneo completo iniciado")
    logger.info("=" * 60)
    
    # 1. Inicializar DB si es necesario
    db.init_db()
    
    # 2. Obtener todos los pares de MEXC
    pairs = fetch_all_pairs_mexc()
    if not pairs:
        logger.error("❌ No se obtuvieron pares de MEXC")
        return
    
    # 3. Guardar/actualizar tokens en DB
    tokens_nuevos = 0
    tokens_actualizados = 0
    
    for pair in pairs:
        token_id = db.upsert_token(
            symbol=pair["symbol"],
            name=pair["base_asset"],
            exchange="MEXC",
            base_asset=pair["base_asset"],
            quote_asset=pair["quote_asset"],
        )
        
        # Guardar precio actual
        db.insert_price_data(
            token_id=token_id,
            price=pair["price"],
            volume_24h=pair["volume_24h"],
            high_24h=pair["high_24h"],
            low_24h=pair["low_24h"],
            price_change_pct=pair["price_change_pct"],
            quote_volume=pair["quote_volume"],
        )
        
        tokens_actualizados += 1
    
    logger.info(f"✅ Discover completado: {tokens_actualizados} tokens procesados")
    
    # 4. Estadísticas
    stats = db.get_db_stats()
    logger.info(f"📊 DB Stats: {stats}")
    
    return tokens_actualizados


def run_update():
    """
    Actualización rápida cada 15 min. 
    
    Estrategia de 2 pasos para eficiencia:
    1. Pre-filtro RÁPIDO: usa solo datos del ticker 24h (1 API call total)
    2. Análisis PROFUNDO: solo para candidatos que pasan el pre-filtro (klines)
    
    Esto reduce de ~500 kline requests a ~20-50 por ciclo.
    """
    logger.info("-" * 40)
    logger.info("🔄 UPDATE JOB — Actualización rápida")
    logger.info("-" * 40)
    
    # 1. Inicializar DB si es necesario
    db.init_db()
    
    # 2. Obtener tickers actuales (1 solo API call)
    pairs = fetch_all_pairs_mexc()
    if not pairs:
        logger.error("❌ No se obtuvieron tickers")
        return 0
    
    # Crear mapeo rápido por símbolo
    ticker_map = {p["symbol"]: p for p in pairs}
    
    # 3. Actualizar precios de TODOS los tokens activos (rápido, sin API calls)
    active_tokens = db.get_active_tokens()
    updated = 0
    
    for token in active_tokens:
        symbol = token["symbol"]
        if symbol not in ticker_map:
            continue
        
        ticker = ticker_map[symbol]
        
        # Guardar precio actual
        db.insert_price_data(
            token_id=token["id"],
            price=ticker["price"],
            volume_24h=ticker["volume_24h"],
            high_24h=ticker["high_24h"],
            low_24h=ticker["low_24h"],
            price_change_pct=ticker["price_change_pct"],
            quote_volume=ticker["quote_volume"],
        )
        updated += 1
    
    # 4. PRE-FILTRO RÁPIDO: identificar candidatos prometedores
    # Solo basado en datos del ticker (sin API calls adicionales)
    candidates = []
    for token in active_tokens:
        symbol = token["symbol"]
        if symbol not in ticker_map:
            continue
        
        ticker = ticker_map[symbol]
        
        # Criterios de pre-filtro (cualquiera activa el análisis profundo):
        # - Cambio de precio > 5% en 24h
        # - Volumen alto (top 50 por quote_volume)
        price_change = abs(ticker.get("price_change_pct", 0))
        is_promising = price_change >= 5.0
        
        if is_promising:
            candidates.append((token, ticker))
    
    # También incluir top 20 por volumen (siempre analizar los más activos)
    volume_sorted = sorted(
        [(t, ticker_map[t["symbol"]]) for t in active_tokens 
         if t["symbol"] in ticker_map],
        key=lambda x: x[1]["quote_volume"],
        reverse=True
    )[:20]
    
    # Combinar candidatos sin duplicar
    candidate_ids = {t["id"] for t, _ in candidates}
    for token, ticker in volume_sorted:
        if token["id"] not in candidate_ids:
            candidates.append((token, ticker))
            candidate_ids.add(token["id"])
    
    logger.info(
        f"📊 Pre-filtro: {len(candidates)} candidatos de {len(active_tokens)} tokens "
        f"(cambio >5% o top volumen)"
    )
    
    # 5. ANÁLISIS PROFUNDO: klines solo para candidatos
    metrics_calculated = 0
    for token, ticker in candidates:
        metrics = calculate_metrics_for_token(token["id"], token["symbol"])
        if metrics:
            # Usar price_change_pct del ticker como fallback para 24h
            if abs(metrics["price_change_24h"]) < 0.01:
                metrics["price_change_24h"] = ticker.get("price_change_pct", 0)
            
            db.insert_metrics(
                token_id=token["id"],
                **metrics
            )
            metrics_calculated += 1
    
    logger.info(f"✅ Update: {updated} precios, {metrics_calculated} métricas calculadas")
    return updated


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    mode = sys.argv[1] if len(sys.argv) > 1 else "update"
    
    if mode == "discover":
        run_discover()
    elif mode == "update":
        run_update()
    else:
        print(f"Uso: python -m src.data_collector [discover|update]")
