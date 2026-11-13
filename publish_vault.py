"""Собрать зашифрованный список квартир для сайта по ссылке.

Пароль читается из переменной IDEALISTA_PASSWORD и никуда не записывается.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from serve import all_listings, load_rates


def main() -> None:
    password = os.environ.get("IDEALISTA_PASSWORD", "")
    if len(password) < 10:
        raise SystemExit("Задайте длинный IDEALISTA_PASSWORD. В репозиторий он не записывается.")
    rates = load_rates()
    listings = all_listings()
    payload = {
        "count": len(listings),
        "rates": {
            "source": rates.get("source") or "",
            "source_url": rates.get("source_url") or "",
            "checked": rates.get("checked") or "",
            "period": rates.get("period") or "",
        },
        "listings": listings,
    }
    env = os.environ.copy()
    sync_path = Path(__file__).resolve().parent / "data" / "sync.json"
    if sync_path.exists() and not env.get("IDEALISTA_GIST_ID"):
        sync = json.loads(sync_path.read_text(encoding="utf-8"))
        if sync.get("gistId"):
            env["IDEALISTA_GIST_ID"] = sync["gistId"]
        if sync.get("fileName"):
            env["IDEALISTA_GIST_FILE"] = sync["fileName"]
    if not env.get("IDEALISTA_SYNC_TOKEN"):
        try:
            token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
            if token:
                env["IDEALISTA_SYNC_TOKEN"] = token
        except Exception:
            pass
    subprocess.run(
        ["node", "publish_vault.mjs"],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        check=True,
        env=env,
    )
    print(f"Сейф обновлён: {len(listings)} квартир. Пароль в файл не записан.")
    if env.get("IDEALISTA_SYNC_TOKEN") and env.get("IDEALISTA_GIST_ID"):
        subprocess.run(["python", "sync_notes.py"], check=True, env=env)
        print("Общие заметки синхронизированы.")


if __name__ == "__main__":
    main()
