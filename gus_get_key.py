"""Mint a GUS.earth (gAIa) API key from your account, and offer to save it to .env.

GUS does not surface the API key in the gaia.gus.earth web UI. The key is minted
through the API: you authenticate for a short-lived bearer token, then ask the
account endpoint to create a persistent API key. This script supports both ways
in, then creates the key.

Two sign-in routes:
  A) Google sign-in (SSO): you have no GUS password. Paste the session bearer
     token your browser already holds. In gaia.gus.earth open DevTools, go to the
     Network tab, reload, click any request to backend.gus.earth/api, and copy the
     value after "Bearer " in the Authorization request header.
  B) Email + password: only if you set a GUS password directly (not Google SSO).
     The password is read with getpass and sent only to the GUS login endpoint.

Run it:
    python gus_get_key.py

It prints the new key and, if you agree, writes GUS_API_KEY=... into .env.
Docs: https://backend.gus.earth/docs
"""

from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path

import requests

BASE = "https://backend.gus.earth"
TOKEN_URL = f"{BASE}/api/v1/token"
CREATE_KEY_URL = f"{BASE}/api/v1/users/create_api_key"
ENV_PATH = Path(__file__).with_name(".env")


def _extract_key(payload) -> str | None:
    """The create_api_key response shape is not documented; look in the likely
    fields, then fall back to the first string value that looks like a key."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for k in ("api_key", "apiKey", "key", "token", "api_token", "value"):
            v = payload.get(k)
            if isinstance(v, str) and len(v) >= 12:
                return v
        for v in payload.values():
            if isinstance(v, str) and len(v) >= 16:
                return v
    return None


def _save_key(key: str) -> None:
    print(f"\nYour GUS API key: {key}")
    if not ENV_PATH.exists():
        return
    ans = input(f"\nWrite GUS_API_KEY into {ENV_PATH.name}? [y/N] ").strip().lower()
    if ans != "y":
        return
    lines = ENV_PATH.read_text().splitlines()
    wrote = False
    for i, ln in enumerate(lines):
        if ln.strip().startswith("GUS_API_KEY="):
            lines[i] = f"GUS_API_KEY={key}"; wrote = True; break
    if not wrote:
        lines.append(f"GUS_API_KEY={key}")
    ENV_PATH.write_text("\n".join(lines) + "\n")
    print(f"Saved to {ENV_PATH.name}. Verify with: python city_data.py gus")


def _token_from_password() -> str | None:
    email = input("Email: ").strip()
    password = getpass.getpass("Password (hidden): ")
    r = requests.post(TOKEN_URL, timeout=40,
                      data={"username": email, "password": password},
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    if r.status_code != 200:
        print(f"\nLogin failed ({r.status_code}). Check the email and password.")
        print(r.text[:300]); return None
    token = r.json().get("access_token")
    if not token:
        print("\nLogin returned no access_token:", r.text[:300]); return None
    print("Logged in."); return token


def main() -> int:
    print("GUS.earth API key helper.\n")
    print("Did you sign in to gaia.gus.earth with Google? [Y/n] ", end="")
    google = (input().strip().lower() or "y") == "y"

    if google:
        # Clerk session tokens live ~60s, so copy-paste loses the race. Mint the
        # persistent key from inside the logged-in page, then paste that key here.
        print("\nOn the logged-in gaia.gus.earth page, open DevTools , Console, and run:\n")
        print("  const t = await window.Clerk.session.getToken();")
        print("  const r = await fetch('https://backend.gus.earth/api/v1/users/create_api_key',")
        print("    { method:'POST', headers:{ Authorization:'Bearer '+t } });")
        print("  console.log(r.status, JSON.stringify(await r.json(), null, 2));\n")
        print("It prints your persistent API key (field api_key / key / token). Paste it here.\n")
        key = getpass.getpass("GUS API key (hidden paste): ").strip()
        if not key:
            print("No key entered."); return 1
        who = requests.get(f"{BASE}/api/v1/users/me", timeout=40,
                           headers={"X-API-Key": key})
        if who.status_code != 200:
            print(f"\nThat key was not accepted ({who.status_code}): {who.text[:200]}")
            return 1
        print("Key accepted.")
        _save_key(key)
        return 0
    else:
        token = _token_from_password()
        if not token:
            return 1

    # 2) create a persistent API key with that token
    r = requests.post(CREATE_KEY_URL, timeout=40,
                      headers={"Authorization": f"Bearer {token}"})
    if r.status_code not in (200, 201):
        print(f"\ncreate_api_key failed ({r.status_code}): {r.text[:300]}")
        return 1
    try:
        payload = r.json()
    except ValueError:
        payload = r.text
    key = _extract_key(payload)
    if not key:
        print("\nCould not find the key in the response. Raw response:")
        print(json.dumps(payload, indent=2) if isinstance(payload, (dict, list)) else payload)
        return 1

    _save_key(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
