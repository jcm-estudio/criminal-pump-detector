"""
Tests para el motor de Paper Trading simulado.
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import src.paper_trader as paper_trader
from src.config import TP1_PERCENT, STOP_LOSS_PERCENT, TIME_STOP_HOURS

class TestPaperTrader(unittest.TestCase):

    @patch("src.paper_trader.db")
    @patch("src.paper_trader.PAPER_TRADING", True)
    @patch("src.paper_trader.MAX_OPEN_POSITIONS", 3)
    @patch("src.paper_trader.MAX_DAILY_TRADES", 5)
    def test_process_new_signals_open_trade(self, mock_db):
        # Setup mocks
        mock_db.get_open_paper_trades.return_value = []
        mock_db.get_daily_trades_count.return_value = 0
        mock_db.get_price_history.return_value = [{"price": 10.0}]
        mock_db.insert_paper_trade.return_value = 1
        
        signals = [
            {"token_id": 100, "symbol": "TESTUSDT", "level": "CRITICO", "signal_id": 10}
        ]
        
        opened = paper_trader.process_new_signals(signals)
        
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["symbol"], "TESTUSDT")
        self.assertEqual(opened[0]["entry_price"], 10.0)
        mock_db.insert_paper_trade.assert_called_once()


    @patch("src.paper_trader.db")
    @patch("src.paper_trader.PAPER_TRADING", True)
    def test_process_new_signals_ignores_medium(self, mock_db):
        mock_db.get_open_paper_trades.return_value = []
        mock_db.get_daily_trades_count.return_value = 0
        
        signals = [
            {"token_id": 100, "symbol": "TESTUSDT", "level": "MEDIO", "signal_id": 10}
        ]
        
        opened = paper_trader.process_new_signals(signals)
        self.assertEqual(len(opened), 0)


    @patch("src.paper_trader.db")
    @patch("src.paper_trader.PAPER_TRADING", True)
    @patch("src.paper_trader.MAX_OPEN_POSITIONS", 1)
    def test_process_new_signals_max_positions_limit(self, mock_db):
        # Setup mock to simulate 1 open position already
        mock_db.get_open_paper_trades.return_value = [{"token_id": 99}]
        mock_db.get_daily_trades_count.return_value = 0
        
        signals = [
            {"token_id": 100, "symbol": "TESTUSDT", "level": "CRITICO", "signal_id": 10}
        ]
        
        opened = paper_trader.process_new_signals(signals)
        self.assertEqual(len(opened), 0) # Limit is 1, so it shouldn't open


    @patch("src.paper_trader.db")
    @patch("src.paper_trader.PAPER_TRADING", True)
    def test_update_open_trades_take_profit(self, mock_db):
        now = datetime.now(timezone.utc).isoformat()
        
        # Simulate open trade at $10
        open_trades = [{
            "id": 1, "token_id": 100, "symbol": "TESTUSDT",
            "entry_price": 10.0, "amount_usd": 50.0, "entry_time": now
        }]
        mock_db.get_open_paper_trades.return_value = open_trades
        
        # Current price hits TP1 (e.g. +50% -> $15)
        tp_price = 10.0 * (1 + (TP1_PERCENT / 100.0))
        mock_db.get_price_history.return_value = [{"price": tp_price}]
        
        closed = paper_trader.update_open_trades()
        
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["exit_reason"], "TAKE_PROFIT")
        self.assertGreaterEqual(closed[0]["pnl_percent"], TP1_PERCENT)
        mock_db.close_paper_trade.assert_called_once()


    @patch("src.paper_trader.db")
    @patch("src.paper_trader.PAPER_TRADING", True)
    def test_update_open_trades_stop_loss(self, mock_db):
        now = datetime.now(timezone.utc).isoformat()
        
        open_trades = [{
            "id": 1, "token_id": 100, "symbol": "TESTUSDT",
            "entry_price": 10.0, "amount_usd": 50.0, "entry_time": now
        }]
        mock_db.get_open_paper_trades.return_value = open_trades
        
        # Current price hits SL (e.g. -15% -> $8.5)
        sl_price = 10.0 * (1 + (STOP_LOSS_PERCENT / 100.0))
        mock_db.get_price_history.return_value = [{"price": sl_price}]
        
        closed = paper_trader.update_open_trades()
        
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["exit_reason"], "STOP_LOSS")
        self.assertLessEqual(closed[0]["pnl_percent"], STOP_LOSS_PERCENT)


    @patch("src.paper_trader.db")
    @patch("src.paper_trader.PAPER_TRADING", True)
    def test_update_open_trades_time_stop(self, mock_db):
        # Trade opened 25 hours ago
        past_time = datetime.now(timezone.utc) - timedelta(hours=TIME_STOP_HOURS + 1)
        past_iso = past_time.isoformat()
        
        open_trades = [{
            "id": 1, "token_id": 100, "symbol": "TESTUSDT",
            "entry_price": 10.0, "amount_usd": 50.0, "entry_time": past_iso
        }]
        mock_db.get_open_paper_trades.return_value = open_trades
        
        # Price hasn't moved much (no SL or TP)
        mock_db.get_price_history.return_value = [{"price": 10.1}]
        
        closed = paper_trader.update_open_trades()
        
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["exit_reason"], "TIME_STOP")


if __name__ == '__main__':
    unittest.main()
