"""
Tests para el módulo de scoring (pump_scorer.py).
Verifica que las reglas detectan correctamente patrones de pump.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pump_scorer import (
    volume_anomaly_rule,
    price_momentum_rule,
    market_cap_rule,
    new_token_rule,
    calculate_total_score,
    classify_signal,
    score_token,
)
from datetime import datetime, timezone, timedelta


class TestVolumeAnomalyRule:
    """Tests para la Regla 1: Volumen Anómalo."""
    
    def test_extreme_volume_spike(self):
        """Volumen >300% del promedio debe dar score 100."""
        assert volume_anomaly_rule(3.5) == 100
    
    def test_high_volume_spike(self):
        """Volumen >200% del promedio debe dar score 70."""
        assert volume_anomaly_rule(2.5) == 70
    
    def test_moderate_volume_spike(self):
        """Volumen >150% del promedio debe dar score 40."""
        assert volume_anomaly_rule(1.7) == 40
    
    def test_normal_volume(self):
        """Volumen normal (<150%) debe dar score 0."""
        assert volume_anomaly_rule(1.2) == 0
    
    def test_zero_volume(self):
        """Sin volumen debe dar score 0."""
        assert volume_anomaly_rule(0) == 0
    
    def test_negative_volume(self):
        """Volumen negativo (error de datos) debe dar score 0."""
        assert volume_anomaly_rule(-1) == 0


class TestPriceMomentumRule:
    """Tests para la Regla 2: Momentum de Precio."""
    
    def test_perfect_early_pump(self):
        """Momentum temprano perfecto: +5% 1h, +15% 4h, <50% 24h."""
        score = price_momentum_rule(8, 20, 30)
        assert score == 100
    
    def test_late_pump(self):
        """Pump tardío: bajo momentum reciente pero >100% en 24h = llegamos tarde."""
        score = price_momentum_rule(2, 5, 150)
        assert score == 30
    
    def test_no_momentum(self):
        """Sin momentum debe dar score 0."""
        score = price_momentum_rule(0, 0, 0)
        assert score == 0
    
    def test_dump_in_progress(self):
        """Precio bajando en 1h pero alto en 24h = posible dump, penalizar."""
        score = price_momentum_rule(-5, 10, 50)
        assert score < 20
    
    def test_slight_momentum(self):
        """Momentum leve (3% en 1h) debe dar score moderado."""
        score = price_momentum_rule(3, 5, 10)
        assert score == 20


class TestMarketCapRule:
    """Tests para la Regla 3: Eficiencia de Market Cap."""
    
    def test_low_mcap_high_volume(self):
        """Market cap bajo + volumen desproporcionado = score alto."""
        score = market_cap_rule(5_000_000, 3_000_000)
        assert score >= 90
    
    def test_very_low_mcap(self):
        """Market cap < $1M debe tener bonus."""
        score = market_cap_rule(500_000, 300_000)
        assert score == 100
    
    def test_high_mcap(self):
        """Market cap alto (>$10M) sin ratio alto = score bajo."""
        score = market_cap_rule(100_000_000, 10_000_000)
        assert score <= 30
    
    def test_no_mcap_data(self):
        """Sin datos de market cap debe usar heurística."""
        score = market_cap_rule(0, 2_000_000)
        assert score == 30  # Volumen alto sin mcap
    
    def test_no_data_at_all(self):
        """Sin datos de nada = 0."""
        score = market_cap_rule(0, 100)
        assert score == 0


class TestNewTokenRule:
    """Tests para la Regla 4: Token Nuevo."""
    
    def test_very_new_token(self):
        """Token de <3 días debe dar score 80."""
        now = datetime.now(timezone.utc)
        first_seen = (now - timedelta(days=1)).isoformat()
        assert new_token_rule(first_seen) == 80
    
    def test_new_token(self):
        """Token de <7 días debe dar score 50."""
        now = datetime.now(timezone.utc)
        first_seen = (now - timedelta(days=5)).isoformat()
        assert new_token_rule(first_seen) == 50
    
    def test_recent_token(self):
        """Token de <30 días debe dar score 20."""
        now = datetime.now(timezone.utc)
        first_seen = (now - timedelta(days=15)).isoformat()
        assert new_token_rule(first_seen) == 20
    
    def test_old_token(self):
        """Token viejo (>30 días) debe dar score 0."""
        now = datetime.now(timezone.utc)
        first_seen = (now - timedelta(days=60)).isoformat()
        assert new_token_rule(first_seen) == 0
    
    def test_no_date(self):
        """Sin fecha = 0."""
        assert new_token_rule(None) == 0
        assert new_token_rule("") == 0


class TestTotalScoring:
    """Tests para el cálculo total de scoring."""
    
    def test_all_max_scores(self):
        """Todas las reglas al máximo = score total 100."""
        scores = {
            "volume_anomaly": 100,
            "price_momentum": 100,
            "market_cap_efficiency": 100,
            "new_token": 100,
        }
        total = calculate_total_score(scores)
        assert total == 100.0
    
    def test_all_zero_scores(self):
        """Todas las reglas en 0 = score total 0."""
        scores = {
            "volume_anomaly": 0,
            "price_momentum": 0,
            "market_cap_efficiency": 0,
            "new_token": 0,
        }
        total = calculate_total_score(scores)
        assert total == 0.0
    
    def test_mixed_scores(self):
        """Scores mixtos deben dar un promedio ponderado correcto."""
        scores = {
            "volume_anomaly": 100,    # peso 0.30
            "price_momentum": 70,      # peso 0.30
            "market_cap_efficiency": 0,  # peso 0.20
            "new_token": 50,           # peso 0.20
        }
        # Esperado: (100*0.30 + 70*0.30 + 0*0.20 + 50*0.20) = 30 + 21 + 0 + 10 = 61
        total = calculate_total_score(scores)
        assert total == 61.0


class TestClassifySignal:
    """Tests para la clasificación de señales."""
    
    def test_critical(self):
        assert classify_signal(85) == "CRITICO"
    
    def test_high(self):
        assert classify_signal(65) == "ALTO"
    
    def test_medium(self):
        assert classify_signal(50) == "MEDIO"
    
    def test_low(self):
        assert classify_signal(30) is None


class TestSimulatedPump:
    """Test de integración: simula un pump real conocido."""
    
    def test_classic_pump_pattern(self):
        """
        Simula un pump clásico:
        - Volumen 4x el promedio
        - Precio subiendo 8% en 1h, 20% en 4h
        - Market cap bajo ($3M)
        - Token listado hace 2 días
        """
        now = datetime.now(timezone.utc)
        
        token = {
            "id": 1,
            "symbol": "PUMPTESTUSDT",
            "name": "PUMPTEST",
            "first_seen": (now - timedelta(days=2)).isoformat(),
        }
        
        metrics = {
            "volume_ratio": 4.0,
            "price_change_1h": 8.0,
            "price_change_4h": 20.0,
            "price_change_24h": 35.0,
            "market_cap": 3_000_000,
            "vol_7d_avg": 200_000,
        }
        
        result = score_token(token, metrics)
        
        assert result is not None
        assert result["level"] == "CRITICO"
        assert result["total_score"] >= 75
        assert "volume_anomaly" in result["triggered_rules"]
        assert "price_momentum" in result["triggered_rules"]
    
    def test_false_positive_old_token(self):
        """
        Token viejo con volumen moderado no debería ser CRITICO.
        """
        now = datetime.now(timezone.utc)
        
        token = {
            "id": 2,
            "symbol": "STABLEUSDT",
            "name": "STABLE",
            "first_seen": (now - timedelta(days=180)).isoformat(),
        }
        
        metrics = {
            "volume_ratio": 1.3,
            "price_change_1h": 1.0,
            "price_change_4h": 3.0,
            "price_change_24h": 5.0,
            "market_cap": 50_000_000,
            "vol_7d_avg": 5_000_000,
        }
        
        result = score_token(token, metrics)
        
        # No debería generar señal (score bajo)
        assert result is None


# ============================================================
# Runner
# ============================================================

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
