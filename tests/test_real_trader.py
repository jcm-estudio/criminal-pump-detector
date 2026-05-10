"""
Tests para el motor de Trading Real.
Valida la generación de firmas criptográficas y la lógica de órdenes.
"""

import unittest
from unittest.mock import patch, MagicMock

import src.real_trader as real_trader

class TestRealTrader(unittest.TestCase):

    @patch("src.real_trader.MEXC_API_SECRET", "test_secret")
    def test_generate_signature(self):
        query_string = "symbol=BTCUSDT&side=BUY&type=MARKET&timestamp=1620000000000"
        # HMAC SHA256 pre-calculado para ("test_secret", query_string)
        signature = real_trader._generate_signature(query_string)
        
        self.assertIsInstance(signature, str)
        self.assertEqual(len(signature), 64) # SHA256 hex tiene 64 chars


    @patch("src.real_trader.requests.get")
    @patch("src.real_trader.MEXC_API_KEY", "test_key")
    @patch("src.real_trader.MEXC_API_SECRET", "test_secret")
    def test_get_account_balance(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "balances": [
                {"asset": "BTC", "free": "0.5"},
                {"asset": "USDT", "free": "150.0"}
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        balance = real_trader.get_account_balance("USDT")
        
        self.assertEqual(balance, 150.0)
        mock_get.assert_called_once()


    @patch("src.real_trader.requests.post")
    @patch("src.real_trader.MEXC_API_KEY", "test_key")
    @patch("src.real_trader.MEXC_API_SECRET", "test_secret")
    def test_place_market_order_buy(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"orderId": "123456", "symbol": "TESTUSDT"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        res = real_trader.place_market_order("TESTUSDT", "BUY", quote_order_qty=50)
        
        self.assertIsNotNone(res)
        self.assertEqual(res["orderId"], "123456")
        
        # Verificar que post fue llamado con la URL correcta
        args, kwargs = mock_post.call_args
        self.assertIn("quoteOrderQty=50", args[0])
        self.assertIn("side=BUY", args[0])


    @patch("src.real_trader.get_account_balance")
    @patch("src.real_trader.place_market_order")
    @patch("src.real_trader.send_trade_alert")
    def test_process_new_signals_success(self, mock_send_alert, mock_place_order, mock_get_balance):
        # Setup mocks
        mock_get_balance.return_value = 100.0 # Fondos suficientes (MAX_TRADE_USD=50 default)
        mock_place_order.return_value = {"orderId": "777"}
        
        signals = [
            {"symbol": "PUMPUSDT", "level": "CRITICO"}
        ]
        
        opened = real_trader.process_new_signals(signals)
        
        self.assertEqual(len(opened), 1)
        mock_place_order.assert_called_once_with(
            symbol="PUMPUSDT", side="BUY", quote_order_qty=real_trader.MAX_TRADE_USD
        )
        mock_send_alert.assert_called_once()


    @patch("src.real_trader.get_account_balance")
    @patch("src.real_trader.place_market_order")
    def test_process_new_signals_insufficient_funds(self, mock_place_order, mock_get_balance):
        # Setup mocks
        mock_get_balance.return_value = 10.0 # Fondos insuficientes (MAX_TRADE_USD=50 default)
        
        signals = [
            {"symbol": "PUMPUSDT", "level": "CRITICO"}
        ]
        
        opened = real_trader.process_new_signals(signals)
        
        self.assertEqual(len(opened), 0)
        mock_place_order.assert_not_called()


if __name__ == '__main__':
    unittest.main()
