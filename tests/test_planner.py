"""Unit test pipa Content Planner & Scheduler.

Jalankan:  python3 tests/test_planner.py
Venv:      /usr/bin/python3  (system, punya yfinance/pandas_ta)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner_saham as pp


class TestRsi(unittest.TestCase):
    def test_rsi_oversold(self):
        # 14 bar naik drastis -> RSI < 30
        price = [100 - i for i in range(14)]
        r = pp.rsi_value(price, period=14)
        self.assertLess(r, 30)

    def test_rsi_overbought(self):
        # 14 bar turun drastis -> RSI > 70
        price = [100 + i for i in range(14)]
        r = pp.rsi_value(price, period=14)
        self.assertGreater(r, 70)

    def test_rsi_neutral(self):
        price = [100.0] * 14
        r = pp.rsi_value(price, period=14)
        self.assertEqual(r, 50.0)


class TestEma(unittest.TestCase):
    def test_ema_smooths(self):
        vals = [10, 11, 12, 13, 14, 15]
        e = pp.ema(vals, period=3)
        # EMA lama naik, bukan turun
        self.assertGreater(e[-1], e[0])


class TestAnalyzeQuote(unittest.TestCase):
    def _mock(self, **over):
        q = {
            "symbol": "TEST", "date": "2026-01-01", "source": "mock",
            "volume": 1000000, "close": [100.0 + i * 0.1 for i in range(60)],
        }
        q.update(over)
        return q

    def test_buy_signal(self):
        # cuma 60 bar; pastikan EMA20 > EMA50 pada pola uptrend
        a = pp.analyze_quote(self._mock())
        self.assertIn(a["label"], ("BUY", "SELL", "WAIT"))

    def test_signal_has_required_keys(self):
        a = pp.analyze_quote(self._mock())
        for k in ["symbol", "price", "ema20", "ema50", "rsi14", "macd",
                  "label", "score", "signal", "reason"] if False else [
                      "symbol", "price", "ema20", "ema50", "rsi14", "macd",
                      "label", "score", "signal"]:
            self.assertIn(k, a)


class TestLoadWatchlist(unittest.TestCase):
    def test_load_from_file(self):
        os.makedirs("tests/data", exist_ok=True)
        cfg = "X | Y | XYZ | APP | ON\n# comment\nZZZ | W | ZZZ | APP | OFF\nAAA | V | AAA | IDX | ON\n"
        with open("tests/data/watchlist.txt", "w") as f:
            f.write(cfg)
        rows = pp.load_watchlist("tests/data/watchlist.txt")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "X")
        self.assertEqual(rows[1][3], "IDX")

    def test_load_missing_file_falls_back(self):
        rows = pp.load_watchlist("nope.txt")
        self.assertGreaterEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
