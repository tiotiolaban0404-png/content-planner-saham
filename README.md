# Content Planner & Scheduler — Analisis Saham US + IHSG

Pipeline yang memindai watchlist saham (US + IDX), menghitung sinyal teknis
(EMA20/EMA50, MACD, RSI14, Fibonacci), menghasilkan konten BUY/SELL/WAIT, lalu
mengirim lewat Telegram. Dirancang *offline* dulu (data simulasi), kemudian
ditukar ke data riil.

## Arsitektur (5 langkah)

```
1. fetch   → yfinance (real) / fallback mock
2. analyze → EMA20, EMA50, MACD, RSI14, Fibonacci → JSON {signal, label, score, ...}
3. content → JSON teks manusia + ringkasan (rule fallback; LLM dipisah nanti)
4. deliver → Telegram Bot API (via .env) / webhook / log
5. schedule → cron / crontab / Threading
```

## File Projek

| File | Tujuan |
|------|--------|
| `planner_saham.py` | Scaffold pipeline (fetch → analyze → content → deliver → schedule) |
| `config_saham.txt` | Watchlist 30 ticker (15 US + 16 IDX) |
| `.env.example` | Contoh variabel rahasia (fill lalu rename `.env`) |
| `.gitignore` | Melindungi `.env`, `.txt.local`, `__pycache__` |
| `requirements.txt` | Daftar library wajib |
| `tests/test_planner.py` | Unit test pipa (fetch/analyze/deliver hook) |

## Instalasi

```bash
# 1. Clone & masuk folder
git clone <repo> && cd content_planner_saham

# 2. Pasang library (python3 system Ubuntu/Debian)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Konfigurasi rahasia (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
cp .env.example .env
# edit .env, sesuaikan TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
```

> Catatan: python3 system Ubuntu/Debian (`/usr/bin/python3`) sudah punya
> `yfinance`, `pandas`, `pandas_ta`, `requests`, `python-dotenv`. Venv di atas
> hanyalah referensi; project ini dijalankan langsung pakai `python3`.

## Cara Pakai

```bash
# 1. Jalankan lokal (baca config_saham.txt, filter LOCK=ON)
python3 planner_saham.py

# 2. Mode dry-run (tidak kirim ke Telegram)
python3 planner_saham.py --dry-run

# 3. Schedule otomatis 08:00 WIB
crontab -l | { cat; echo "0 1 * * * cd /home/ridho/Downloads/content_planner_saham && /usr/bin/python3 planner_saham.py >> logs/cron.log 2>&1"; } | crontab -
```

> Schedule: `0 1 * * *` = 01:00 UTC = **08:00 WIB** (sesuai jam IHSG session).

## Sinyal & Penilaian

| Label | Arti |
|-------|------|
| `BUY` | Bullish (golden-cross, overbought → value) |
| `SELL` | Bearish (death-cross, oversold) |
| `WAIT` | Netral / pending (macd/ratio belum klar) |

`score` (0–100) memperkuat keputusan. `reasons` mencatat indikator yang
memicu sinyal (contoh: `golden-cross`, `overbought`, `macd_positive`).

## Konfigurasi Provider

`fetch_quote(symbol, market, source)` adalah titik tunggal yang perlu diubah:

- `market="APP"` → ticker aslinya (AAPL, MSFT...)
- `market="IDX"` → `f"{symbol}.JK"` (BBRI.JK, BBCA.JK... pada Yahoo)
- `source` → `"yfinance"`, `"finnhub"`, atau `"idx"`.

Gagal (404 / no data / timeout) → otomatis fallback ke mock, pipeline tetap jalan.

## Lisensi

MIT
