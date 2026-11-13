# -*- coding: utf-8 -*-
"""Оценка долгосрочной аренды, € в месяц.

Единственное место, где лежит формула и коэффициенты. Ставки €/м² — в
data/rent_rates.json, их можно править руками, сервер перечитывает файл.

Живой поиск idealista.pt/arrendar автоматический сбор не отдал, поэтому
основа — опубликованный индекс Idealista (средняя цена объявлений аренды,
не медиана закрытых договоров и не выдуманная цифра). Где индекса нет,
оценка не считается, а помечается «низкая точность».

    аренда = площадь_м² × ставка_€/м² × типология × состояние × энергокласс
             × лифт × парковка × балкон

Доходность, % = аренда × 12 / цена × 100
Окупаемость, лет = цена / (аренда × 12)

Коэффициенты ниже — поправка к средней по району, не отдельная выборка.
Их имеет смысл менять только здесь.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RATES_PATH = ROOT / "data" / "rent_rates.json"

# Меньшие квартиры сдаются дороже за м², большие — дешевле.
# T2 — основная масса объявлений и ближе всего к средней индекса.
TYPOLOGY = {
    "T0": 1.12,
    "T1": 1.08,
    "T2": 1.00,
    "T3": 0.95,
    "T4": 0.90,
    "T5": 0.88,
    "T6": 0.86,
}

# Состояние относительно «хорошего», на котором собран этот поиск.
CONDITION_NEW = 1.08
CONDITION_EXCELLENT = 1.05
CONDITION_GOOD = 1.00
CONDITION_REPAIR = 0.84

# Энергокласс: арендатор платит за отопление, сертификат это видно.
ENERGY = {
    "A+": 1.06,
    "A": 1.05,
    "B": 1.03,
    "C": 1.00,
    "D": 0.97,
    "E": 0.94,
    "F": 0.90,
    "G": 0.86,
}

# Лифт. Средняя по городу уже смешивает дома с лифтом и без.
LIFT_YES = 1.02
LIFT_NO_LOW = 0.98  # этаж 0–2
LIFT_NO_HIGH = 0.94  # этаж 3 и выше, без лифта сдаётся заметно хуже

PARKING_YES = 1.05
PARKING_NO = 1.00
BALCONY_YES = 1.02
BALCONY_NO = 1.00

# Ширина вилки вокруг центральной цифры. Это не доверительный интервал,
# а практический разброс похожих объявлений.
SPREAD = {
    "высокая точность": 0.08,
    "средняя точность": 0.12,
    "низкая точность": 0.20,
}

_CACHE: dict = {"mtime": None, "data": None}


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    without = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return without.lower()


def load_rates() -> dict:
    if not RATES_PATH.exists():
        return {}
    mtime = RATES_PATH.stat().st_mtime
    if _CACHE["mtime"] == mtime and _CACHE["data"] is not None:
        return _CACHE["data"]
    with RATES_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    _CACHE["mtime"] = mtime
    _CACHE["data"] = data
    return data


def _blank(reason: str, rates: dict | None = None) -> dict:
    rates = rates or {}
    return {
        "rent": None,
        "rent_min": None,
        "rent_max": None,
        "yield_pct": None,
        "payback_years": None,
        "accuracy": "низкая точность",
        "rate_eur_m2": None,
        "rate_label": "",
        "rate_as_of": "",
        "source": rates.get("source") or "",
        "source_url": rates.get("source_url") or "",
        "reason": reason,
        "factors": "",
    }


def _area_m2(row: dict) -> float | None:
    value = row.get("Площадь м²")
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _typology(row: dict) -> tuple[float, str, bool]:
    blob = " ".join(
        str(row.get(key) or "")
        for key in ("Комнаты", "Квартира", "Тип")
    )
    match = re.search(r"\bT\s*(\d)\b", blob, re.I)
    if not match:
        return 1.0, "типология не указана", False
    key = f"T{match.group(1)}"
    factor = TYPOLOGY.get(key, 0.86)
    return factor, key, True


def _condition(row: dict) -> tuple[float, str, bool]:
    text = fold(str(row.get("Состояние") or ""))
    if not text:
        return 1.0, "состояние не указано", False
    if any(word in text for word in ("ремонт", "renovat", "recover", "ruin", "para recuperar")):
        return CONDITION_REPAIR, "требует ремонта", True
    if any(word in text for word in ("нов", "new", "novo", "renovad", "remodel")):
        return CONDITION_NEW, "новое", True
    if any(word in text for word in ("отлич", "excellent", "excelente")):
        return CONDITION_EXCELLENT, "отличное", True
    if any(word in text for word in ("хорош", "good", "bom estado", "usado")):
        return CONDITION_GOOD, "хорошее", True
    return 1.0, "состояние не из шкалы", False


def _energy(row: dict) -> tuple[float, str, bool]:
    raw = str(row.get("Энергокласс") or "").upper().replace(" ", "")
    match = re.search(r"A\+|A|B|C|D|E|F|G", raw)
    if not match:
        return 1.0, "энергокласс не указан", False
    letter = match.group(0)
    return ENERGY[letter], letter, True


def _floor(row: dict) -> int | None:
    match = re.search(r"\d+", str(row.get("Этаж") or ""))
    if not match:
        return None
    return int(match.group(0))


def _lift(row: dict) -> tuple[float, str]:
    flag = fold(str(row.get("Лифт") or ""))
    floor = _floor(row)
    if flag == "да":
        return LIFT_YES, "лифт"
    if flag == "нет":
        if floor is not None and floor >= 3:
            return LIFT_NO_HIGH, "без лифта, этаж 3+"
        return LIFT_NO_LOW, "без лифта"
    return 1.0, "лифт не указан"


def _yes_factor(value: str, yes: float, no: float, label: str) -> tuple[float, str]:
    flag = fold(str(value or ""))
    if flag == "да":
        return yes, label
    if flag == "нет":
        return no, f"нет: {label}"
    return 1.0, f"{label} не указан"


# Idealista иногда пишет приход или «Cidade da …» вместо ключа municipalities.
# Только точные имена. Поиск по куску слова легко приписал бы чужую ставку.
CITY_ALIASES = {
    "cidade da maia": "Maia",
    "nogueira e silva escura": "Maia",
    "lemenhe, mouquim e jesufrei": "Vila Nova de Famalicão",
    "frazao": "Paços de Ferreira",
}


def _find_municipality(city: str, table: dict) -> tuple[str, dict] | tuple[None, None]:
    target = fold(city)
    if not target:
        return None, None
    target = fold(CITY_ALIASES.get(target, target))
    for name, entry in table.items():
        if str(name).startswith("_"):
            continue
        if fold(name) == target and isinstance(entry, dict):
            return name, entry
    return None, None


def _city_allowed(area: dict, city: str) -> bool:
    allowed = area.get("cities")
    if not allowed:
        return True
    if isinstance(allowed, str):
        allowed = [allowed]
    target = fold(city)
    return any(fold(str(name)) == target for name in allowed)


def _find_area(city: str, neighborhood: str, areas: list) -> dict | None:
    folded = fold(f"{city} {neighborhood}")
    if not folded:
        return None
    best = None
    best_len = 0
    for area in areas:
        if not isinstance(area, dict) or not _city_allowed(area, city):
            continue
        tokens = area.get("match") or []
        if isinstance(tokens, str):
            tokens = [tokens]
        for token in tokens:
            needle = fold(str(token))
            if needle and needle in folded and len(needle) > best_len:
                best = area
                best_len = len(needle)
    return best


def _confidence(entry: dict) -> str:
    value = str(entry.get("confidence") or "средняя").strip().lower()
    if value not in {"высокая", "средняя", "низкая"}:
        return "средняя"
    return value


def _phrase(level: str) -> str:
    return {
        "высокая": "высокая точность",
        "средняя": "средняя точность",
        "низкая": "низкая точность",
    }[level]


def _lower(level: str) -> str:
    order = ["высокая", "средняя", "низкая"]
    return order[min(order.index(level) + 1, len(order) - 1)]


def _round10(value: float) -> int:
    return int(round(value / 10.0) * 10)


def _fmt_rate(value: float) -> str:
    text = f"{value:.1f}".replace(".", ",")
    return text


def estimate_listing(row: dict) -> dict:
    """Оценка одной квартиры. Не бросает исключений на кривой строке."""
    rates = load_rates()
    source = rates.get("source") or ""
    if not rates:
        return _blank("Нет файла data/rent_rates.json.", rates)

    area = _area_m2(row)
    city = str(row.get("Город") or "").strip()
    neighborhood = str(row.get("Район") or "").strip()
    zone = _find_area(city, neighborhood, rates.get("areas") or [])
    mun_name, mun = _find_municipality(city, rates.get("municipalities") or {})

    if zone and zone.get("eur_m2") not in (None, ""):
        chosen = zone
        label = zone.get("label") or ", ".join(zone.get("match") or [])
    elif mun and mun.get("eur_m2") not in (None, ""):
        chosen = mun
        label = mun.get("label") or mun_name or city
    else:
        note = ""
        if mun and mun.get("note"):
            note = " " + str(mun["note"])
        elif not mun:
            note = " Добавьте город в data/rent_rates.json."
        reason = (
            f"Нет опубликованной ставки Idealista для «{city or 'города без названия'}»."
            f"{note} Цифра не подставлена."
        )
        return _blank(reason.strip(), rates)

    try:
        eur_m2 = float(chosen["eur_m2"])
    except (TypeError, ValueError):
        return _blank(f"В ставке для «{city}» не число. Цифра не подставлена.", rates)
    if eur_m2 <= 0:
        return _blank(f"Ставка для «{city}» пустая. Цифра не подставлена.", rates)

    if area is None:
        result = _blank("Нет площади — оценку аренды не посчитать, цифру не подставляю.", rates)
        result["rate_eur_m2"] = eur_m2
        result["rate_label"] = label
        return result

    typ_f, typ_label, typ_known = _typology(row)
    cond_f, cond_label, cond_known = _condition(row)
    en_f, en_label, en_known = _energy(row)
    lift_f, lift_label = _lift(row)
    park_f, park_label = _yes_factor(str(row.get("Парковка") or ""), PARKING_YES, PARKING_NO, "парковка")
    balc_f, balc_label = _yes_factor(
        str(row.get("Балкон или терраса") or ""), BALCONY_YES, BALCONY_NO, "балкон"
    )

    multiplier = typ_f * cond_f * en_f * lift_f * park_f * balc_f
    rent = _round10(area * eur_m2 * multiplier)

    level = _confidence(chosen)
    missing = sum(1 for known in (typ_known, cond_known, en_known) if not known)
    if missing >= 2:
        level = _lower(level)
    accuracy = _phrase(level)
    spread = SPREAD[accuracy]
    rent_min = min(rent, _round10(rent * (1 - spread)))
    rent_max = max(rent, _round10(rent * (1 + spread)))

    price = row.get("Цена €")
    yield_pct = None
    payback = None
    try:
        price_num = float(price)
    except (TypeError, ValueError):
        price_num = 0
    if price_num > 0 and rent > 0:
        yield_pct = round(rent * 12 / price_num * 100, 1)
        payback = round(price_num / (rent * 12), 1)

    as_of = str(chosen.get("as_of") or rates.get("period") or "")
    period_label = _period_label(as_of)
    factors = " · ".join(
        [
            f"{typ_label} ×{_coef(typ_f)}",
            f"{cond_label} ×{_coef(cond_f)}",
            f"энергия {en_label} ×{_coef(en_f)}",
            f"{lift_label} ×{_coef(lift_f)}",
            f"{park_label} ×{_coef(park_f)}",
            f"{balc_label} ×{_coef(balc_f)}",
        ]
    )
    reason = (
        f"{label}: {_fmt_rate(eur_m2)} €/м² × {int(area) if area == int(area) else area:g} м², {period_label}. "
        f"{factors}."
    )
    if chosen.get("note"):
        reason = str(chosen["note"]).strip() + " " + reason
    if fold(str(row.get("Сдана арендаторам") or "")) == "да":
        reason += " Сейчас в объявлении есть арендаторы: цифра рыночная, не их договор."

    return {
        "rent": rent,
        "rent_min": rent_min,
        "rent_max": rent_max,
        "yield_pct": yield_pct,
        "payback_years": payback,
        "accuracy": accuracy,
        "rate_eur_m2": eur_m2,
        "rate_label": label,
        "rate_as_of": as_of,
        "source": source,
        "source_url": chosen.get("url") or rates.get("source_url") or "",
        "reason": reason,
        "factors": factors,
    }


def _coef(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _period_label(as_of: str) -> str:
    months = {
        "01": "январь",
        "02": "февраль",
        "03": "март",
        "04": "апрель",
        "05": "май",
        "06": "июнь",
        "07": "июль",
        "08": "август",
        "09": "сентябрь",
        "10": "октябрь",
        "11": "ноябрь",
        "12": "декабрь",
    }
    match = re.match(r"(\d{4})-(\d{2})", as_of or "")
    if not match:
        return "Idealista"
    return f"Idealista, {months.get(match.group(2), match.group(2))} {match.group(1)}"


def decorate(row: dict) -> dict:
    """Добавляет поля оценки прямо в строку для Excel. JSON объявлений не трогает."""
    estimate = estimate_listing(row)
    city = str(row.get("Город") or "").strip()
    neighborhood = str(row.get("Район") or "").strip()
    row["Город / район"] = " · ".join(part for part in (city, neighborhood) if part)

    def put(name: str, value) -> None:
        row[name] = "" if value is None else value

    put("Оценка аренды €/мес", estimate["rent"])
    put("Аренда от €/мес", estimate["rent_min"])
    put("Аренда до €/мес", estimate["rent_max"])
    put("Доходность %", estimate["yield_pct"])
    put("Окупаемость лет", estimate["payback_years"])
    row["Точность оценки"] = estimate["accuracy"]
    return estimate
