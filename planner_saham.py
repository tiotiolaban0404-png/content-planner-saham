"""
content_planner_saham.py — drafts: AI Content Planner & Scheduler for
stock analysis (US + IHSG).

Pipeline:
  1. fetch (real / mock)
  2. analyze               (EMA20, EMA50, RSI14, MACD, Fibonacci, volume)
  3. content_planner       (JSON + human text, via LLM or rule fallback)
  4. deliver               (Telegram / webhook / log)
  5. schedule              (HerMES cron / crontab / Threading)

Menggunakan config_saham.txt (US + IDX). Ringkasan cuma (tanpa API key
fungsional), sehingga draft ini bisa dicoba tanpa token.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv  # noqa: E402

# ---------------------------------------------------------------------------
# konfigurasi default (dipakai kalau file .txt belum ada)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = """
# watchlist_saham.txt — format: SAPI | NAMA | TICKER | DAUR(APP/IDX) | LOCK
# US
AAPL | Apple Inc. | AAPL | APP | ON
MSFT | Microsoft Corp. | MSFT | APP | ON
GOOGL | Alphabet Inc. | GOOGL | APP | ON
AMZN | Amazon.com Inc. | AMZN | APP | ON
NVDA | NVIDIA Corp. | NVDA | APP | ON
META | Meta Platforms Inc. | META | APP | ON
NFLX | Netflix Inc. | NFLX | APP | ON
AMD | Advanced Micro Devices. | AMD | APP | ON
INTC | Intel Corp. | INTC | APP | ON
TSLA | Tesla Inc. | TSLA | APP | ON
UNH | UnitedHealth Group. | UNH | APP | ON
JPM | JPMorgan Chase & Co. | JPM | APP | ON
V | Visa Inc. | V | APP | ON
KO | The Coca-Cola Company. | KO | APP | ON
PG | Procter & Gamble Co. | PG | APP | ON
# IDX (IHSG)
BBRI | Bank Bukopin Raya. | BBRI | IDX | ON
BBCA | Bank Central Asia. | BBCA | IDX | ON
BBCT | Bank Central Asia (Tbk). | BBCT | IDX | ON
ANTM | Astra International. | ANTM | IDX | ON
TLKM | Telekomunikasi Indonesia. | TLKM | IDX | ON
MID | Media Nusantara. | MID | IDX | ON
INCO | Indosat Ooredo. | INCO | IDX | ON
UNVR | United Industries (Unilever). | UNVR | IDX | ON
ASII | Aneka Tambang. | ASII | IDX | ON
BNBR | Bakrie & Brothers. | BNBR | IDX | ON
BWPT | Eagle High Plantations. | BWPT | IDX | ON
SUB | Sukanto Tanoto. | SUB | IDX | ON
MHET | Metro Retail. | MHET | IDX | ON
SMPL | Simpati Park. | SMPL | IDX | ON
DMAP | Dompet Dhufa. | DMAP | IDX | ON
ICOM | Titan International. | ICOM | IDX | ON
"""

# ---------------------------------------------------------------------------
# 1. fetch
# ---------------------------------------------------------------------------
def _fallback_quote(symbol, market, source, error=None):
    """Mock fallback: dipakai kalau yfinance/finnhub gagal atau data tidak ada."""
    import random
    random.seed(hash(symbol + source))
    base = 100 + (hash(symbol) % 200) / 50.0
    close = []
    p = base
    for _ in range(60):
        p = max(1, p + (random.random() - 0.48) * 3.0)
        close.append(round(p, 2))
    last = close[-1]
    return {
        "symbol": symbol, "date": "01 Januari 2026", "close": close,
        "open": round(last - 1.2, 2), "high": round(last + 1.8, 2),
        "low": round(last - 1.6, 2),
        "volume": 1000000 + hash(symbol) % 9000000, "change_percent": 1.2,
        "source": source, "error": error,
    }


def fetch_quote(symbol: str, market: str = "APP", source: str = "yfinance"):
    """
    Fetch quote ASLI via yfinance (Yahoo Finance).

    • AAPL / MSFT (US)  -> yahoo symbol = symbol (mis. "AAPL")
    • BBRI / BBCA (IDX) -> yahoo symbol = f"{symbol}.JK"

    Gagal (404 / no data / timeout): fallback ke mock supaya pipeline tetap jalan.
    """
    yahoo_symbol = symbol if market.strip().upper() == "APP" else f"{symbol}.JK"

    try:
        import yfinance as yf  # noqa: F401
    except ImportError:  # pragma: no cover
        return _fallback_quote(symbol, market, source, error="yfinance not installed; using mock")

    try:
        t = yf.Ticker(yahoo_symbol)
        hist = t.history(period="60d", interval="1d")
        if hist.empty:
            return _fallback_quote(symbol, market, source, error=f"no data for {yahoo_symbol}")

        close = [round(float(v), 2) for v in hist["Close"]]
        open_ = close[0]
        info = t.info or {}
        prev_close = info.get("previousClose") or close[-1]
        curr = close[-1]
        change_percent = round((curr - prev_close) / prev_close * 100.0, 2) if prev_close else 0.0
        volume = int(hist["Volume"].iloc[-1]) if len(hist) else 0
        return {
            "symbol": symbol,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "close": close,
            "open": round(float(open_), 2),
            "high": round(float(hist["High"].iloc[-1]), 2),
            "low": round(float(hist["Low"].iloc[-1]), 2),
            "volume": volume,
            "change_percent": change_percent,
            "source": source,
            "error": None,
        }
    except Exception as e:  # noqa: BLE001
        return _fallback_quote(symbol, market, source, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 2. analyze (multi-emiten)
# ---------------------------------------------------------------------------
def rsi_value(price, period=14):
    """
    RSI simpel (no-alt). Mengambil data close thn 14, perbarui gain/loss.
    """
    idx = max(1, len(price) - period)
    run_up, run_down = 0.0, 0.0
    for i in range(idx, min(idx + period, len(price))):
        delta = price[i] - price[i - 1]
        run_up += max(delta, 0.0) / period
        run_down += max(-delta, 0.0) / period
    return round(100 - 100 / (1 + run_up / (run_down + 1e-9)), 2) if (run_up + run_down) else 50.0


def analyze_quote(q, period=14):
    """
    Multi-emiten: EMA20, EMA50, RSI14, MACD, Fibonacci.
    Return dict + label BUY/SELL/WAIT + score.
    """
    close = q.get("close", [])
    if isinstance(close, (int, float)):
        # single bar (mock real API), buat tingkat minor 14 hari
        close = [float(close)] * 60

    # EMA20 / EMA50 / MACD (gain & loss) — semua bersifat list
    e20 = ema(close, 20)
    e50 = ema(close, 50)
    e12 = ema(close, 12)
    e26 = ema(close, 26)
    macd_level = e12[-1] - e26[-1]

    rsi14 = rsi_value(close, 14)
    fib = close[-1] - (close[-1] - close[0]) * 0.618 if len(close) >= 2 else 0.0

    signal = "WAIT"
    score = 50
    reasons = []

    # EMA20 vs EMA50 (golden/death cross)
    if len(close) >= 2:
        if e20[-1] > e50[-1] and close[-1] > e20[-1]:
            signal = "BUY"
            reasons.append("golden-cross")
        elif e20[-1] < e50[-1] and close[-1] < e20[-1]:
            signal = "SELL"
            reasons.append("death-cross")

    # RSI
    if rsi14 > 70:
        reasons.append("overbought")
    elif rsi14 < 30:
        reasons.append("oversold")

    # MACD
    if macd_level > 0:
        reasons.append("macd_positive")

    if signal == "WAIT":
        score = 50
        label = "WAIT"
    elif signal == "BUY":
        label = "BUY"
        score = max(51, min(85, 50 + rsi14 - 50))
        signal = "BUY"
    else:
        label = "SELL"
        score = min(49, max(15, 50 - rsi14 - 50))

    score = round(score, 1)
    reasons = list(dict.fromkeys(reasons))

    return {
        "symbol": q.get("symbol", ""),
        "date": q.get("date", ""),
        "price": round(float(close[-1]), 2),
        "open": round(float(close[0] - 1.2), 2),
        "volume": int(q.get("volume", 0)),
        "ema20": round(float(e20[-1]) if isinstance(e20, list) else e20, 2),
        "ema50": round(float(e50[-1]) if isinstance(e50, list) else e50, 2),
        "rsi14": round(float(rsi14), 2),
        "macd": round(float(macd_level), 2),
        "macd_signal": "positive" if macd_level > 0 else "negative",
        "fib_618": round(float(fib), 2),
        "label": label,
        "score": score,
        "reasons": reasons,
        "signal": signal,
    }


def ema(values, period):
    """EMA existing per bar; returns list."""
    if not values:
        return []
    alpha = 2 / (period + 1)
    e = [float(values[0])]
    for v in values[1:]:
        e.append(v * alpha + e[-1] * (1 - alpha))
    return e


# ---------------------------------------------------------------------------
# 3. Content planner (LLM) + fallback rules
# ---------------------------------------------------------------------------
def planner_json(signal, price, rsi, macd, ema20, ema50, label, score, reasons):
    """
    Format JSON siap dikirim ke LLM. LLM akan overload & drop reason.
    """
    return {
        "ts": 0.0,
        "symbol": signal,
        "label": label,
        "score": score,
        "price": price,
        "rsi14": rsi,
        "macd": macd,
        "ema20": ema20,
        "ema50": ema50,
        "indicators": ["EMA20", "EMA50", "RSI14", "MACD", "Fibonacci", "volume"],
        "warnings": [],
        "action": label.lower(),
        "sentimen": "positive" if label == "BUY" else ("negative" if label == "SELL" else "neutral"),
        "conclusion": "Content drafted by Content Planner & Scheduler.",
        "promise": "This is an analytical draft, not financial advice.",
    }


def content_planner(signal, reason):
    """
    LLM override (mock). Penalakan: prompt berformat, bukan free text.
    """
    return {
        "title": f"[{signal['label']}] {signal['symbol']} (rsi{rsi}, ema20 {ema}, macd {macd})",
        "body": f"{signal['symbol']} menunjukkan {reason}, terlihat bullish/bearish.",
        "action": signal["label"].lower(),
        "reason": "; ".join(signal["reasons"]) or "neutral momentum",
        "score": signal["score"],
    }


def craft_content(signal):
    """Unified human-readable + JSON content."""
    label, score = signal["label"], signal["score"]
    s = signal["reasons"][0] if signal["reasons"] else "netral"
    if label == "BUY":
        txt = f"BUY • {signal['symbol']} — price {signal['price']} (RSI {signal['rsi14']}, score {score:.0f})"
    elif label == "SELL":
        txt = f"SELL • {signal['symbol']} — price {signal['price']} (RSI {signal['rsi14']}, score {score:.0f})"
    else:
        txt = f"WAIT • {signal['symbol']} — price {signal['price']} (RSI {signal['rsi14']}, score {score:.0f})"
    return {
        "text": txt,
        "reason": "; ".join(signal["reasons"]),
        "score": score,
        "summary": f"{signal['symbol']} {label} = {score:.0f} (awk {s})",
    }


# ---------------------------------------------------------------------------
# 4. Deliver
# ---------------------------------------------------------------------------
def _load_env_if_needed() -> None:
    """Load .env (dotenv). Called once lazily."""
    load_dotenv()


def deliver_telegram(content, telegram_chat_id=None):
    """
    Deliver ke Telegram Bot API.

    Membaca TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID dari file .env (dotenv).
    Kalau konfigurasi belum ada, fallback ke print (terminal) supaya pipeline tetap jalan.
    """
    _load_env_if_needed()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print(f"[TELEMGR] SKIP: TELEGRAM_BOT_TOKEN not set; message not sent.")
        return

    chat_id = telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        print(f"[TELEMGR] SKIP: TELEGRAM_CHAT_ID not set; message not sent.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = f"📈 {content['text']}\n📊 {content['summary']}\n⚠️ {content['reason']}"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        resp = requests.post(url, data=payload, timeout=15)
        if resp.status_code == 200:
            print(f"[TELEMGR] SENT ok to chat_id {chat_id}")
        else:
            print(f"[TELEMGR] FAIL HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:  # noqa: BLE001
        print(f"[TELEMGR] ERROR: {e}")


# ---------------------------------------------------------------------------
# 5. Scheduler
# ---------------------------------------------------------------------------
def run_pipeline(watchlist_config, dry_run=False, source: str = "yfinance", delay: float = 1.5):
    """
    Core loop. delay = jeda (detik) antar ticker supaya Yahoo Finance tidak rate-limit.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n=== content_planner_saham run: {now} ===")

    for sym, name, ticker, market, lock in watchlist_config:
        if lock.strip() != "ON":
            continue
        try:
            q = fetch_quote(ticker, market=market, source=source)
            a = analyze_quote(q)
            c = craft_content(a)
            print(f"[{q.get('symbol')}] {c['text']}  ({c['summary']})")
            if not dry_run:
                deliver_telegram(c)
        except Exception as e:
            print(f"[{ticker}] ERROR: {e}")
        time.sleep(delay)


def schedule_cron_hermes(description="daily stock planner", internal="", schedule="0 7 * * *"):
    """Return config block usable in Hermes cron / crontab."""
    # schedule time example: 0 7 * * * = 07:00 WIB (00:00 UTC)
    return f"0 7 * * * cd {os.getcwd()} && python3 planner_saham.py sched 08 00"


# --- CLI / local test ---
def load_watchlist(path: str = "config_saham.txt"):
    """
    Baca config_saham.txt -> list of (SAPI, NAMA, TICKER, MARKET, LOCK).
    # comment lines skipped; baris kosong diabaikan.
    Kalau file belum ada, fallback ke DEFAULT_CONFIG (tabel bawaan).
    """
    cfg = ""
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg = f.read()
    else:
        cfg = DEFAULT_CONFIG

    _rows = [l.split("|") for l in cfg.strip().splitlines()
             if "|" in l and not l.strip().startswith("#")]
    _data = [tuple(r) for r in _rows if len(r) == 5]
    _data = [(a.strip(), b.strip(), c.strip(), d.strip(), e.strip())
             for a, b, c, d, e in _data]
    _data = [r for r in _data if r[4] == "ON"]
    return _data


def main():
    print("✨ Content Planner & Scheduler — processing watchlist (real data via yfinance).")
    print("   Edit `fetch_quote()` → ganti ke Finnhub / IDX broker lain.")

    _data = load_watchlist("config_saham.txt")
    run_pipeline(_data)


if __name__ == "__main__":
    main()
