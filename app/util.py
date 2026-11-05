import csv
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone

from flask import current_app

from . import crypto
from .db import get_db

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
PLACEHOLDER = re.compile(r"\{(\w+)\}")

DEFAULT_COLUMNS = "login; Логин\npassword; Пароль; secret"
PRESETS_DIR = os.path.join(os.path.dirname(__file__), "presets")


def default_cards(columns):
    """Одна карточка со всеми колонками подряд — разумная заготовка."""
    return [{
        "title": "Учётные данные", "subtitle": "Доступ к рабочему месту", "icon": "🔑",
        "fields": [{"label": c["label"], "value": "{%s}" % c["key"]} for c in columns],
    }]


def fmt_ts(ts):
    if not ts:
        return "—"
    tz = timezone(timedelta(hours=current_app.config["UI_TZ_OFFSET_HOURS"]))
    return datetime.fromtimestamp(ts, tz).strftime("%d.%m %H:%M:%S")


def audit(admin, action, details=""):
    db = get_db()
    db.execute(
        "INSERT INTO audit (ts, admin, action, details) VALUES (strftime('%s','now'), ?, ?, ?)",
        (admin, action, details),
    )


# ── колонки ────────────────────────────────────────────────

def parse_columns(text):
    """Строки вида `key; Подпись; secret` -> список колонок."""
    cols, seen = [], set()
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(";")]
        key = parts[0]
        if not KEY_RE.match(key):
            raise ValueError(
                f"Строка {n}: ключ «{key}» — только a-z, 0-9 и _, начинается с буквы"
            )
        if key in seen:
            raise ValueError(f"Строка {n}: ключ «{key}» повторяется")
        seen.add(key)
        label = parts[1] if len(parts) > 1 and parts[1] else key
        cols.append({"key": key, "label": label, "secret": "secret" in parts[2:]})
    if not cols:
        raise ValueError("Нужна хотя бы одна колонка")
    return cols


def columns_to_text(cols):
    return "\n".join(
        "; ".join([c["key"], c["label"]] + (["secret"] if c["secret"] else []))
        for c in cols
    )


# ── карточки ───────────────────────────────────────────────

def parse_cards(text, columns):
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON карточек: {e}")
    if not isinstance(raw, list) or not raw:
        raise ValueError("Карточки: ожидается непустой список")

    keys = {c["key"] for c in columns}
    cards = []
    for i, card in enumerate(raw, 1):
        if not isinstance(card, dict) or not isinstance(card.get("title"), str):
            raise ValueError(f"Карточка {i}: нужно поле title")
        fields = card.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ValueError(f"Карточка {i}: нужен непустой список fields")
        clean = []
        for f in fields:
            if (not isinstance(f, dict) or not isinstance(f.get("label"), str)
                    or not isinstance(f.get("value"), str)):
                raise ValueError(f"Карточка {i}: у поля должны быть строки label и value")
            unknown = set(PLACEHOLDER.findall(f["value"])) - keys
            if unknown:
                raise ValueError(
                    f"Карточка {i}, «{f['label']}»: нет колонок {', '.join(sorted(unknown))}"
                )
            clean.append({"label": f["label"], "value": f["value"],
                          "accent": bool(f.get("accent")), "link": bool(f.get("link"))})
        cards.append({
            "title": card["title"],
            "subtitle": str(card.get("subtitle", "")),
            "icon": str(card.get("icon", "")),
            "badge": str(card.get("badge", "")),
            "fields": clean,
        })
    return cards


def render_cards(cards, data, columns=()):
    """Подставляет значения слота в {плейсхолдеры}. Ссылками становятся только http(s),
    а поля с данными из колонок «это пароль» помечаются masked (участник открывает их кнопкой)."""
    secret = {c["key"] for c in columns if c["secret"]}
    def fill(s):
        return PLACEHOLDER.sub(lambda m: str(data.get(m.group(1), "")), s)

    out = []
    for card in cards:
        fields = []
        for f in card["fields"]:
            val = fill(f["value"])
            fields.append({
                "label": f["label"],
                "value": val,
                "accent": f.get("accent", False),
                "link": f.get("link", False) and val.lower().startswith(("http://", "https://")),
                "masked": bool(secret & set(PLACEHOLDER.findall(f["value"]))),
            })
        out.append({**card, "fields": fields})
    return out


# ── слоты ──────────────────────────────────────────────────

def upsert_slots(exam_id, columns, rows):
    """rows — список словарей {key: value}. Метка слота = первая колонка."""
    db = get_db()
    keys = [c["key"] for c in columns]
    created = updated = 0
    for row in rows:
        data = {k: str(row.get(k) or "").strip() for k in keys}
        label = data[keys[0]]
        if not label:
            continue
        exists = db.execute(
            "SELECT 1 FROM slots WHERE exam_id=? AND label=?", (exam_id, label)
        ).fetchone()
        db.execute(
            "INSERT INTO slots (exam_id, label, data) VALUES (?,?,?) "
            "ON CONFLICT(exam_id, label) DO UPDATE SET data=excluded.data",
            (exam_id, label, crypto.encrypt(data)),
        )
        updated += bool(exists)
        created += not exists
    return created, updated


def parse_csv(text, columns):
    text = text.lstrip("﻿").strip()
    if not text:
        raise ValueError("Пустой CSV")
    head = text.splitlines()[0]
    delim = max(",;\t", key=head.count)
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    fields = [(h or "").strip() for h in reader.fieldnames or []]
    missing = [c["key"] for c in columns if c["key"] not in fields]
    if missing:
        raise ValueError(f"В заголовке CSV нет колонок: {', '.join(missing)}")
    rows = [{(k or "").strip(): v for k, v in r.items()} for r in reader]
    if len(rows) > 2000:
        raise ValueError("Слишком много строк (максимум 2000)")
    return rows


def slot_data(row):
    return crypto.decrypt(row["data"])


# ── шаблоны, импорт и экспорт мероприятия ─────────────────

def list_presets():
    out = []
    for fn in sorted(os.listdir(PRESETS_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(PRESETS_DIR, fn), encoding="utf-8") as f:
                out.append({"id": fn[:-5], "name": json.load(f)["name"]})
    return out


def load_preset(preset_id):
    if not re.fullmatch(r"[a-z0-9_-]+", preset_id):
        raise ValueError("Неизвестный шаблон")
    path = os.path.join(PRESETS_DIR, preset_id + ".json")
    if not os.path.exists(path):
        raise ValueError("Неизвестный шаблон")
    with open(path, encoding="utf-8") as f:
        return parse_template(json.load(f))


def parse_template(data):
    """Принимает объект-шаблон или старый config.json (список словарей).

    Возвращает dict: title, columns, cards, rows. Ошибки — ValueError.
    """
    if isinstance(data, list):                      # старый формат config.json
        if not data or not all(isinstance(r, dict) for r in data):
            raise ValueError("Ожидается список записей-словарей")
        keys = list(dict.fromkeys(k for r in data for k in r))
        columns = parse_columns("\n".join(
            f"{k}; {k}" + ("; secret" if "password" in k else "") for k in keys))
        return {"title": "", "columns": columns, "cards": default_cards(columns), "rows": data}

    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект с колонками и карточками")
    raw_cols = data.get("columns")
    if not isinstance(raw_cols, list) or not all(isinstance(c, dict) for c in raw_cols):
        raise ValueError("В JSON нужен список columns из объектов {key, label, secret}")
    columns = parse_columns(columns_to_text(
        [{"key": str(c.get("key", "")), "label": str(c.get("label", "")),
          "secret": bool(c.get("secret"))} for c in raw_cols]))
    cards = parse_cards(json.dumps(data["cards"]), columns) if data.get("cards") \
        else default_cards(columns)
    rows = data.get("slots") or []
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError("slots должен быть списком объектов")
    return {"title": str(data.get("title", "")), "columns": columns, "cards": cards, "rows": rows}


def export_template(title, columns, cards):
    """Шаблон для переноса между инсталляциями. Рабочих мест и паролей здесь нет."""
    return {"title": title, "columns": columns, "cards": cards}
