import re
import sqlite3

import pytest
from cryptography.fernet import Fernet

from app import auth, create_app

ADMIN_PW = "correct-horse-battery"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    app = create_app()
    app.testing = True
    with app.app_context():
        auth.create_admin("boss", ADMIN_PW, "owner")
    return app


def token(client, url="/admin/login"):
    html = client.get(url).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def post(client, url, page=None, **data):
    """POST с csrf-токеном, взятым со страницы page (по умолчанию — с самой url)."""
    data["csrf_token"] = token(client, page or url)
    return client.post(url, data=data, follow_redirects=True)


@pytest.fixture
def admin(app):
    c = app.test_client()
    r = post(c, "/admin/login", username="boss", password=ADMIN_PW)
    assert r.status_code == 200 and "Выйти" in r.get_data(as_text=True)
    return c


@pytest.fixture
def raw_db(app):
    def q(sql, *a):
        conn = sqlite3.connect(app.config["DB_PATH"])
        try:
            return conn.execute(sql, a).fetchall()
        finally:
            conn.close()
    return q
