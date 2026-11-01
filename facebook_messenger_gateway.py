"""
FacebookMessengerGateway — kirim notifikasi saham lewat Facebook Messenger.

Cara kerja:
• Aplikasi & Page Access Token diambil dari .env
• Kirim ke Graph API v18.0 (https://graph.facebook.com/v18.0/{page-id}/messages)
• Agar user dapat chat ke bot/Page di HP Facebook, mereka harus:
    1. Buka Facebook
    2. Cari halaman bot (misal: @SahamAlertBot)
    3. Buka chat (bukan aplikasi, tapi halaman di FB)
    4. Kirim pesan apa saja → bot akan merespons balik (2-way)
• Kirim notifikasi (push) : backend kita kirim ke Graph API, Facebook Broadcast API
  mengantarkan ke user yang follow/chat bot.

Konfigurasi .env:
  FACEBOOK_PAGE_ID=1234567890
  FACEBOOK_PAGE_ACCESS_TOKEN=<token dari App Dashboard>
  FACEBOOK_VERIFY_TOKEN=<verifikasi webhook, opsional>
  FACEBOOK_SEND_DELAY_SEC=2.0   (antrian antar kirim, hindari rate-limit)

Contoh .env.example:
  FACEBOOK_PAGE_ID=1234567890
  FACEBOOK_PAGE_ACCESS_TOKEN=[REDACTED]
  FACEBOOK_VERIFY_TOKEN=[REDACTED]
  FACEBOOK_SEND_DELAY_SEC=2.0

Cara dapat Page Access Token di Facebook:
  1. Buka https://www.facebook.com/dashboard/
  2. + Tambah Aplikasi → Pilih "Messenger" (jika belum ada)
  3. Pergi ke "Messenger" → Settings → "Page Access Token"
  4. Pilih Page yang bersangkutan → Salin token
  5. Masukkan ke .env (FACEBOOK_PAGE_ACCESS_TOKEN)

Catatan: token hanya berlaku untuk Page yang dipilih; jangan pernah commit ke repo.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Load .env (dir proyek), kalau exist
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# Also try system .env / .hermes/.env for local config
for _candidate in (Path("/home/ridho/.hermes/.env"),):
    if _candidate.exists():
        load_dotenv(_candidate, override=True)


class FacebookMessengerGateway:
    """Gateway kirim pesan ke Facebook Messenger via Graph API."""

    # Facebook Graph API version yang masih aktif (v18.0 disarankan)
    DEFAULT_VERSION = "v18.0"

    def __init__(self, page_id: str | None = None, page_access_token: str | None = None):
        self.page_id = page_id or os.getenv("FACEBOOK_PAGE_ID", "").strip()
        self.page_access_token = page_access_token or os.getenv(
            "FACEBOOK_PAGE_ACCESS_TOKEN", ""
        ).strip()
        self.verify_token = os.getenv("FACEBOOK_VERIFY_TOKEN", "").strip()
        self.send_delay = float(os.getenv("FACEBOOK_SEND_DELAY_SEC", "2.0"))

        self.base_url = f"https://graph.facebook.com/{self.DEFAULT_VERSION}"
        self._rate_limit_lock = 0.0

        self._validate_config()

    def _validate_config(self) -> None:
        if not self.page_id:
            raise ValueError("FACEBOOK_PAGE_ID belum diisi di .env")
        if not self.page_access_token:
            raise ValueError("FACEBOOK_PAGE_ACCESS_TOKEN belum diisi di .env")
        if len(self.page_access_token) < 20:
            raise ValueError("FACEBOOK_PAGE_ACCESS_TOKEN terlihat bukan token Facebook (ambil dari App Dashboard)")

    # ------------------------------------------------------------------ #
    #  Public API (kirim)                                               #
    # ------------------------------------------------------------------ #
    def send_message(self, recipient_id: str, text: str) -> dict:
        """
        Kirim text ke chat Facebook.

        Args:
            recipient_id: ID user (telefon HP) yang mengikuti/chat bot. Cara dapat ID:
                1. Chat ke Page/Page-bot, buka FB Inbox, balas pesan user lain dengan "Telepon/Balasan"
                2. Atau baca dari requests.get() 'from' field (perlu webhook setup)
            text: Isi pesan (string). *jangan* pakai karakter HTML.
        Returns:
            dict: {ok: True, recipient_id: ..., msg_id: ...}
        """
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
        }
        headers = {
            "Authorization": f"Bearer {self.page_access_token}",
            "Content-Type": "application/json",
        }
        # Rate-limit anti-flood: jeda antar kirim.
        if self.send_delay > 0:
            elapsed = time.time() - self._rate_limit_lock
            if elapsed < self.send_delay:
                time.sleep(self.send_delay - elapsed)
            self._rate_limit_lock = time.time()

        try:
            resp = requests.post(
                f"{self.base_url}/{self.page_id}/messages",
                headers=headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("recipient_id"):
                return {"ok": True, "recipient_id": data["recipient_id"], "msg_id": data.get("message_id")}
            # Facebook kadang return ok:false dengan errors array
            errs = data.get("errors", [])
            if errs:
                return {"ok": False, "error": errs[0].get("message", "Unknown"), "code": errs[0].get("code")}
            return {"ok": True, "msg": "sent"}
        except requests.RequestException as e:
            return {"ok": False, "error": f"HTTP {e}"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------------ #
    #  Helper (tidak wajib, untuk testing manual)                       #
    # ------------------------------------------------------------------ #
    def verify_endpoint(self, mode: str, token: str, challenge: str | None = None) -> str:
        """
        Webhook verification endpoint (Graph API).
        Panggil dengan GET:
          ?hub.verify_token=<token>&hub.challenge=<challenge>
        Mengembalikan challenge jika token cocok, else ''
        """
        if mode == "hub" and token == self.verify_token:
            return challenge or ""
        return ""


# ---------------------------------------------------------------------- #
#  Diagnotic / flow test                                             #
# ---------------------------------------------------------------------- #
def test_gateway():
    """Print status konfigurasi dan contoh kirim (tidak kirim data asli)."""
    gw = FacebookMessengerGateway()
    print("=== Facebook Messenger Gateway — diagnotic ===")
    print(f"  PAGE_ID           : {'OK' if gw.page_id else 'MISSING'}")
    print(f"  PAGE_ACCESS_TOKEN : {'OK (len {0})'.format(len(gw.page_access_token)) if gw.page_access_token else 'MISSING'}")
    print(f"  VERIFY_TOKEN      : {'OK' if gw.verify_token else 'optional'}")
    print(f"  SEND_DELAY_SEC    : {gw.send_delay}")
    if not gw.page_access_token:
        print("\n  >> Not configured. Isi .env: FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN")
    else:
        print("\n  >> Ready. Example recipient_id: '<PAGE_ID>|<USER_ID>'")


if __name__ == "__main__":
    test_gateway()
