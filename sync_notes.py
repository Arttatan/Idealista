# -*- coding: utf-8 -*-
"""Слить data/user_notes.json с общим gist и залить обратно.

Важно: сначала читаем облако и мержим по полям, иначе локальный файл
затирает статусы жены.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTES_PATH = ROOT / "data" / "user_notes.json"
SYNC_PATH = ROOT / "data" / "sync.json"
NOTE_FIELDS = [
    "Статус",
    "Избранное",
    "Приоритет",
    "Просмотрено",
    "Запланирован визит",
    "Дата визита",
    "Телефон",
    "Заметки",
    "Плюсы",
    "Минусы",
    "Причина отказа",
]


def field_ts(note: dict, field: str) -> int:
    if not isinstance(note, dict):
        return 0
    raw = note.get(f"_ts_{field}", note.get("_ts", 0))
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def merge_one(left: dict | None, right: dict | None) -> dict:
    a = dict(left or {})
    b = dict(right or {})
    merged = {**a, **b}
    for field in NOTE_FIELDS:
        a_ts = field_ts(a, field)
        b_ts = field_ts(b, field)
        if b_ts > a_ts:
            if field in b:
                merged[field] = b[field]
            ts_key = f"_ts_{field}"
            if ts_key in b:
                merged[ts_key] = b[ts_key]
            elif b.get("_ts"):
                merged[ts_key] = b["_ts"]
        elif a_ts > b_ts:
            if field in a:
                merged[field] = a[field]
            ts_key = f"_ts_{field}"
            if ts_key in a:
                merged[ts_key] = a[ts_key]
            elif a.get("_ts"):
                merged[ts_key] = a["_ts"]
        else:
            if field == "Статус":
                a_status = a.get("Статус") or "Новая"
                b_status = b.get("Статус") or "Новая"
                if a_status != "Новая" and b_status == "Новая":
                    merged["Статус"] = a_status
                elif b_status != "Новая" and a_status == "Новая":
                    merged["Статус"] = b_status
                elif field in b:
                    merged["Статус"] = b_status
                elif field in a:
                    merged["Статус"] = a_status
            elif field == "Избранное":
                merged["Избранное"] = bool(a.get("Избранное")) or bool(b.get("Избранное"))
            else:
                a_val = a.get(field)
                b_val = b.get(field)
                merged[field] = b_val if b_val not in (None, "") else a_val
    merged["_ts"] = max(
        [int(a.get("_ts") or 0), int(b.get("_ts") or 0)]
        + [field_ts(merged, field) for field in NOTE_FIELDS]
    )
    return merged


def merge_notes(local: dict, remote: dict) -> dict:
    ids = set(local) | set(remote)
    return {listing_id: merge_one(local.get(listing_id), remote.get(listing_id)) for listing_id in ids}


def load_local_notes() -> dict:
    if not NOTES_PATH.exists():
        return {}
    raw = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    out = {}
    for key, value in raw.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        out[str(key)] = dict(value)
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


def decrypt_payload(password: str, bundle: dict) -> dict:
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", r"""
import { createDecipheriv, pbkdf2Sync } from 'node:crypto';
const password = process.env.IDEALISTA_PASSWORD;
const bundle = JSON.parse(await new Response(process.stdin).text());
const key = pbkdf2Sync(password, Buffer.from(bundle.salt,'base64'), bundle.iter, 32, 'sha256');
const packed = Buffer.from(bundle.data,'base64');
const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(bundle.iv,'base64'));
decipher.setAuthTag(packed.subarray(packed.length-16));
const plain = Buffer.concat([decipher.update(packed.subarray(0, packed.length-16)), decipher.final()]);
process.stdout.write(plain);
"""],
        input=json.dumps(bundle).encode("utf-8"),
        capture_output=True,
        check=False,
        cwd=ROOT,
        env={**os.environ, "IDEALISTA_PASSWORD": password},
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.decode("utf-8", errors="replace") or "decrypt failed")
    return json.loads(proc.stdout.decode("utf-8"))


def gist_api(method: str, gist_id: str, payload: dict | None = None) -> dict:
    args = ["gh", "api", "-X", method, f"gists/{gist_id}", "-H", "Accept: application/vnd.github+json"]
    if payload is not None:
        args.extend(["--input", "-"])
        proc = subprocess.run(args, input=json.dumps(payload).encode("utf-8"), capture_output=True, check=False)
    else:
        proc = subprocess.run(args, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.decode("utf-8", errors="replace") or "gh api failed")
    body = proc.stdout.decode("utf-8")
    return json.loads(body) if body else {}


def pull_remote(password: str, gist_id: str, file_name: str) -> dict:
    gist = gist_api("GET", gist_id)
    file_info = (gist.get("files") or {}).get(file_name) or {}
    content = file_info.get("content")
    if not content:
        return {}
    payload = decrypt_payload(password, json.loads(content))
    notes = payload.get("notes") or {}
    return {str(key): value for key, value in notes.items() if isinstance(value, dict)}


def main() -> None:
    password = os.environ.get("IDEALISTA_PASSWORD", "")
    if len(password) < 10:
        raise SystemExit("Нужен IDEALISTA_PASSWORD")
    if not os.environ.get("IDEALISTA_SYNC_TOKEN"):
        try:
            os.environ["IDEALISTA_SYNC_TOKEN"] = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
        except Exception as exc:  # noqa: BLE001
            raise SystemExit("Нужен IDEALISTA_SYNC_TOKEN") from exc

    sync = json.loads(SYNC_PATH.read_text(encoding="utf-8")) if SYNC_PATH.exists() else {}
    gist_id = os.environ.get("IDEALISTA_GIST_ID") or sync.get("gistId")
    file_name = sync.get("fileName") or "notes.vault.json"
    if not gist_id:
        raise SystemExit("Нет gistId в data/sync.json")

    local = load_local_notes()
    remote = pull_remote(password, gist_id, file_name)
    merged = merge_notes(local, remote)

    # сохранить слитое локально, чтобы Excel/serve видели то же
    raw = json.loads(NOTES_PATH.read_text(encoding="utf-8")) if NOTES_PATH.exists() else {"_meta": {}}
    for listing_id, note in merged.items():
        raw[listing_id] = note
    NOTES_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload = {
        "v": 1,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "notes": merged,
    }
    encrypted = encrypt_payload(password, payload)
    gist_api("PATCH", gist_id, {"files": {file_name: {"content": json.dumps(encrypted, ensure_ascii=False)}}})
    SYNC_PATH.write_text(
        json.dumps({"gistId": gist_id, "fileName": file_name}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    interesting = sum(1 for note in merged.values() if (note.get("Статус") or "") == "Интересно")
    print(f"Слито и отправлено: {len(merged)} заметок, Интересно={interesting}")


if __name__ == "__main__":
    main()
