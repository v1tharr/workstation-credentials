"""Служебные команды: ключи, админы, импорт старого config.json, демо-данные.

    python manage.py gen-keys
    python manage.py create-admin [--username NAME] [--role owner|admin]
    python manage.py import-json config.json --exam "Название" [--cards examples/old-config.cards.json]
    python manage.py demo
"""
import argparse
import getpass
import json
import secrets
import sqlite3
import sys
import time

from cryptography.fernet import Fernet


def gen_keys(_args):
    print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
    print(f"ENCRYPTION_KEY={Fernet.generate_key().decode()}")


def make_app():
    from app import create_app
    return create_app()


def ask_password():
    pw = getpass.getpass("Пароль: ")
    if pw != getpass.getpass("Ещё раз: "):
        sys.exit("Пароли не совпали")
    return pw


def create_admin(args):
    from app import auth
    app = make_app()
    with app.app_context():
        name = args.username or input("Логин: ").strip()
        try:
            auth.create_admin(name, ask_password(), args.role)
        except (ValueError, sqlite3.IntegrityError) as e:
            sys.exit(f"Не создано: {e}")
    print(f"Админ {name} ({args.role}) создан")


def import_json(args):
    """Загрузка из старого config.json (список) или из шаблона (объект с columns/cards/slots)."""
    from app.db import get_db
    from app.util import parse_cards, parse_template, upsert_slots
    with open(args.file, encoding="utf-8") as f:
        tpl = parse_template(json.load(f))
    if args.cards:
        with open(args.cards, encoding="utf-8") as f:
            tpl["cards"] = parse_cards(f.read(), tpl["columns"])
    if not tpl["rows"]:
        sys.exit("В файле нет рабочих мест")

    app = make_app()
    with app.app_context():
        db = get_db()
        cur = db.execute(
            "INSERT INTO exams (title, columns, cards, created_at) VALUES (?,?,?,?)",
            (args.exam, json.dumps(tpl["columns"], ensure_ascii=False),
             json.dumps(tpl["cards"], ensure_ascii=False), time.time()))
        created, _ = upsert_slots(cur.lastrowid, tpl["columns"], tpl["rows"])
        db.commit()
    print(f"Мероприятие «{args.exam}»: загружено мест — {created}. "
          f"Исходный {args.file} теперь можно удалить.")


def demo(_args):
    """Два параллельных мероприятия с фейковыми данными — для проверки дома."""
    from app import auth
    from app.db import get_db
    from app.util import parse_columns, upsert_slots
    app = make_app()
    with app.app_context():
        db = get_db()
        if db.execute("SELECT COUNT(*) FROM exams").fetchone()[0]:
            sys.exit("БД не пустая, демо не загружаю")
        if not db.execute("SELECT 1 FROM admins").fetchone():
            auth.create_admin("owner", "demo-owner-pass", "owner")
            print("Админ: owner / demo-owner-pass  (только для демо!)")

        def add(title, cols_text, cards, rows):
            cols = parse_columns(cols_text)
            cur = db.execute(
                "INSERT INTO exams (title, columns, cards, created_at) VALUES (?,?,?,?)",
                (title, json.dumps(cols, ensure_ascii=False),
                 json.dumps(cards, ensure_ascii=False), time.time()))
            upsert_slots(cur.lastrowid, cols, rows)

        add("Демо: программирование", "ad_login; AD логин\nad_password; AD пароль; secret\ndb_login; БД логин\ndb_password; БД пароль; secret",
            [{"title": "Домен", "icon": "🔑", "fields": [
                {"label": "Логин", "value": "{ad_login}"}, {"label": "Пароль", "value": "{ad_password}", "accent": True}]},
             {"title": "База данных", "icon": "🗄️", "fields": [
                {"label": "Портал", "value": "http://git.demo.lab:3000", "link": True},
                {"label": "Логин", "value": "{db_login}"}, {"label": "Пароль", "value": "{db_password}"}]}],
            [{"ad_login": f"demo_dev{i:02}", "ad_password": secrets.token_urlsafe(9),
              "db_login": f"ws{i:02}", "db_password": secrets.token_urlsafe(9)} for i in range(1, 6)])
        add("Демо: информационная безопасность", "host; Хост\nuser; Пользователь\npassword; Пароль; secret",
            [{"title": "Стенд", "icon": "🛡️", "fields": [
                {"label": "Хост", "value": "{host}"}, {"label": "SSH", "value": "ssh {user}@{host}"},
                {"label": "Пароль", "value": "{password}", "accent": True}]}],
            [{"host": f"10.20.0.{10 + i}", "user": f"sec{i:02}", "password": secrets.token_urlsafe(9)}
             for i in range(1, 4)])
        db.commit()
    print("Демо-мероприятия созданы")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-keys").set_defaults(fn=gen_keys)
    a = sub.add_parser("create-admin")
    a.add_argument("--username")
    a.add_argument("--role", choices=["owner", "admin"], default="owner")
    a.set_defaults(fn=create_admin)
    j = sub.add_parser("import-json")
    j.add_argument("file")
    j.add_argument("--exam", required=True)
    j.add_argument("--cards")
    j.set_defaults(fn=import_json)
    sub.add_parser("demo").set_defaults(fn=demo)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
