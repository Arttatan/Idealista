# -*- coding: utf-8 -*-
"""Зашифровать data/user_notes.json и залить в GitHub Gist для общего доступа."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTES_PATH = ROOT / "data" / "user_notes.json"
SYNC_PATH = ROOT / "data" / "sync.json"


def load_notes() -> dict:
    if not NOTES_PATH.exists():
        return {}
    raw = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    out = {}
    now = int(time.time() * 1000)
    for key, value in raw.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        item = dict(value)
        item["_ts"] = int(item.get("_ts") or now)
        out[str(key)] = item
    return out


def encrypt_payload(password: str, payload: dict) -> dict:
    proc = subprocess.run(
        ["node", "encrypt_json.mjs"],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        check=False,
        cwd=ROOT,
        env={**os.environ, "IDEALISTA_PASSWORD": password},
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.decode("utf-8", errors="replace") or "encrypt failed")
    return json.loads(proc.stdout.decode("utf-8"))


def gist_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    # Надёжнее через gh: на части Windows urllib падает на SSL.
    gist_id = url.rstrip("/").split("/")[-1]
    args = ["gh", "api", "-X", method, f"gists/{gist_id}", "-H", "Accept: application/vnd.github+json"]
    if payload is not None:
        args.extend(["--input", "-"])
        proc = subprocess.run(
            args,
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            check=False,
        )
    else:
        proc = subprocess.run(args, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.decode("utf-8", errors="replace") or "gh api failed")
    body = proc.stdout.decode("utf-8")
    return json.loads(body) if body else {}


def main() -> None:
    password = os.environ.get("IDEALISTA_PASSWORD", "")
    token = os.environ.get("IDEALISTA_SYNC_TOKEN", "")
    if len(password) < 10:
        raise SystemExit("Нужен IDEALISTA_PASSWORD")
    if not token:
        raise SystemExit("Нужен IDEALISTA_SYNC_TOKEN (gh auth token)")
    sync = json.loads(SYNC_PATH.read_text(encoding="utf-8")) if SYNC_PATH.exists() else {}
    gist_id = os.environ.get("IDEALISTA_GIST_ID") or sync.get("gistId")
    file_name = sync.get("fileName") or "notes.vault.json"
    if not gist_id:
        raise SystemExit("Нет gistId в data/sync.json")

    notes = load_notes()
    payload = {
        "v": 1,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "notes": notes,
    }
    encrypted = encrypt_payload(password, payload)
    files = {file_name: {"content": json.dumps(encrypted, ensure_ascii=False)}}
    gist_request("PATCH", f"https://api.github.com/gists/{gist_id}", token, {"files": files})
    SYNC_PATH.write_text(
        json.dumps({"gistId": gist_id, "fileName": file_name}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Заметки отправлены в gist {gist_id}: {len(notes)} квартир")


if __name__ == "__main__":
    main()
