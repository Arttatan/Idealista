"""Собрать зашифрованный список квартир для сайта по ссылке.

Пароль читается из переменной IDEALISTA_PASSWORD и никуда не записывается.
"""

import json
import os
import subprocess
import sys

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
    subprocess.run(
        ["node", "publish_vault.mjs"],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        check=True,
    )
    print(f"Сейф обновлён: {len(listings)} квартир. Пароль в файл не записан.")


if __name__ == "__main__":
    main()
