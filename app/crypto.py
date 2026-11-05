import json

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


class KeyMismatch(RuntimeError):
    """Данные в БД зашифрованы другим ENCRYPTION_KEY, чем тот, с которым запущено приложение."""


def init_app(app):
    try:
        app.extensions["fernet"] = Fernet(app.config["ENCRYPTION_KEY"].encode())
    except ValueError as e:
        raise RuntimeError(
            "ENCRYPTION_KEY некорректен, ожидается ключ Fernet "
            "(python manage.py gen-keys)"
        ) from e


def check_key(app):
    """Пробует расшифровать одно рабочее место. True, если ключ подходит (или данных ещё нет)."""
    import sqlite3
    conn = sqlite3.connect(app.config["DB_PATH"])
    try:
        row = conn.execute("SELECT data FROM slots LIMIT 1").fetchone()
    finally:
        conn.close()
    if row is None:
        return True
    try:
        app.extensions["fernet"].decrypt(row[0].encode())
        return True
    except InvalidToken:
        return False


def encrypt(obj):
    raw = json.dumps(obj, ensure_ascii=False).encode()
    return current_app.extensions["fernet"].encrypt(raw).decode()


def decrypt(token):
    try:
        raw = current_app.extensions["fernet"].decrypt(token.encode())
    except InvalidToken:
        raise KeyMismatch(
            "Не удалось расшифровать данные: ENCRYPTION_KEY не совпадает с тем, "
            "которым они были записаны"
        )
    return json.loads(raw)
