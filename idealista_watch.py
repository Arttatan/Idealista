# -*- coding: utf-8 -*-
"""Ежедневная подборка квартир Idealista: округ Порту и округ Брага.

Сбор ходит по публичной странице поиска. Ручные пометки лежат в
data/user_notes.json (их пишет локальный сайт) и при обновлении не затираются.
Excel при сборке получает те же пометки и не становится источником правды.
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from rent_estimate import decorate

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
XLSX = ROOT / "Квартиры_Порту_Брага.xlsx"
LISTINGS_PATH = DATA / "listings.json"
GEO_CACHE_PATH = DATA / "geocode_cache.json"
AMENITIES_PATH = DATA / "amenities.json"
SEEN_PATH = DATA / "seen_ids.json"
LOG_PATH = DATA / "update.log"

SEARCH_URL = (
    "https://www.idealista.pt/en/multi/comprar-casas/abW,azY/"
    "com-preco-max_320000,t2,t3,t4-t5,publicado_ultimas-48-horas,"
    "ultimo-andar,andares-intermedios,bom-estado,"
    "eficiencia-energetica-alta,eficiencia-energetica-media/"
    "?ordem=atualizado-desc"
)

# Порту + Брага, с небольшим запасом по краям.
BBOX = (40.75, -9.00, 42.08, -7.82)  # south, west, north, east
WALK_M = 800
SHORT_M = 2000
MAX_M = 5000

USER_AGENT = "IdealistaHomeSearch/1.0 (personal apartment search; contact: local)"

CARD_CACHE = Path(
    r"C:\Users\35191\.cursor\browser-logs\cdp-response-Runtime.evaluate-2026-11-11T22-43-13-827Z.json"
)
DETAIL_CACHE = Path(
    r"C:\Users\35191\.cursor\browser-logs\cdp-response-Runtime.evaluate-2026-11-11T22-44-41-518Z.json"
)

# Столбцы, которые заполняет человек. Скрипт их не перезаписывает.
MANUAL = {
    "Телефон",
    "Просмотрено",
    "Запланирован визит",
    "Дата визита",
    "Приоритет",
    "Статус",
    "Заметки",
    "Плюсы",
    "Минусы",
    "Причина отказа",
}

COLUMNS = [
    "ID",
    "Добавлено",
    "Новое в этом обновлении",
    "Полнота данных",
    "Округ",
    "Город",
    "Район",
    "Адрес или ориентир",
    "Точность адреса",
    "Квартира",
    "Тип",
    "Цена €",
    "Цена €/м²",
    "Площадь м²",
    "Полезная м²",
    "Комнаты",
    "Ванные",
    "Этаж",
    "Лифт",
    "Состояние",
    "Энергокласс",
    "Энергогруппа",
    "Год постройки",
    "Парковка",
    "Балкон или терраса",
    "Сдана арендаторам",
    "Автопометки",
    "Описание",
    "Ссылка",
    "Агентство",
    "Страница агентства",
    "Телефон",
    "Район по услугам",
    "Балл удобства",
    "Почему такая оценка",
    "Магазины",
    "Аптеки",
    "Школы",
    "Детские сады",
    "Транспорт",
    "Парк",
    "Медицина",
    "Просмотрено",
    "Запланирован визит",
    "Дата визита",
    "Приоритет",
    "Статус",
    "Заметки",
    "Плюсы",
    "Минусы",
    "Причина отказа",
    "Платёж €/мес",
    "Широта",
    "Долгота",
    "Уверенность координат",
]

# Что видно в Excel. Полный COLUMNS по-прежнему пишется в listings.json,
# сбор объявлений его не урезает. Первые 7 колонок закреплены.
EXCEL_COLUMNS = [
    "Ссылка",
    "Город / район",
    "Цена €",
    "Оценка аренды €/мес",
    "Состояние",
    "Энергокласс",
    "Год постройки",
    "Аренда от €/мес",
    "Аренда до €/мес",
    "Доходность %",
    "Окупаемость лет",
    "Точность оценки",
    "Округ",
    "Адрес или ориентир",
    "Квартира",
    "Этаж",
    "Лифт",
    "Энергогруппа",
    "Парковка",
    "Балкон или терраса",
    "Сдана арендаторам",
    "Добавлено",
    "Агентство",
    "Страница агентства",
    "Телефон",
    "Район по услугам",
    "Балл удобства",
    "Магазины",
    "Аптеки",
    "Школы",
    "Детские сады",
    "Транспорт",
    "Парк",
    "Медицина",
    "Просмотрено",
    "Статус",
    "Приоритет",
    "Запланирован визит",
    "Дата визита",
    "Заметки",
    "Плюсы",
    "Минусы",
    "Причина отказа",
]

ENERGY_STYLES = {
    "A+": ("176B34", "FFFFFF"),
    "A": ("2E8B3A", "FFFFFF"),
    "B": ("7CB342", "1C2421"),
    "C": ("F9A825", "1C2421"),
    "D": ("EF8C22", "1C2421"),
    "E": ("E85D3A", "FFFFFF"),
    "F": ("D63A3A", "FFFFFF"),
    "G": ("8E1B1B", "FFFFFF"),
}


def now_lisbon() -> datetime:
    return datetime.now()


def stamp() -> str:
    return now_lisbon().strftime("%Y-%m-%d %H:%M")


def log(message: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    line = f"{stamp()}  {message}"
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def http_json(url: str, data: bytes | None = None, timeout: int = 180):
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en,pt,ru",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_money(text: str) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d[\d\.,\s]*)", text.replace("\xa0", " "))
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group(1))
    if not digits:
        return None
    value = int(digits)
    return value if value else None


def parse_area_pair(features: list[str], card_details: list[str]) -> tuple[int | None, int | None]:
    blob = " | ".join(features + card_details)
    built = useful = None
    match = re.search(
        r"(\d+)\s*m²\s*built(?:,\s*(\d+)\s*m²\s*floor area)?",
        blob,
        re.I,
    )
    if match:
        built = int(match.group(1))
        if match.group(2):
            useful = int(match.group(2))
    if built is None:
        simple = re.search(r"(\d+)\s*m²", blob)
        if simple:
            built = int(simple.group(1))
    return built, useful


def parse_floor_and_lift(features: list[str], card_details: list[str]) -> tuple[str, str]:
    blob = " | ".join(features + card_details)
    floor = ""
    numbered = re.search(r"(\d+)(?:st|nd|rd|th)\s+floor", blob, re.I)
    if numbered:
        floor = numbered.group(1)
    elif re.search(r"ground floor|rés[- ]do[- ]chão", blob, re.I):
        floor = "0 (цоколь)"
    lift = ""
    if re.search(r"\bwith lift\b|\bcom elevador\b", blob, re.I):
        lift = "Да"
    elif re.search(r"\bwithout lift\b|\bno lift\b|\bsem elevador\b", blob, re.I):
        lift = "Нет"
    return floor, lift


def parse_bathrooms(features: list[str]) -> str:
    blob = " | ".join(features)
    match = re.search(r"(\d+)\s+bathrooms?", blob, re.I)
    return match.group(1) if match else ""


def parse_year(features: list[str]) -> str:
    blob = " | ".join(features)
    match = re.search(r"Built in (\d{4})", blob, re.I)
    return match.group(1) if match else ""


def yes_no_unknown(blob: str, yes_pattern: str, known: bool) -> str:
    if re.search(yes_pattern, blob, re.I):
        return "Да"
    if known:
        return "Нет"
    return "не указано"


def energy_group(letter: str) -> str:
    letter = (letter or "").upper().replace(" ", "")
    if letter in {"A+", "A", "B"}:
        return "Высокая"
    if letter in {"C", "D", "E"}:
        return "Средняя"
    if letter in {"F", "G"}:
        return "Низкая"
    return "Высокая или средняя"


def property_kind(title: str) -> str:
    low = title.lower()
    if "penthouse" in low:
        kind = "пентхаус"
    elif "duplex" in low:
        kind = "дуплекс"
    elif "detached" in low:
        kind = "отдельный дом"
    elif "semi-detached" in low:
        kind = "дом на две семьи"
    elif "terraced" in low or "townhouse" in low:
        kind = "таунхаус"
    elif re.search(r"\bhouse\b|\bmoradia\b|\bvilla\b", low):
        kind = "дом"
    elif "studio" in low:
        kind = "студия"
    else:
        kind = "квартира"
    rooms = re.search(r"\bT(\d)\b", title)
    if rooms:
        return f"{kind} T{rooms.group(1)}"
    return kind


def looks_like_street(text: str) -> bool:
    low = text.lower()
    return bool(
        re.match(
            r"^(rua|avenida|travessa|praceta|largo|alameda|estrada|campo|calçada|calcada|urbanização|urbanizacao|rotunda)\b",
            low,
        )
        or re.search(r"\d", text)
    )


def parse_location(lis: list[str], title: str) -> dict:
    district = city = neighborhood = street = ""
    clean = [re.sub(r"\s+", " ", item).strip() for item in lis if item and item.strip()]
    if clean:
        last = clean[-1]
        if "," in last:
            city_part, district_part = [part.strip() for part in last.rsplit(",", 1)]
            city = city_part
            district = district_part
        else:
            city = last
        body = clean[:-1] if len(clean) > 1 else clean
        for item in body:
            name = re.sub(r"^District\s+", "", item, flags=re.I).strip()
            if looks_like_street(item) and not item.lower().startswith("district "):
                street = street or item
            else:
                neighborhood = neighborhood or name
        if not neighborhood and street and len(body) == 1 and "," not in last:
            neighborhood = ""
    else:
        match = re.search(r"\bin (.+)$", title, re.I)
        place = match.group(1).strip() if match else title
        raw_parts = [part.strip() for part in place.split(",") if part.strip()]
        parts: list[str] = []
        for part in raw_parts:
            if re.fullmatch(r"\d+[A-Za-z]?", part) and parts:
                parts[-1] = parts[-1] + ", " + part
            else:
                parts.append(part)
        if parts and looks_like_street(parts[0]) and len(parts) > 1:
            street = parts[0]
            parts = parts[1:]
        if len(parts) >= 2:
            neighborhood = ", ".join(parts[:-1])
            city = parts[-1]
        elif parts:
            neighborhood = parts[0]
    district = normalize_district(district)
    return {
        "district": district,
        "city": city,
        "neighborhood": neighborhood,
        "street": street,
    }


def normalize_district(value: str) -> str:
    low = (value or "").lower()
    if "braga" in low:
        return "Braga"
    if "porto" in low or "oporto" in low:
        return "Porto"
    if "vila real" in low:
        return "Vila Real"
    if "viseu" in low:
        return "Viseu"
    if "aveiro" in low:
        return "Aveiro"
    return value.strip()


def in_bbox(lat: float, lon: float) -> bool:
    south, west, north, east = BBOX
    return south <= lat <= north and west <= lon <= east


def geocode_query(loc: dict, title: str) -> str:
    parts = []
    if loc.get("street"):
        parts.append(loc["street"])
    if loc.get("neighborhood"):
        parts.append(loc["neighborhood"])
    if loc.get("city"):
        parts.append(loc["city"])
    if loc.get("district"):
        parts.append(loc["district"])
    if not parts:
        match = re.search(r"\bin (.+)$", title, re.I)
        parts.append(match.group(1).strip() if match else title)
    parts.append("Portugal")
    # Убираем повторы, сохраняя порядок.
    seen = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    without = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return without.lower()


GENERIC_AREA = {
    "centro",
    "zona este",
    "zona norte",
    "zona sul",
    "zona oeste",
    "zona central",
}


def clean_street(street: str) -> str:
    street = re.sub(r"\bNn\b", "", street or "", flags=re.I)
    street = re.sub(r"\s+,", ",", street)
    return re.sub(r"\s+", " ", street).strip(" ,")


def geocode_results(query: str, cache: dict) -> list[dict]:
    key = "v2:" + query
    cached = cache.get(key)
    if isinstance(cached, list):
        return cached
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 5,
            "countrycodes": "pt",
        }
    )
    url = "https://nominatim.openstreetmap.org/search?" + params
    try:
        results = http_json(url, timeout=40)
    except Exception as exc:  # noqa: BLE001 - сеть может отказать, кэш это переживёт
        log(f"геокодер не ответил для «{query}»: {exc}")
        return []
    time.sleep(1.1)
    cache[key] = results if isinstance(results, list) else []
    return cache[key]


def in_porto_or_braga(item: dict) -> bool:
    try:
        lat = float(item["lat"])
        lon = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return False
    if not in_bbox(lat, lon):
        return False
    address = item.get("address") or {}
    blob = fold(" ".join(
        [
            item.get("display_name") or "",
            address.get("state") or "",
            address.get("county") or "",
            address.get("city") or "",
            address.get("town") or "",
        ]
    ))
    return "porto" in blob or "braga" in blob


def city_mentioned(city: str, item: dict) -> bool:
    if not city:
        return True
    display = fold(item.get("display_name") or "")
    city_f = fold(city)
    if city_f and city_f in display:
        return True
    tokens = [token for token in re.split(r"[^a-z0-9]+", city_f) if len(token) >= 4]
    return any(token in display for token in tokens)


def choose_hit(results: list[dict], city: str) -> dict | None:
    for item in results:
        if in_porto_or_braga(item) and city_mentioned(city, item):
            return item
    return None


def place_queries(row: dict) -> list[tuple[str, str]]:
    city = (row.get("Город") or "").strip()
    neighborhood = (row.get("Район") or "").strip()
    street = clean_street(row.get("street") or "")
    generic = fold(neighborhood) in GENERIC_AREA
    queries: list[tuple[str, str]] = []
    if street and city:
        queries.append((f"{street}, {city}, Portugal", "средняя, по улице"))
    if neighborhood and city and not generic and fold(neighborhood) != fold(city):
        queries.append((f"{neighborhood}, {city}, Portugal", "средняя, по району"))
    if city:
        queries.append((f"{city}, Portugal", "средняя, по городу"))
    elif neighborhood and not generic:
        queries.append((f"{neighborhood}, Portugal", "средняя, по району"))
    unique: list[tuple[str, str]] = []
    seen = set()
    for query, confidence in queries:
        if query not in seen:
            seen.add(query)
            unique.append((query, confidence))
    return unique


def locate(row: dict, cache: dict) -> tuple[dict | None, str]:
    city = (row.get("Город") or "").strip()
    for query, confidence in place_queries(row):
        hit = choose_hit(geocode_results(query, cache), city)
        if hit:
            if confidence == "средняя, по городу":
                confidence = "средняя, по городу: точка в центре, не у двери"
            return hit, confidence
    return None, "нет"


def apply_geocode(row: dict, hit: dict | None, confidence: str) -> None:
    if not hit:
        row["Широта"] = ""
        row["Долгота"] = ""
        row["Уверенность координат"] = "нет"
        return
    lat = float(hit["lat"])
    lon = float(hit["lon"])
    row["Широта"] = round(lat, 6)
    row["Долгота"] = round(lon, 6)
    address = hit.get("address") or {}
    state = normalize_district(address.get("state") or address.get("county") or "")
    city = (
        address.get("city")
        or address.get("town")
        or address.get("municipality")
        or address.get("village")
        or ""
    )
    suburb = (
        address.get("suburb")
        or address.get("city_district")
        or address.get("quarter")
        or address.get("neighbourhood")
        or address.get("hamlet")
        or ""
    )
    if not row.get("Округ") and state:
        row["Округ"] = state
    if not row.get("Округ"):
        display = fold(hit.get("display_name") or "")
        if "braga" in display and "porto" not in display:
            row["Округ"] = "Braga"
        elif "porto" in display:
            row["Округ"] = "Porto"
    official_city = city
    current_city = (row.get("Город") or "").strip()
    if official_city and fold(official_city) != fold(current_city):
        if current_city and fold(current_city) not in fold(row.get("Район") or ""):
            neighborhood = (row.get("Район") or "").strip()
            row["Район"] = current_city if not neighborhood else f"{neighborhood}, {current_city}"
        row["Город"] = official_city
    elif not current_city and official_city:
        row["Город"] = official_city
    if not row.get("Район") and suburb:
        row["Район"] = suburb
    if row.get("exact_address") and confidence.startswith("средняя, по улице"):
        row["Уверенность координат"] = "высокая, адрес указан"
    else:
        row["Уверенность координат"] = confidence


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def amenity_kind(tags: dict) -> str | None:
    amenity = tags.get("amenity") or ""
    shop = tags.get("shop") or ""
    railway = tags.get("railway") or ""
    leisure = tags.get("leisure") or ""
    if amenity == "pharmacy":
        return "pharmacy"
    if amenity == "school":
        return "school"
    if amenity in {"kindergarten", "childcare"}:
        return "kindergarten"
    if amenity in {"clinic", "hospital", "doctors"}:
        return "health"
    if shop in {"supermarket", "convenience", "mall", "department_store"} or amenity == "marketplace":
        return "shop"
    if tags.get("highway") == "bus_stop" or railway in {"station", "halt", "subway_entrance"}:
        return "transit"
    if leisure in {"park", "garden"}:
        return "park"
    return None


def download_amenities(force: bool = False) -> list[dict]:
    if AMENITIES_PATH.exists() and not force:
        cached = load_json(AMENITIES_PATH, [])
        if cached:
            log(f"услуги на карте взяты из кэша: {len(cached)}")
            return cached
    south, west, north, east = BBOX
    query = f"""
[out:json][timeout:180];
(
  nwr["amenity"~"^(pharmacy|school|kindergarten|childcare|clinic|hospital|doctors|marketplace)$"]({south},{west},{north},{east});
  nwr["shop"~"^(supermarket|convenience|mall|department_store)$"]({south},{west},{north},{east});
  node["highway"="bus_stop"]({south},{west},{north},{east});
  nwr["railway"~"^(station|halt|subway_entrance)$"]({south},{west},{north},{east});
  nwr["leisure"~"^(park|garden)$"]({south},{west},{north},{east});
);
out center;
"""
    log("загружаю магазины, аптеки, школы и сады с OpenStreetMap")
    payload = http_json(
        "https://overpass-api.de/api/interpreter",
        data=urllib.parse.urlencode({"data": query}).encode("utf-8"),
        timeout=180,
    )
    points = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        kind = amenity_kind(tags)
        if not kind:
            continue
        lat = element.get("lat") or (element.get("center") or {}).get("lat")
        lon = element.get("lon") or (element.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        name = tags.get("name") or tags.get("brand") or ""
        points.append({"kind": kind, "lat": lat, "lon": lon, "name": name})
    save_json(AMENITIES_PATH, points)
    log(f"точек услуг: {len(points)}")
    return points


def nearest(points: list[dict], kind: str, lat: float, lon: float) -> tuple[float | None, str]:
    best = None
    name = ""
    for point in points:
        if point["kind"] != kind:
            continue
        distance = haversine(lat, lon, point["lat"], point["lon"])
        if distance > MAX_M:
            continue
        if best is None or distance < best:
            best = distance
            name = point.get("name") or ""
    return best, name


def format_access(distance: float | None, name: str) -> str:
    if distance is None:
        return "дальше 5 км или нет на карте OSM"
    if distance <= WALK_M:
        how = "пешком"
    elif distance <= SHORT_M:
        how = "короткая поездка"
    else:
        how = "на машине"
    if distance < 1000:
        dist = f"{int(round(distance))} м"
    else:
        dist = f"{distance / 1000:.1f} км".replace(".", ",")
    if name:
        return f"{how}, {dist} ({name})"
    return f"{how}, {dist}"


def rate_area(access: dict[str, tuple[float | None, str]]) -> tuple[str, int, str]:
    def meters(kind: str) -> float | None:
        return access[kind][0]

    shop = meters("shop")
    pharmacy = meters("pharmacy")
    school = meters("school")
    garden = meters("kindergarten")
    score = 0
    if shop is not None and shop <= WALK_M:
        score += 3
    elif shop is not None and shop <= SHORT_M:
        score += 1
    if pharmacy is not None and pharmacy <= WALK_M:
        score += 3
    elif pharmacy is not None and pharmacy <= SHORT_M:
        score += 1
    if school is not None and school <= WALK_M:
        score += 2
    elif school is not None and school <= SHORT_M:
        score += 1
    if garden is not None and garden <= WALK_M:
        score += 2
    elif garden is not None and garden <= SHORT_M:
        score += 1
    if access["transit"][0] is not None and access["transit"][0] <= 500:
        score += 1
    if access["park"][0] is not None and access["park"][0] <= WALK_M:
        score += 1

    daily_walk = shop is not None and shop <= WALK_M and pharmacy is not None and pharmacy <= WALK_M
    child_near = (
        (school is not None and school <= 1500) or (garden is not None and garden <= 1500)
    )
    if daily_walk and child_near:
        label = "Хороший"
    elif (shop is not None and shop <= WALK_M) or (pharmacy is not None and pharmacy <= WALK_M):
        label = "Средний"
    else:
        label = "Слабый"

    why_bits = [
        f"магазины: {format_access(*access['shop'])}",
        f"аптека: {format_access(*access['pharmacy'])}",
        f"школа: {format_access(*access['school'])}",
        f"детский сад: {format_access(*access['kindergarten'])}",
    ]
    why = (
        "; ".join(why_bits)
        + ". Оценка только про шаговую доступность услуг, не про безопасность и не про престиж улицы."
    )
    return label, score, why


def auto_notes(row: dict) -> str:
    notes = []
    if row.get("Сдана арендаторам") == "Да":
        notes.append("сдана арендаторам")
    if row.get("Лифт") == "Нет":
        try:
            floor_num = int(str(row.get("Этаж") or "").split()[0])
        except ValueError:
            floor_num = None
        if floor_num is not None and floor_num >= 3:
            notes.append("нет лифта, этаж 3 или выше")
    price_m2 = row.get("Цена €/м²")
    if isinstance(price_m2, (int, float)) and price_m2 >= 3000:
        notes.append("выше 3000 €/м²")
    if row.get("Точность адреса") == "только район":
        notes.append("точный адрес скрыт")
    if row.get("Полнота данных") != "полная":
        notes.append("агентство и класс энергии ещё не сняты с карточки")
    if str(row.get("Уверенность координат") or "").startswith("низкая"):
        notes.append("координаты неуверенные, район проверить вручную")
    return "; ".join(notes)


def listing_from_card(card: dict, added: str) -> dict:
    title = card.get("title") or ""
    details = card.get("details") or []
    features: list[str] = []
    price = parse_money(card.get("priceText") or "")
    built, useful = parse_area_pair(features, details)
    floor, lift = parse_floor_and_lift(features, details)
    rooms = next((item for item in details if re.fullmatch(r"T\d+", item)), "")
    if not rooms:
        match = re.search(r"\b(T\d)\b", title)
        rooms = match.group(1) if match else ""
    loc = parse_location([], title)
    price_m2 = round(price / built) if price and built else None
    row = {
        "ID": str(card.get("id")),
        "Добавлено": added,
        "Новое в этом обновлении": "Да",
        "Полнота данных": "с поиска",
        "Округ": loc["district"],
        "Город": loc["city"],
        "Район": loc["neighborhood"],
        "Адрес или ориентир": loc["street"] or loc["neighborhood"] or title,
        "Точность адреса": "только район",
        "Квартира": property_kind(title),
        "Тип": title,
        "Цена €": price,
        "Цена €/м²": price_m2,
        "Площадь м²": built,
        "Полезная м²": useful,
        "Комнаты": rooms,
        "Ванные": "",
        "Этаж": floor,
        "Лифт": lift or "не указано",
        "Состояние": "Хорошее состояние (фильтр поиска)",
        "Энергокласс": "",
        "Энергогруппа": energy_group(""),
        "Год постройки": "",
        "Парковка": yes_no_unknown(" | ".join(details), r"parking|garage|garagem", False),
        "Балкон или терраса": "не указано",
        "Сдана арендаторам": "не проверено",
        "Описание": (card.get("desc") or "").strip(),
        "Ссылка": card.get("url") or f"https://www.idealista.pt/en/imovel/{card.get('id')}/",
        "Агентство": "",
        "Страница агентства": "",
        "Телефон": "",
        "Просмотрено": "Нет",
        "Запланирован визит": "Нет",
        "Дата визита": "",
        "Приоритет": "",
        "Статус": "Новая",
        "Заметки": "",
        "Плюсы": "",
        "Минусы": "",
        "Причина отказа": "",
        "street": loc["street"],
        "features": features,
        "card_details": details,
        "exact_address": False,
    }
    return row


def overlay_detail(row: dict, detail: dict) -> None:
    if detail.get("status") != 200:
        return
    h1 = detail.get("h1") or ""
    if not h1 or "Demasiados pedidos" in h1 or "Just a moment" in h1:
        return
    features = [item for item in (detail.get("features") or []) if item]
    if not features and not detail.get("lis"):
        return
    blob = " | ".join(features)
    loc = parse_location(detail.get("lis") or [], detail.get("cardTitle") or row.get("Тип") or "")
    built, useful = parse_area_pair(features, row.get("card_details") or [])
    floor, lift = parse_floor_and_lift(features, row.get("card_details") or [])
    price = parse_money(detail.get("info") or "") or row.get("Цена €")
    if loc["district"]:
        row["Округ"] = loc["district"]
    if loc["city"]:
        row["Город"] = loc["city"]
    if loc["neighborhood"]:
        row["Район"] = loc["neighborhood"]
    if loc["street"]:
        row["Адрес или ориентир"] = loc["street"]
        row["street"] = loc["street"]
    row["Точность адреса"] = "точный адрес" if detail.get("exactAddress") else "только район"
    row["exact_address"] = bool(detail.get("exactAddress"))
    if built:
        row["Площадь м²"] = built
    if useful:
        row["Полезная м²"] = useful
    if price and built:
        row["Цена €/м²"] = round(price / built)
    if price:
        row["Цена €"] = price
    baths = parse_bathrooms(features)
    if baths:
        row["Ванные"] = baths
    if floor:
        row["Этаж"] = floor
    if lift:
        row["Лифт"] = lift
    letter = (detail.get("energy") or "").upper()
    if letter:
        row["Энергокласс"] = letter
        row["Энергогруппа"] = energy_group(letter)
    year = parse_year(features)
    if year:
        row["Год постройки"] = year
    if re.search(r"good condition|bom estado", blob, re.I):
        row["Состояние"] = "Хорошее состояние"
    row["Парковка"] = yes_no_unknown(blob + " | " + " | ".join(row.get("card_details") or []), r"parking|garage|garagem", True)
    row["Балкон или терраса"] = yes_no_unknown(blob, r"terrace|balcony|varanda", True)
    if re.search(r"rented|with tenants|arrendad", blob, re.I):
        row["Сдана арендаторам"] = "Да"
    else:
        row["Сдана арендаторам"] = "Нет"
    if detail.get("agency"):
        row["Агентство"] = detail["agency"]
    if detail.get("agencyUrl"):
        row["Страница агентства"] = detail["agencyUrl"]
    comment = (detail.get("comment") or "").strip()
    if comment and not row.get("Описание"):
        row["Описание"] = comment
    row["Полнота данных"] = "полная"
    row["features"] = features


def load_initial_cards() -> list[dict]:
    payload = load_json(CARD_CACHE, {})
    cards = payload.get("result", {}).get("value", {}).get("all") or []
    if not cards:
        raise SystemExit(f"Не найден кэш объявлений: {CARD_CACHE}")
    added = stamp()
    rows = [listing_from_card(card, added) for card in cards]
    details_payload = load_json(DETAIL_CACHE, {})
    details = details_payload.get("result", {}).get("value") or []
    by_id = {str(item.get("id")): item for item in details}
    for row in rows:
        detail = by_id.get(row["ID"])
        if detail:
            overlay_detail(row, detail)
    return rows


def enrich_places(rows: list[dict]) -> None:
    cache = load_json(GEO_CACHE_PATH, {})
    points = download_amenities()
    buckets = {kind: [point for point in points if point["kind"] == kind] for kind in
               ["shop", "pharmacy", "school", "kindergarten", "transit", "park", "health"]}
    for index, row in enumerate(rows, start=1):
        hit, confidence = locate(row, cache)
        apply_geocode(row, hit, confidence)
        if row.get("Широта") in (None, ""):
            row["Район по услугам"] = "нет точки"
            row["Балл удобства"] = ""
            row["Почему такая оценка"] = "Адрес не нашёлся на карте, услуги не посчитаны."
            for column in ("Магазины", "Аптеки", "Школы", "Детские сады", "Транспорт", "Парк", "Медицина"):
                row[column] = ""
        else:
            access = {}
            for kind, column in (
                ("shop", "Магазины"),
                ("pharmacy", "Аптеки"),
                ("school", "Школы"),
                ("kindergarten", "Детские сады"),
                ("transit", "Транспорт"),
                ("park", "Парк"),
                ("health", "Медицина"),
            ):
                found = nearest(buckets[kind], kind, row["Широта"], row["Долгота"])
                access[kind] = found
                row[column] = format_access(*found)
            label, score, why = rate_area(access)
            if "по городу" in confidence:
                why = "Точка стоит в центре города, не у двери квартиры. " + why
                label = label + " (центр города)"
            elif str(row.get("Уверенность координат") or "").startswith("низкая"):
                label = label + " (проверить)"
            row["Район по услугам"] = label
            row["Балл удобства"] = score
            row["Почему такая оценка"] = why
        row["Автопометки"] = auto_notes(row)
        if index % 10 == 0 or index == len(rows):
            log(f"адреса и услуги: {index}/{len(rows)}")
            save_json(GEO_CACHE_PATH, cache)
    save_json(GEO_CACHE_PATH, cache)


def read_manual(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    workbook = load_workbook(path)
    if "Квартиры" not in workbook.sheetnames:
        return {}
    sheet = workbook["Квартиры"]
    headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    kept = {}
    for cells in sheet.iter_rows(min_row=2, values_only=True):
        record = {headers[i]: cells[i] for i in range(len(headers)) if headers[i]}
        listing_id = record.get("ID")
        if listing_id in (None, ""):
            listing_id = record.get("_ID")
        listing_id = str(listing_id or "").strip()
        if listing_id.endswith(".0"):
            listing_id = listing_id[:-2]
        if not listing_id:
            continue
        kept[listing_id] = {key: record.get(key) for key in MANUAL}
        kept[listing_id]["Добавлено"] = record.get("Добавлено")
    return kept


def apply_manual(rows: list[dict], manual: dict[str, dict], fresh_ids: set[str]) -> None:
    for row in rows:
        previous = manual.get(row["ID"])
        if previous:
            for key in MANUAL:
                value = previous.get(key)
                if value not in (None, ""):
                    row[key] = value
            if previous.get("Добавлено"):
                row["Добавлено"] = previous["Добавлено"]
        if row["ID"] in fresh_ids or not previous:
            row["Новое в этом обновлении"] = "Да"


def style_workbook(workbook: Workbook, sheet, rows: list[dict]) -> None:
    header_fill = PatternFill("solid", fgColor="0F3D2E")
    header_font = Font(color="FFFFFF", bold=True, name="Calibri", size=11)
    thin = Border(
        left=Side(style="thin", color="D9E2DF"),
        right=Side(style="thin", color="D9E2DF"),
        top=Side(style="thin", color="D9E2DF"),
        bottom=Side(style="thin", color="D9E2DF"),
    )
    sheet.freeze_panes = "H2"
    sheet.row_dimensions[1].height = 40
    sheet.sheet_view.showGridLines = False
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.sheet_properties.tabColor = "0F3D2E"
    sheet.oddHeader.left.text = "Квартиры Порту и Брага"
    for col, name in enumerate(EXCEL_COLUMNS, start=1):
        cell = sheet.cell(1, col, name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        comment = HEADER_COMMENTS.get(name)
        if comment:
            cell.comment = Comment(comment, "Idealista", width=280, height=80)
    link_font = Font(color="1D4E89", underline="single", name="Calibri", size=11)
    body_font = Font(name="Calibri", size=11, color="1F2933")
    wrap = Alignment(wrap_text=True, vertical="center")
    center = Alignment(wrap_text=True, vertical="center", horizontal="center")
    centered_names = {
        "Этаж",
        "Лифт",
        "Энергокласс",
        "Год постройки",
        "Парковка",
        "Балкон или терраса",
        "Сдана арендаторам",
        "Просмотрено",
        "Запланирован визит",
        "Приоритет",
        "Район по услугам",
        "Балл удобства",
        "Доходность %",
        "Окупаемость лет",
        "Точность оценки",
    }
    for row_index, row in enumerate(rows, start=2):
        sheet.row_dimensions[row_index].height = 48
        for col, name in enumerate(EXCEL_COLUMNS, start=1):
            value = row.get(name, "")
            cell = sheet.cell(row_index, col, value if value is not None else "")
            cell.font = body_font
            cell.alignment = center if name in centered_names else wrap
            cell.border = thin
            if name == "Ссылка" and value:
                cell.hyperlink = value
                cell.value = "открыть"
                cell.font = link_font
            if name == "Страница агентства" and value:
                cell.hyperlink = value
                cell.value = "агентство"
                cell.font = link_font
            if name in {"Цена €", "Оценка аренды €/мес", "Аренда от €/мес", "Аренда до €/мес"} and isinstance(value, (int, float)):
                cell.number_format = "#,##0"
            if name in {"Доходность %", "Окупаемость лет"} and isinstance(value, (int, float)):
                cell.number_format = "0.0"
            if name == "Оценка аренды €/мес" and isinstance(value, (int, float)):
                cell.fill = PatternFill("solid", fgColor="E5F4F2")
                cell.font = Font(name="Calibri", size=12, bold=True, color="0F6E68")
            energy_letter = str(value or "").upper().replace(" ", "")
            if name == "Энергокласс" and energy_letter in ENERGY_STYLES:
                background, foreground = ENERGY_STYLES[energy_letter]
                cell.fill = PatternFill("solid", fgColor=background)
                cell.font = Font(name="Calibri", size=11, bold=True, color=foreground)
            if name == "Точность оценки" and value == "низкая точность":
                cell.fill = PatternFill("solid", fgColor="FDECC8")
                cell.font = Font(name="Calibri", size=11, color="7A4B00")
        if row_index % 2 == 0:
            for col in range(1, len(EXCEL_COLUMNS) + 1):
                current = sheet.cell(row_index, col)
                if current.fill.fgColor is None or current.fill.fgColor.rgb in (None, "00000000"):
                    current.fill = PatternFill("solid", fgColor="F7FBFA")
    widths = {
        "ID": 12,
        "Добавлено": 18,
        "Новое в этом обновлении": 14,
        "Полнота данных": 16,
        "Округ": 12,
        "Город": 22,
        "Район": 28,
        "Адрес или ориентир": 36,
        "Точность адреса": 16,
        "Квартира": 18,
        "Тип": 42,
        "Цена €": 12,
        "Цена €/м²": 12,
        "Площадь м²": 12,
        "Полезная м²": 12,
        "Комнаты": 12,
        "Ванные": 10,
        "Этаж": 12,
        "Лифт": 10,
        "Состояние": 24,
        "Энергокласс": 12,
        "Энергогруппа": 18,
        "Год постройки": 12,
        "Парковка": 14,
        "Балкон или терраса": 16,
        "Сдана арендаторам": 16,
        "Автопометки": 36,
        "Описание": 40,
        "Ссылка": 14,
        "Агентство": 28,
        "Страница агентства": 16,
        "Телефон": 20,
        "Район по услугам": 16,
        "Балл удобства": 12,
        "Почему такая оценка": 55,
        "Магазины": 32,
        "Аптеки": 32,
        "Школы": 32,
        "Детские сады": 32,
        "Транспорт": 32,
        "Парк": 32,
        "Медицина": 32,
        "Просмотрено": 14,
        "Запланирован визит": 16,
        "Дата визита": 16,
        "Приоритет": 22,
        "Статус": 20,
        "Заметки": 36,
        "Плюсы": 28,
        "Минусы": 28,
        "Причина отказа": 28,
        "Платёж €/мес": 14,
        "Широта": 12,
        "Долгота": 12,
        "Уверенность координат": 28,
        "Город / район": 40,
        "Оценка аренды €/мес": 20,
        "Аренда от €/мес": 16,
        "Аренда до €/мес": 16,
        "Доходность %": 14,
        "Окупаемость лет": 16,
        "Точность оценки": 20,
    }
    for index, name in enumerate(EXCEL_COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = widths.get(name, 18)

    area_col = get_column_letter(EXCEL_COLUMNS.index("Район по услугам") + 1)
    tenant_col = get_column_letter(EXCEL_COLUMNS.index("Сдана арендаторам") + 1)
    priority_col = get_column_letter(EXCEL_COLUMNS.index("Приоритет") + 1)
    last_row = max(2, len(rows) + 1)
    sheet.conditional_formatting.add(
        f"{area_col}2:{area_col}{last_row}",
        FormulaRule(formula=[f'LEFT({area_col}2,7)="Хороший"'], fill=PatternFill("solid", fgColor="C8E6D4")),
    )
    sheet.conditional_formatting.add(
        f"{area_col}2:{area_col}{last_row}",
        FormulaRule(formula=[f'LEFT({area_col}2,7)="Средний"'], fill=PatternFill("solid", fgColor="FDECC8")),
    )
    sheet.conditional_formatting.add(
        f"{area_col}2:{area_col}{last_row}",
        FormulaRule(formula=[f'LEFT({area_col}2,6)="Слабый"'], fill=PatternFill("solid", fgColor="F4D6D6")),
    )
    sheet.conditional_formatting.add(
        f"{tenant_col}2:{tenant_col}{last_row}",
        FormulaRule(formula=[f'{tenant_col}2="Да"'], fill=PatternFill("solid", fgColor="F6C1A6")),
    )
    sheet.conditional_formatting.add(
        f"{priority_col}2:{priority_col}{last_row}",
        FormulaRule(formula=[f'LEFT({priority_col}2,1)="1"'], fill=PatternFill("solid", fgColor="C8E6D4")),
    )
    accuracy_col = get_column_letter(EXCEL_COLUMNS.index("Точность оценки") + 1)
    sheet.conditional_formatting.add(
        f"{accuracy_col}2:{accuracy_col}{last_row}",
        FormulaRule(formula=[f'{accuracy_col}2="низкая точность"'], fill=PatternFill("solid", fgColor="FDECC8")),
    )

    lists = workbook.create_sheet("Списки")
    lists.sheet_state = "hidden"
    options = {
        "A": ["Нет", "Да"],
        "B": ["Нет", "Да"],
        "C": ["1 — смотреть первой", "2 — интересно", "3 — запасной вариант"],
        "D": ["Новая", "Интересно", "Написать агенту", "Визит назначен", "Визит был", "Отказ", "Оффер", "Купили"],
    }
    for column, values in options.items():
        for index, value in enumerate(values, start=1):
            lists[f"{column}{index}"] = value
    validations = [
        ("Просмотрено", "Списки!$A$1:$A$2"),
        ("Запланирован визит", "Списки!$B$1:$B$2"),
        ("Приоритет", "Списки!$C$1:$C$3"),
        ("Статус", "Списки!$D$1:$D$8"),
    ]
    for name, formula in validations:
        column = get_column_letter(EXCEL_COLUMNS.index(name) + 1)
        validation = DataValidation(type="list", formula1=formula, allow_blank=True)
        validation.error = "Выберите значение из списка"
        validation.errorTitle = "Список"
        validation.add(f"{column}2:{column}5000")
        sheet.add_data_validation(validation)

    table = Table(displayName="Kvartiry", ref=f"A1:{get_column_letter(len(EXCEL_COLUMNS))}{max(2, len(rows) + 1)}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=False)
    sheet.add_table(table)


HEADER_COMMENTS = {
    "Район по услугам": "Хороший: магазин и аптека пешком (до 800 м) и школа или сад ближе 1,5 км. Средний: магазин или аптека пешком. Слабый: повседневные услуги дальше пешей прогулки. Это не оценка безопасности.",
    "Оценка аренды €/мес": "Долгосрочная аренда: площадь × ставка €/м² из data/rent_rates.json × поправки (типология, состояние, энергокласс, лифт, парковка, балкон). Ставка — индекс Idealista, не договор. Пустая ячейка и «низкая точность» — для города индекс не опубликован, цифра не выдумана.",
    "Точность оценки": "Средняя — есть опубликованная ставка муниципалитета или района. Низкая — ставки нет или выборка Idealista слишком тонкая.",
    "Сдана арендаторам": "Да — в объявлении написано, что квартира сдана. Для жизни сразу не подойдёт, пока арендатор не съедет.",
    "Уверенность координат": "Если адрес скрыт, точка ставится по улице или району. Расстояния тогда ориентировочные.",
}


def write_parameters(workbook: Workbook) -> None:
    sheet = workbook.create_sheet("Параметры", 0)
    sheet.sheet_properties.tabColor = "53C6BD"
    sheet["A1"] = "Черновая ипотека"
    sheet["A1"].font = Font(name="Calibri", size=18, bold=True, color="0F3D2E")
    sheet["A3"] = "Взнос, %"
    sheet["B3"] = 10
    sheet["A4"] = "Ставка, % годовых"
    sheet["B4"] = 3.5
    sheet["A5"] = "Срок, лет"
    sheet["B5"] = 30
    for cell in ("A3", "A4", "A5"):
        sheet[cell].font = Font(name="Calibri", size=12, bold=True)
    for cell in ("B3", "B4", "B5"):
        sheet[cell].font = Font(name="Calibri", size=14, color="0F3D2E")
        sheet[cell].fill = PatternFill("solid", fgColor="E7F7F5")
    sheet["B4"].number_format = "0.00"
    sheet["A7"] = (
        "Три числа выше — памятка по ипотеке (взнос, ставка, срок). "
        "Отдельного столбца платежа в таблице больше нет. "
        "Это не предложение банка: в Португалии ставка обычно Euribor плюс спред, "
        "срок часто 30–40 лет, банк смотрит взнос, доход и энергокласс."
    )
    sheet["A7"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A7:F10")
    sheet["A12"] = "Фильтры, как на скриншотах"
    sheet["A12"].font = Font(name="Calibri", size=16, bold=True, color="0F3D2E")
    lines = [
        "Покупка жилья, не аренда.",
        "Территория: округ Порту и округ Брага.",
        "Цена до 300 000 €. Нижняя граница не задана.",
        "Комнаты: T2, T3, T4 и больше. T0 и T1 не берём.",
        "Состояние: хорошее. «Под ремонт» и обязательная новостройка не включены.",
        "Этаж: верхний или средние. Цокольный и ground floor исключены.",
        "Энергоэффективность: высокая или средняя. Низкая исключена.",
        "Только объявления, которые Idealista помечает как опубликованные за последние 48 часов.",
        "Тип дома на скриншоте не ограничен: в выборке и квартиры, и дома, если они прошли остальные фильтры.",
        "Ванные, площадь, парковка, балкон, вид на море и «люкс» не ограничивались.",
        "Квартиры с арендаторами не исключались: на скриншоте этот фильтр не был включён. Они помечены в столбце «Сдана арендаторам».",
    ]
    for index, line in enumerate(lines, start=13):
        sheet[f"A{index}"] = line
        sheet[f"A{index}"].alignment = Alignment(wrap_text=True)
    sheet["A25"] = "Ссылка на тот же поиск"
    sheet["A26"] = SEARCH_URL
    sheet["A26"].hyperlink = SEARCH_URL
    sheet["A26"].font = Font(color="1D4E89", underline="single")
    sheet["A28"] = (
        "Как читать район. «Хороший» значит, что магазин и аптека находятся примерно в 10 минутах пешком "
        "(до 800 метров), а школа или детский сад ближе 1,5 км. «Средний» — пешком есть хотя бы магазин или аптека. "
        "«Слабый» — за повседневными услугами нужна машина. Безопасность, шум и престиж улицы сюда не входят: "
        "это видно только на месте. Если Idealista скрыл точный адрес, точка стоит на районе, и расстояние ориентировочное."
    )
    sheet["A28"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A28:F32")
    sheet["A34"] = "Что обновляется само, а что остаётся вашим"
    sheet["A34"].font = Font(name="Calibri", size=16, bold=True, color="0F3D2E")
    sheet["A35"] = (
        "Каждое обновление добавляет новые объявления и не стирает data/user_notes.json. "
        "Именно этот файл — источник полей «Просмотрено», «Запланирован визит», «Дата визита», "
        "«Приоритет», «Статус», «Заметки», «Плюсы», «Минусы», «Причина отказа» и «Телефон». "
        "Их удобнее править на локальном сайте. При сборке Excel скрипт переносит их сюда. "
        "Телефон на Idealista часто открывается только кнопкой «показать телефон»."
    )
    sheet["A35"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A35:F38")
    sheet["A40"] = "Оценка аренды"
    sheet["A40"].font = Font(name="Calibri", size=16, bold=True, color="0F3D2E")
    sheet["A41"] = (
        "Столбцы аренды считаются при каждой сборке файла: площадь × ставка €/м² "
        "из data/rent_rates.json × поправки за типологию, состояние, энергокласс, лифт, парковку и балкон. "
        "Ставка — индекс Idealista (цена объявлений аренды). Если для города индекс не опубликован, "
        "ячейка пустая и стоит пометка «низкая точность»: цифра не выдумывается. "
        "Первые семь колонок листа «Квартиры» закреплены."
    )
    sheet["A41"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A41:F44")
    sheet.column_dimensions["A"].width = 36
    sheet.column_dimensions["B"].width = 18
    sheet.row_dimensions[7].height = 20
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 1
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.print_title_rows = "1:1"
    sheet.sheet_view.showGridLines = False
    sheet.oddHeader.left.text = "Параметры поиска и ипотеки"


def write_digest(rows: list[dict]) -> None:
    fresh = [row for row in rows if row.get("Новое в этом обновлении") == "Да"]
    ordered = sorted(
        fresh,
        key=lambda row: (
            0 if str(row.get("Район по услугам") or "").startswith("Хороший") else 1,
            0 if row.get("Сдана арендаторам") != "Да" else 1,
            row.get("Цена €") or 10**9,
        ),
    )
    lines = [
        f"Обновление {stamp()} (Лиссабон)",
        f"В файле: {len(rows)}. Новых в этом заходе: {len(fresh)}.",
        "",
    ]
    for row in ordered:
        lines.append(
            f"{row.get('Цена €') or '—'} € | {row.get('Квартира') or ''} | {row.get('Город') or ''} | "
            f"{row.get('Район') or ''} | {row.get('Район по услугам') or ''} | {row.get('Ссылка')}"
        )
    (DATA / "last_digest.txt").write_text("\n".join(lines), encoding="utf-8")


def overlay_user_notes(rows: list[dict]) -> None:
    """Сайт — источник ручных полей. Файл заметок здесь только читается."""
    notes = load_json(DATA / "user_notes.json", {})
    if not isinstance(notes, dict):
        return
    for row in rows:
        saved = notes.get(str(row.get("ID") or ""))
        if not isinstance(saved, dict):
            continue
        for key in MANUAL:
            if key in saved and saved[key] is not None:
                row[key] = saved[key]


def merge_saved_fields(rows: list[dict]) -> None:
    manual = read_manual(XLSX)
    fresh_ids = {row["ID"] for row in rows if row["ID"] not in manual}
    apply_manual(rows, manual, fresh_ids)
    overlay_user_notes(rows)


def _excel_cell_value(value):
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith("="):
        return "'" + value
    return value


def render_workbook(rows: list[dict]) -> Workbook:
    prepared = [dict(row) for row in rows]
    for row in prepared:
        decorate(row)
    prepared.sort(key=lambda row: (row.get("Округ") or "я", row.get("Город") or "я", row.get("Цена €") or 10**9))
    workbook = Workbook()
    write_parameters(workbook)
    sheet = workbook.create_sheet("Квартиры", 1)
    if "Sheet" in workbook.sheetnames:
        del workbook["Sheet"]
    for col, name in enumerate(EXCEL_COLUMNS, start=1):
        sheet.cell(1, col, name)
    style_workbook(workbook, sheet, prepared)
    id_col = len(EXCEL_COLUMNS) + 1
    id_letter = get_column_letter(id_col)
    sheet.cell(1, id_col, "_ID")
    sheet.column_dimensions[id_letter].hidden = True
    sheet.column_dimensions[id_letter].width = 0
    for row_index, row in enumerate(prepared, start=2):
        sheet.cell(row_index, id_col, str(row.get("ID") or ""))
        for col, name in enumerate(EXCEL_COLUMNS, start=1):
            value = row.get(name, "")
            cell = sheet.cell(row_index, col)
            if name == "Ссылка" and value:
                cell.hyperlink = value
                cell.value = "открыть"
            elif name == "Страница агентства" and value:
                cell.hyperlink = value
                cell.value = "агентство"
            else:
                cell.value = _excel_cell_value(value)
    return workbook


def write_workbook(rows: list[dict]) -> None:
    merge_saved_fields(rows)
    render_workbook(rows).save(XLSX)
    write_digest(rows)
    log(f"файл записан: {XLSX}")


def public_rows(rows: list[dict]) -> list[dict]:
    cleaned = []
    for row in rows:
        item = {key: row.get(key, "") for key in COLUMNS}
        item["street"] = row.get("street", "")
        item["exact_address"] = row.get("exact_address", False)
        item["features"] = row.get("features", [])
        item["card_details"] = row.get("card_details", [])
        cleaned.append(item)
    return cleaned


def init() -> None:
    rows = load_initial_cards()
    log(f"объявлений в первой выборке: {len(rows)}")
    enrich_places(rows)
    save_json(LISTINGS_PATH, public_rows(rows))
    save_json(SEEN_PATH, sorted({row["ID"] for row in rows}))
    write_workbook(rows)


def normalize_card(card: dict) -> dict:
    out = dict(card)
    out["id"] = str(out.get("id") or "")
    out["url"] = out.get("url") or out.get("href") or f"https://www.idealista.pt/en/imovel/{out['id']}/"
    out["details"] = out.get("details") or []
    return out


def merge_fresh_cards(cards: list[dict]) -> tuple[list[dict], list[dict]]:
    """Добавить новые карточки к базе. Старые строки и даты Добавлено не трогаем."""
    existing = load_json(LISTINGS_PATH, [])
    by_id = {str(row.get("ID")): row for row in existing if isinstance(row, dict)}
    for row in by_id.values():
        row["Новое в этом обновлении"] = "Нет"
    added_stamp = stamp()
    fresh_rows: list[dict] = []
    for raw in cards:
        card = normalize_card(raw)
        listing_id = card["id"]
        if not listing_id:
            continue
        if listing_id in by_id:
            continue
        row = listing_from_card(card, added_stamp)
        by_id[listing_id] = row
        fresh_rows.append(row)
    rows = list(by_id.values())
    return rows, fresh_rows


def update_from_cards(path: Path | None = None) -> None:
    """Влить карточки из браузерного сбора (data/fresh_cards.json) в базу."""
    source = path or (DATA / "fresh_cards.json")
    cards = load_json(source, [])
    if not cards:
        raise SystemExit(f"Нет карточек в {source}")
    rows, fresh_rows = merge_fresh_cards(cards)
    log(f"карточек с Idealista: {len(cards)}; новых: {len(fresh_rows)}; всего в базе: {len(rows)}")
    if fresh_rows:
        enrich_places(fresh_rows)
    save_json(LISTINGS_PATH, public_rows(rows))
    seen = load_json(SEEN_PATH, [])
    save_json(SEEN_PATH, sorted({*map(str, seen), *(str(row["ID"]) for row in rows)}))
    write_workbook(rows)
    log(f"готово: новых {len(fresh_rows)}, всего {len(rows)}")


def update() -> None:
    """Утренний заход. Idealista часто режет прямой запрос — тогда берём data/fresh_cards.json."""
    log("старт обновления")
    existing = load_json(LISTINGS_PATH, [])
    if not existing:
        log("сохранённой базы нет, пропускаю обновление")
        return
    fresh_path = DATA / "fresh_cards.json"
    if fresh_path.exists():
        update_from_cards(fresh_path)
        return
    try:
        request = urllib.request.Request(SEARCH_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=40) as response:
            html = response.read(500).decode("utf-8", errors="ignore")
            status = response.status
    except Exception as exc:  # noqa: BLE001
        log(f"Idealista не отдал поиск ({exc}). Файл не изменён. Нужен заход через браузер.")
        return
    if status != 200 or "item-link" not in html and "Just a moment" in html:
        log("Idealista закрыл автоматический запрос. Файл не изменён.")
        return
    log("поиск открылся, но без файла data/fresh_cards.json полный разбор не запускаю")


def places() -> None:
    rows = load_json(LISTINGS_PATH, [])
    if not rows:
        raise SystemExit("Нет data/listings.json")
    enrich_places(rows)
    save_json(LISTINGS_PATH, public_rows(rows))
    write_workbook(rows)


def excel_only() -> None:
    rows = load_json(LISTINGS_PATH, [])
    if not rows:
        raise SystemExit("Нет data/listings.json")
    write_workbook(rows)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "init"
    if command == "init":
        init()
    elif command == "excel":
        excel_only()
    elif command == "places":
        places()
    elif command == "update":
        update()
    elif command == "merge_cards":
        update_from_cards()
    else:
        raise SystemExit("Команды: init, excel, update, merge_cards")


if __name__ == "__main__":
    main()
