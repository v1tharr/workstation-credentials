import os


def env(name, default=None):
    """Значение из ENV; если задана NAME_FILE — читаем из файла (Docker secrets)."""
    path = os.environ.get(name + "_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return os.environ.get(name, default)


def flag(name):
    return (env(name, "0") or "0").lower() in ("1", "true", "yes")


def load():
    cfg = {
        "SECRET_KEY": env("SECRET_KEY"),
        "ENCRYPTION_KEY": env("ENCRYPTION_KEY"),
        "DB_PATH": env("DB_PATH", "data/creds.db"),
        "TRUST_PROXY": flag("TRUST_PROXY"),
        "SESSION_COOKIE_SECURE": flag("COOKIE_SECURE"),
        "PENDING_TTL_MIN": int(env("PENDING_TTL_MIN", "30")),
        "MAX_PENDING": int(env("MAX_PENDING", "1000")),
        "MIN_PASSWORD_LEN": int(env("MIN_PASSWORD_LEN", "6")),
        "UI_TZ_OFFSET_HOURS": int(env("UI_TZ_OFFSET_HOURS", "7")),
    }
    missing = [k for k in ("SECRET_KEY", "ENCRYPTION_KEY") if not cfg[k]]
    if missing:
        raise RuntimeError(
            f"Не заданы обязательные переменные: {', '.join(missing)}. "
            "Сгенерировать: python manage.py gen-keys"
        )
    if len(cfg["SECRET_KEY"]) < 32:
        raise RuntimeError("SECRET_KEY слишком короткий (нужно >= 32 символов)")
    return cfg
