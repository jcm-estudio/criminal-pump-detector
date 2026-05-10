"""
Motor de Scoring para detección de Criminal/Scam Pumps.

Implementa 4 reglas de detección con pesos configurables:
1. Volumen Anómalo (30%)
2. Momentum de Precio (30%)
3. Eficiencia de Market Cap (20%)
4. Token Nuevo / Recién Listado (20%)

Cada regla retorna un score de 0 a 100.
El score total es la media ponderada de todas las reglas.
"""

import json
import logging
from datetime import datetime, timezone, timedelta

from src.config import (
    # Pesos
    RULE_WEIGHTS,
    # Umbrales scoring
    SCORE_CRITICAL, SCORE_HIGH, SCORE_MEDIUM,
    # Regla 1: Volumen
    VOL_SPIKE_EXTREME, VOL_SPIKE_HIGH, VOL_SPIKE_MODERATE,
    # Regla 2: Momentum
    MOMENTUM_EARLY_1H, MOMENTUM_EARLY_4H, MOMENTUM_EARLY_24H_MAX,
    MOMENTUM_LATE_24H,
    # Regla 3: Market Cap
    MCAP_LOW, MCAP_VERY_LOW, VOL_MCAP_RATIO_THRESHOLD,
    # Regla 4: Token Nuevo
    NEW_TOKEN_VERY_NEW, NEW_TOKEN_NEW, NEW_TOKEN_OLD,
)
from src import database as db

logger = logging.getLogger(__name__)


# ============================================================
# REGLA 1: VOLUMEN ANÓMALO (Peso: 30%)
# ============================================================

def volume_anomaly_rule(volume_ratio):
    """
    Compara el volumen actual de 24h contra el promedio de 7 días.
    
    Args:
        volume_ratio: Ratio volumen_24h / promedio_7d
    
    Returns:
        int: Score 0-100
    """
    if volume_ratio <= 0:
        return 0
    
    if volume_ratio >= VOL_SPIKE_EXTREME:   # >300%
        return 100
    elif volume_ratio >= VOL_SPIKE_HIGH:    # >200%
        return 70
    elif volume_ratio >= VOL_SPIKE_MODERATE:  # >150%
        return 40
    else:
        return 0


# ============================================================
# REGLA 2: MOMENTUM DE PRECIO (Peso: 30%)
# ============================================================

def price_momentum_rule(change_1h, change_4h, change_24h):
    """
    Evalúa el momentum del precio en múltiples timeframes.
    Busca detectar pumps TEMPRANOS (antes de que ya hayan explotado).
    
    Args:
        change_1h: Cambio porcentual en 1 hora
        change_4h: Cambio porcentual en 4 horas
        change_24h: Cambio porcentual en 24 horas
    
    Returns:
        int: Score 0-100
    """
    score = 0
    
    # Caso ideal: Momentum temprano fuerte
    # El precio sube consistentemente pero todavía no explotó
    if (change_1h >= MOMENTUM_EARLY_1H and           # +5% en 1h
        change_4h >= MOMENTUM_EARLY_4H and            # +15% en 4h
        change_24h < MOMENTUM_EARLY_24H_MAX):          # <50% en 24h (aún temprano)
        score = 100
    
    # Momentum decente pero no perfecto
    elif change_1h >= MOMENTUM_EARLY_1H and change_4h >= 10:
        score = 70
    
    # Solo momentum en 1h (posible inicio)
    elif change_1h >= MOMENTUM_EARLY_1H:
        score = 50
    
    # Ya explotó (>100% en 24h) — llegamos tarde
    elif change_24h >= MOMENTUM_LATE_24H:
        score = 30  # Penalizar por llegar tarde
    
    # Subida leve
    elif change_1h >= 3:
        score = 20
    
    # Bonus/penalización por dirección
    # Si el precio baja en la última hora pero subió en 24h → posible dump
    if change_1h < 0 and change_24h > 30:
        score = max(0, score - 30)  # Penalizar, posible dump en curso
    
    return min(100, max(0, score))


# ============================================================
# REGLA 3: EFICIENCIA DE MARKET CAP (Peso: 20%)
# ============================================================

def market_cap_rule(market_cap, volume_24h_usd):
    """
    Detecta tokens con market cap bajo pero volumen alto.
    Esto indica actividad desproporcionada — posible manipulación.
    
    Args:
        market_cap: Market cap en USD
        volume_24h_usd: Volumen en USD de 24h
    
    Returns:
        int: Score 0-100
    """
    # Si no tenemos datos de market cap, usar heurística
    if market_cap <= 0:
        # Sin market cap disponible: usar volumen como proxy
        # Alto volumen relativo = posible pump
        if volume_24h_usd > 1_000_000:
            return 30  # Puntaje bajo pero no ignorar
        return 0
    
    score = 0
    
    # Market cap bajo + volumen alto = señal fuerte
    vol_mcap_ratio = volume_24h_usd / market_cap if market_cap > 0 else 0
    
    if market_cap < MCAP_LOW and vol_mcap_ratio > VOL_MCAP_RATIO_THRESHOLD:
        score = 90
    elif market_cap < MCAP_LOW:
        score = 50
    elif vol_mcap_ratio > VOL_MCAP_RATIO_THRESHOLD:
        score = 60
    
    # Bonus para market caps muy bajos
    if market_cap < MCAP_VERY_LOW:
        score = min(100, score + 10)
    
    return score


# ============================================================
# REGLA 4: TOKEN NUEVO / RECIÉN LISTADO (Peso: 20%)
# ============================================================

def new_token_rule(first_seen_str):
    """
    Tokens nuevos son más propensos a pumps (fase de price discovery).
    
    Args:
        first_seen_str: Fecha ISO cuando lo vimos por primera vez
    
    Returns:
        int: Score 0-100
    """
    if not first_seen_str:
        return 0
    
    try:
        first_seen = datetime.fromisoformat(first_seen_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days_since = (now - first_seen).total_seconds() / 86400
    except (ValueError, TypeError):
        return 0
    
    if days_since < NEW_TOKEN_VERY_NEW:   # <3 días
        return 80
    elif days_since < NEW_TOKEN_NEW:      # <7 días
        return 50
    elif days_since < NEW_TOKEN_OLD:      # <30 días
        return 20
    else:
        return 0


# ============================================================
# SCORING TOTAL
# ============================================================

def calculate_total_score(individual_scores, weights=None):
    """
    Calcula el score total ponderado.
    
    Args:
        individual_scores: dict con {rule_name: score}
        weights: dict con pesos por regla (usa DB si es None)
    
    Returns:
        float: Score total 0-100
    """
    if weights is None:
        try:
            weights = db.get_current_weights()
        except Exception:
            weights = RULE_WEIGHTS
    
    total = 0
    total_weight = 0
    
    for rule_name, score in individual_scores.items():
        weight = weights.get(rule_name, 0)
        total += score * weight
        total_weight += weight
    
    # Normalizar si los pesos no suman 1
    if total_weight > 0 and total_weight != 1.0:
        total = total / total_weight
    
    return round(total, 2)


def classify_signal(total_score):
    """
    Clasifica una señal por nivel de urgencia.
    
    Returns:
        str o None: "CRITICO", "ALTO", "MEDIO", o None si es bajo
    """
    if total_score >= SCORE_CRITICAL:
        return "CRITICO"
    elif total_score >= SCORE_HIGH:
        return "ALTO"
    elif total_score >= SCORE_MEDIUM:
        return "MEDIO"
    return None


# ============================================================
# WORKFLOW PRINCIPAL
# ============================================================

def score_token(token, metrics):
    """
    Evalúa un token individual contra todas las reglas.
    
    Args:
        token: dict con datos del token (de la tabla tokens)
        metrics: dict con métricas calculadas (de la tabla metrics)
    
    Returns:
        dict o None: Resultado del scoring si pasa el umbral mínimo
    """
    if not metrics:
        return None
    
    # Calcular scores individuales
    individual_scores = {
        "volume_anomaly": volume_anomaly_rule(
            metrics.get("volume_ratio", 0)
        ),
        "price_momentum": price_momentum_rule(
            metrics.get("price_change_1h", 0),
            metrics.get("price_change_4h", 0),
            metrics.get("price_change_24h", 0),
        ),
        "market_cap_efficiency": market_cap_rule(
            metrics.get("market_cap", 0),
            metrics.get("vol_7d_avg", 0) * 24,  # Estimación volumen diario
        ),
        "new_token": new_token_rule(
            token.get("first_seen", "")
        ),
    }
    
    # Calcular total
    total_score = calculate_total_score(individual_scores)
    level = classify_signal(total_score)
    
    if level is None:
        return None  # Score demasiado bajo, ignorar
    
    # Identificar reglas que contribuyeron significativamente
    triggered_rules = [
        rule for rule, score in individual_scores.items()
        if score >= 40
    ]
    
    return {
        "token_id": token["id"],
        "symbol": token["symbol"],
        "total_score": total_score,
        "level": level,
        "individual_scores": individual_scores,
        "triggered_rules": triggered_rules,
    }


def run_scoring():
    """
    Ejecuta el scoring completo para todos los tokens activos.
    
    Estrategia de 2 niveles:
    1. Tokens CON métricas detalladas (klines): scoring completo
    2. Tokens SIN métricas (solo ticker): scoring básico con price_data
    
    Guarda señales en la DB si superan el umbral mínimo.
    
    Returns:
        list[dict]: Señales generadas
    """
    logger.info("🎯 SCORING — Evaluando tokens activos...")
    
    active_tokens = db.get_active_tokens()
    signals_generated = []
    scored_count = 0
    
    for token in active_tokens:
        # Verificar si ya hay alerta reciente para este token
        if db.has_recent_alert(token["id"], hours=6):
            continue
        
        # Intentar obtener métricas detalladas (de klines)
        metrics = db.get_latest_metrics(token["id"])
        
        # Fallback: construir métricas básicas desde price_data (ticker 24h)
        if not metrics:
            prices = db.get_price_history(token["id"], hours=1)
            if not prices:
                continue
            
            latest = prices[-1]
            price_change_24h = latest.get("price_change_pct", 0)
            quote_volume = latest.get("quote_volume", 0)
            
            # Solo evaluar si hay movimiento significativo
            if abs(price_change_24h) < 3.0:
                continue
            
            metrics = {
                "volume_ratio": 1.5 if abs(price_change_24h) > 10 else 1.0,
                "price_change_1h": price_change_24h / 6,  # Estimación
                "price_change_4h": price_change_24h / 2,  # Estimación
                "price_change_24h": price_change_24h,
                "market_cap": 0,
                "vol_7d_avg": quote_volume / 24,
            }
        
        # Evaluar
        result = score_token(token, metrics)
        if result is None:
            continue
        
        scored_count += 1
        
        # Guardar señal en DB
        signal_id = db.insert_signal(
            token_id=result["token_id"],
            total_score=result["total_score"],
            level=result["level"],
            individual_scores=result["individual_scores"],
            triggered_rules=result["triggered_rules"],
        )
        
        result["signal_id"] = signal_id
        signals_generated.append(result)
        
        logger.info(
            f"🚨 SEÑAL {result['level']}: {result['symbol']} "
            f"— Score: {result['total_score']}/100 "
            f"— Reglas: {', '.join(result['triggered_rules'])}"
        )
    
    logger.info(
        f"✅ Scoring completado: {len(signals_generated)} señales generadas "
        f"de {len(active_tokens)} tokens evaluados ({scored_count} con métricas)"
    )
    
    return signals_generated


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    signals = run_scoring()
    
    for s in signals:
        print(f"\n{'='*50}")
        print(f"Token: {s['symbol']}")
        print(f"Score: {s['total_score']}/100 ({s['level']})")
        print(f"Reglas: {s['individual_scores']}")
        print(f"Activadas: {s['triggered_rules']}")
