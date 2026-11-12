# -*- coding: utf-8 -*-
"""Скачать станции Metro do Porto в data/metro.json."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
SOURCES = (
    "https://open-data.pt/api/products/metro-do-porto-gtfs-stops/records/all",
    "https://open-data.pt/api/products/metro-do-porto-gtfs-stops.geojson",
)


def from_records(payload) -> list[dict]:
    rows = payload if isinstance(payload, list) else payload.get("records") or payload.get("data") or []
    points = []
    for row in rows:
        item = row.get("record") if isinstance(row, dict) and "record" in row else row
        if not isinstance(item, dict):
            continue
        try:
            lat = float(item.get("latitude") or item.get("lat"))
            lon = float(item.get("longitude") or item.get("lon") or item.get("lng"))
        except (TypeError, ValueError):
            continue
        points.append({"lat": lat, "lon": lon, "name": str(item.get("stop_name") or item.get("name") or "")})
    return points


def from_geojson(payload: dict) -> list[dict]:
    points = []
    for feature in payload.get("features") or []:
        geometry = feature.get("geometry") or {}
        props = feature.get("properties") or {}
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        points.append({
            "lat": float(lat),
            "lon": float(lon),
            "name": str(props.get("stop_name") or props.get("name") or ""),
        })
    return points


def main() -> None:
    last_error = None
    points: list[dict] = []
    for url in SOURCES:
        request = urllib.request.Request(url, headers={"User-Agent": "IdealistaHomeSearch/1.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"fail: {url} ({exc})")
            continue
        points = from_geojson(payload) if isinstance(payload, dict) and payload.get("type") == "FeatureCollection" else from_records(payload)
        if points:
            print(f"ok: {url} -> {len(points)}")
            break
    if not points:
        raise SystemExit(f"Не удалось скачать метро: {last_error}")
    path = DATA / "metro.json"
    path.write_text(json.dumps(points, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {path}")


if __name__ == "__main__":
    main()
