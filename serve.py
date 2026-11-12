# -*- coding: utf-8 -*-
"""Локальный сайт с квартирами. Запуск: python serve.py"""

from __future__ import annotations

import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlparse

from idealista_watch import DATA, LISTINGS_PATH, load_json, merge_saved_fields, render_workbook
from rent_estimate import estimate_listing, load_rates

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
NOTES_PATH = DATA / "user_notes.json"
HOST = "127.0.0.1"
PORT = 8765
LOCK = threading.Lock()

NOTE_DEFAULTS = {
    "Просмотрено": "Нет",
    "Запланирован визит": "Нет",
    "Дата визита": "",
    "Приоритет": "",
    "Статус": "Новая",
    "Заметки": "",
    "Плюсы": "",
    "Минусы": "",
    "Причина отказа": "",
    "Телефон": "",
    "Избранное": False,
}

FACT_FIELDS = [
    ("Квартира", "Квартира"),
    ("Округ", "Округ"),
    ("Адрес или ориентир", "Адрес или ориентир"),
    ("Этаж", "Этаж"),
    ("Лифт", "Лифт"),
    ("Энергогруппа", "Энергогруппа"),
    ("Парковка", "Парковка"),
    ("Балкон или терраса", "Балкон или терраса"),
    ("Сдана арендаторам", "Сдана арендаторам"),
    ("Добавлено", "Добавлено"),
    ("Агентство", "Агентство"),
    ("Страница агентства", "Страница агентства"),
    ("Район по услугам", "Район по услугам"),
    ("Балл удобства", "Балл удобства"),
    ("Магазины", "Магазины"),
    ("Аптеки", "Аптеки"),
    ("Школы", "Школы"),
    ("Детские сады", "Детские сады"),
    ("Транспорт", "Транспорт"),
    ("Парк", "Парк"),
    ("Медицина", "Медицина"),
]

NOTES_ABOUT = "Ручные пометки сайта. idealista_watch.py этот файл не перезаписывает."


def photo_of(row: dict) -> str | None:
    for key in ("Фото", "photo", "image", "thumbnail", "img"):
        value = row.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    for key in ("photos", "images"):
        value = row.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str) and first.startswith(("http://", "https://")):
                return first
            if isinstance(first, dict):
                url = first.get("url") or first.get("src")
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    return url
    return None


def coordinates(row: dict) -> tuple[float | None, float | None]:
    try:
        lat = float(row.get("Широта"))
        lon = float(row.get("Долгота"))
    except (TypeError, ValueError):
        return None, None
    if not (40 <= lat <= 43 and -10 <= lon <= -6):
        return None, None
    return lat, lon


def load_notes() -> dict:
    if not NOTES_PATH.exists():
        return {"_meta": {"about": NOTES_ABOUT}}
    try:
        with NOTES_PATH.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"_meta": {"about": NOTES_ABOUT}}
    return payload if isinstance(payload, dict) else {"_meta": {"about": NOTES_ABOUT}}


def save_notes(notes: dict) -> None:
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = NOTES_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(notes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(NOTES_PATH)


def merge_notes(row: dict, saved_all: dict) -> dict:
    notes = dict(NOTE_DEFAULTS)
    for key in NOTE_DEFAULTS:
        if key == "Избранное":
            continue
        value = row.get(key)
        if value not in (None, ""):
            notes[key] = str(value)
    saved = saved_all.get(str(row.get("ID") or ""))
    if isinstance(saved, dict):
        for key in NOTE_DEFAULTS:
            if key not in saved or saved[key] is None:
                continue
            notes[key] = bool(saved[key]) if key == "Избранное" else str(saved[key])
    if not notes["Статус"]:
        notes["Статус"] = "Новая"
    return notes


def listing_payload(row: dict, notes_all: dict) -> dict:
    lat, lon = coordinates(row)
    try:
        price = int(row.get("Цена €"))
    except (TypeError, ValueError):
        price = None
    facts = []
    for key, label in FACT_FIELDS:
        raw = row.get(key)
        if raw in (None, ""):
            continue
        text = str(raw).strip()
        if not text:
            continue
        fact = {"label": label, "value": text}
        if text.startswith(("http://", "https://")):
            fact["href"] = text
        facts.append(fact)
    city = str(row.get("Город") or "").strip()
    neighborhood = str(row.get("Район") or "").strip()
    return {
        "id": str(row.get("ID") or ""),
        "url": str(row.get("Ссылка") or ""),
        "city": city,
        "neighborhood": neighborhood,
        "district": str(row.get("Округ") or "").strip(),
        "place": " · ".join(part for part in (city, neighborhood) if part),
        "address": str(row.get("Адрес или ориентир") or "").strip(),
        "kind": str(row.get("Квартира") or "").strip(),
        "agency": str(row.get("Агентство") or "").strip(),
        "price": price,
        "condition": str(row.get("Состояние") or "").strip(),
        "energy": str(row.get("Энергокласс") or "").strip(),
        "year": str(row.get("Год постройки") or "").strip(),
        "added": str(row.get("Добавлено") or "").strip(),
        "parking": str(row.get("Парковка") or "").strip(),
        "lift": str(row.get("Лифт") or "").strip(),
        "tenant": str(row.get("Сдана арендаторам") or "").strip(),
        "photo": photo_of(row),
        "lat": lat,
        "lon": lon,
        "rent": estimate_listing(row),
        "facts": facts,
        "notes": merge_notes(row, notes_all),
    }


def all_listings() -> list[dict]:
    notes = load_notes()
    rows = load_json(LISTINGS_PATH, [])
    return [listing_payload(row, notes) for row in rows if isinstance(row, dict)]


def update_note(listing_id: str, patch: dict) -> dict:
    clean = {}
    for key in NOTE_DEFAULTS:
        if key not in patch:
            continue
        value = patch[key]
        if key == "Избранное":
            clean[key] = bool(value)
        else:
            clean[key] = str("" if value is None else value)[:4000]
    with LOCK:
        notes = load_notes()
        if not isinstance(notes.get("_meta"), dict):
            notes["_meta"] = {"about": NOTES_ABOUT}
        current = notes.get(listing_id)
        if not isinstance(current, dict):
            current = {}
        current.update(clean)
        notes[listing_id] = current
        save_notes(notes)
        return dict(current)


def export_xlsx() -> bytes:
    rows = load_json(LISTINGS_PATH, [])
    merge_saved_fields(rows)
    buffer = BytesIO()
    render_workbook(rows).save(buffer)
    return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, code: int, body: bytes | str, content_type: str, extra: dict | None = None) -> None:
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def _file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._send(404, "Не найдено", "text/plain; charset=utf-8")
            return
        self._send(200, path.read_bytes(), content_type)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/listings":
            rates = load_rates()
            listings = all_listings()
            self._json(200, {
                "count": len(listings),
                "rates": {
                    "source": rates.get("source") or "",
                    "source_url": rates.get("source_url") or "",
                    "checked": rates.get("checked") or "",
                    "period": rates.get("period") or "",
                },
                "listings": listings,
            })
            return
        if path == "/api/export.xlsx":
            try:
                payload = export_xlsx()
            except Exception as exc:  # noqa: BLE001 — файл Excel может быть занят
                self._json(500, {"error": f"Не удалось собрать Excel: {exc}"})
                return
            filename = quote("Квартиры_Порту_Брага.xlsx")
            self._send(
                200,
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
            )
            return
        files = {
            "/": (WEB / "index.html", "text/html; charset=utf-8"),
            "/index.html": (WEB / "index.html", "text/html; charset=utf-8"),
            "/app.css": (WEB / "app.css", "text/css; charset=utf-8"),
            "/app.js": (WEB / "app.js", "text/javascript; charset=utf-8"),
        }
        if path in files:
            self._file(*files[path])
            return
        self._send(404, "Не найдено", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/notes":
            self._send(404, "Не найдено", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 200_000:
            self._json(400, {"error": "Пустой или слишком большой запрос"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "Не JSON"})
            return
        listing_id = str(payload.get("id") or "")
        if not re.fullmatch(r"\d{5,12}", listing_id):
            self._json(400, {"error": "Неизвестный id"})
            return
        patch = payload.get("notes")
        if not isinstance(patch, dict):
            self._json(400, {"error": "Нет полей"})
            return
        rows = [row for row in load_json(LISTINGS_PATH, []) if isinstance(row, dict)]
        row = next((item for item in rows if str(item.get("ID")) == listing_id), None)
        if row is None:
            self._json(404, {"error": "Объявления нет в базе"})
            return
        saved = update_note(listing_id, patch)
        self._json(200, {"ok": True, "notes": merge_notes(row, {listing_id: saved})})


def main() -> None:
    class Server(ThreadingHTTPServer):
        allow_reuse_address = True

    try:
        server = Server((HOST, PORT), Handler)
    except OSError as exc:
        raise SystemExit(f"Порт {PORT} занят ({exc}). Закройте другой serve.py и запустите снова.") from exc
    url = f"http://{HOST}:{PORT}"
    print(f"Сайт: {url}", flush=True)
    print("Остановить: Ctrl+C", flush=True)
    if os.environ.get("IDEALISTA_NO_BROWSER") != "1":
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
