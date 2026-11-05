import re

import pytest
from cryptography.fernet import Fernet

from app import auth, create_app
from app.db import get_db
from conftest import ADMIN_PW, post, token

CSV = "login;password\npc01;Sekret-01\npc02;Sekret-02\n"


def make_exam(admin, title="Экзамен А", csv=CSV):
    post(admin, "/admin/exams/new", page="/admin/exams", title=title)
    exam_id = max(int(x) for x in re.findall(r"/admin/exams/(\d+)\"", admin.get("/admin/exams").get_data(as_text=True)))
    if csv:
        r = post(admin, f"/admin/exams/{exam_id}/import", page=f"/admin/exams/{exam_id}", csv=csv)
        assert "добавлено" in r.get_data(as_text=True)
    return exam_id


def slot_ids(admin, exam_id):
    html = admin.get(f"/admin/exams/{exam_id}").get_data(as_text=True)
    return [int(x) for x in re.findall(rf"/admin/exams/{exam_id}/slots/(\d+)\"", html)]


def student_code(client):
    html = client.get("/").get_data(as_text=True)
    return re.search(r'class="code-box">(\d{6})<', html).group(1)


def activate(admin, code, slot_id):
    return post(admin, "/admin/activate", page="/admin/", code=code, slot_id=slot_id).get_data(as_text=True)


# ── конфигурация ───────────────────────────────────────────

def test_refuses_to_start_without_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()


def test_rejects_bad_encryption_key(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("ENCRYPTION_KEY", "not-a-key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        create_app()


def test_key_from_file(monkeypatch, tmp_path):
    f = tmp_path / "enc"
    f.write_text(Fernet.generate_key().decode() + "\n")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("ENCRYPTION_KEY_FILE", str(f))
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    create_app()


# ── админы ─────────────────────────────────────────────────

def test_admin_pages_require_login(app):
    c = app.test_client()
    for url in ("/admin/", "/admin/exams", "/admin/admins", "/admin/audit"):
        r = c.get(url)
        assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_login_wrong_password_and_lockout(app):
    c = app.test_client()
    for _ in range(5):
        r = post(c, "/admin/login", username="boss", password="nope")
        assert "Неверный логин или пароль" in r.get_data(as_text=True)
    r = post(c, "/admin/login", username="boss", password=ADMIN_PW)
    assert "Слишком много попыток" in r.get_data(as_text=True)


def test_unknown_user_same_error(app):
    r = post(app.test_client(), "/admin/login", username="ghost", password="whatever")
    assert "Неверный логин или пароль" in r.get_data(as_text=True)


def test_csrf_required(admin):
    r = admin.post("/admin/exams/new", data={"title": "без токена"})
    assert r.status_code == 400


def test_only_owner_manages_admins(admin, app):
    post(admin, "/admin/admins", username="helper", password="helper-pass-123", role="admin")
    helper = app.test_client()
    post(helper, "/admin/login", username="helper", password="helper-pass-123")
    assert helper.get("/admin/").status_code == 200
    assert helper.get("/admin/admins").status_code == 403


def test_short_password_rejected(admin):
    r = post(admin, "/admin/admins", username="weak", password="123", role="admin")
    assert "Пароль короче" in r.get_data(as_text=True)


def test_disabled_admin_loses_access_immediately(admin, app):
    post(admin, "/admin/admins", username="temp", password="temp-pass-1234", role="admin")
    temp = app.test_client()
    post(temp, "/admin/login", username="temp", password="temp-pass-1234")
    assert temp.get("/admin/").status_code == 200
    aid = int(re.search(r"/admin/admins/(\d+)/toggle", admin.get("/admin/admins").get_data(as_text=True)).group(1))
    post(admin, f"/admin/admins/{aid}/toggle", page="/admin/admins")
    assert temp.get("/admin/").status_code == 302


# ── шифрование ─────────────────────────────────────────────

def test_passwords_encrypted_at_rest(admin, raw_db):
    make_exam(admin)
    blobs = [r[0] for r in raw_db("SELECT data FROM slots")]
    assert len(blobs) == 2
    assert all("Sekret" not in b and "pc01" not in b for b in blobs)


def test_secret_not_shown_in_admin_list_but_visible_to_student(admin, app):
    eid = make_exam(admin)
    assert "Sekret-01" not in admin.get(f"/admin/exams/{eid}").get_data(as_text=True)

    student = app.test_client()
    code = student_code(student)
    activate(admin, code, slot_ids(admin, eid)[0])
    page = student.get("/").get_data(as_text=True)
    assert "pc01" in page and "Sekret-01" in page


# ── поток участника ────────────────────────────────────────

def test_full_flow_and_revoke(admin, app):
    eid = make_exam(admin)
    s = app.test_client()
    code = student_code(s)
    assert s.get("/api/status").get_json() == {"status": "pending"}
    assert student_code(s) == code                      # код стабилен между обновлениями

    out = activate(admin, code, slot_ids(admin, eid)[0])
    assert "Экзамен А / pc01" in out
    assert s.get("/api/status").get_json() == {"status": "active"}

    post(admin, "/admin/revoke", page="/admin/", code=code)
    assert s.get("/api/status").get_json() == {"status": "gone"}
    assert student_code(s) != code                      # получает новый код


def test_slot_cannot_be_used_twice(admin, app):
    eid = make_exam(admin)
    slot = slot_ids(admin, eid)[0]
    a, b = app.test_client(), app.test_client()
    ca, cb = student_code(a), student_code(b)
    activate(admin, ca, slot)
    out = activate(admin, cb, slot)
    assert "уже занято" in out
    assert b.get("/api/status").get_json() == {"status": "pending"}


def test_two_exams_in_parallel(admin, app):
    e1 = make_exam(admin, "Экзамен 1")
    e2 = make_exam(admin, "Экзамен 2", csv="login;password\nsec01;Other-Pass\n")
    s1, s2 = app.test_client(), app.test_client()
    c1, c2 = student_code(s1), student_code(s2)
    activate(admin, c1, slot_ids(admin, e1)[0])
    activate(admin, c2, slot_ids(admin, e2)[0])
    p1, p2 = s1.get("/").get_data(as_text=True), s2.get("/").get_data(as_text=True)
    assert "Sekret-01" in p1 and "Other-Pass" not in p1
    assert "Other-Pass" in p2 and "Sekret-01" not in p2


def test_closing_exam_cuts_participants(admin, app):
    eid = make_exam(admin)
    s = app.test_client()
    activate(admin, student_code(s), slot_ids(admin, eid)[0])
    post(admin, f"/admin/exams/{eid}/status", page=f"/admin/exams/{eid}")
    r = s.get("/")
    assert "Sekret-01" not in r.get_data(as_text=True)
    assert s.get("/api/status").get_json()["status"] != "active"


def test_closed_exam_slots_not_offered(admin, app):
    eid = make_exam(admin)
    post(admin, f"/admin/exams/{eid}/status", page=f"/admin/exams/{eid}")
    student_code(app.test_client())
    assert "pc01" not in admin.get("/admin/").get_data(as_text=True)


def test_pending_cap_evicts_oldest_instead_of_blocking(admin, app, raw_db):
    app.config["MAX_PENDING"] = 3
    codes = [student_code(app.test_client()) for _ in range(6)]   # у каждого клиента своя cookie
    left = [r[0] for r in raw_db("SELECT code FROM sessions ORDER BY id")]
    assert left == codes[-3:]                       # остались три последних, 429 нет


def test_expired_pending_codes_purged(admin, app, raw_db):
    import sqlite3, time
    student_code(app.test_client())
    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.execute("UPDATE sessions SET created_at = ?", (time.time() - 3600,))
    conn.commit(); conn.close()
    student_code(app.test_client())
    assert len(raw_db("SELECT 1 FROM sessions")) == 1


# ── настройка экзамена ─────────────────────────────────────

def test_custom_columns_and_cards(admin, app):
    eid = make_exam(admin, csv=None)
    cols = "host; Хост\nuser; Пользователь\npassword; Пароль; secret"
    cards = '[{"title":"SSH","fields":[{"label":"Команда","value":"ssh {user}@{host}"}]}]'
    r = post(admin, f"/admin/exams/{eid}", title="ИБ", columns=cols, cards=cards)
    assert "Сохранено" in r.get_data(as_text=True)
    post(admin, f"/admin/exams/{eid}/import", page=f"/admin/exams/{eid}",
         csv="host,user,password\n10.0.0.5,alice,pw1\n")
    s = app.test_client()
    activate(admin, student_code(s), slot_ids(admin, eid)[0])
    assert "ssh alice@10.0.0.5" in s.get("/").get_data(as_text=True)


@pytest.mark.parametrize("cards,msg", [
    ("[not json", "JSON"),
    ('[{"title":"x","fields":[{"label":"a","value":"{nope}"}]}]', "нет колонок nope"),
    ('{"a":1}', "список"),
])
def test_invalid_cards_rejected(admin, cards, msg):
    eid = make_exam(admin, csv=None)
    r = post(admin, f"/admin/exams/{eid}", title="t", columns="login; L", cards=cards)
    assert msg in r.get_data(as_text=True)


def test_bad_column_key_rejected(admin):
    eid = make_exam(admin, csv=None)
    r = post(admin, f"/admin/exams/{eid}", title="t", columns="Bad Key; L", cards="[]")
    assert "ключ" in r.get_data(as_text=True)


def test_csv_missing_column(admin):
    eid = make_exam(admin, csv=None)
    r = post(admin, f"/admin/exams/{eid}/import", page=f"/admin/exams/{eid}", csv="login\npc1\n")
    assert "нет колонок: password" in r.get_data(as_text=True)


def test_csv_upsert_and_edit_keeps_blank_secret(admin, app):
    eid = make_exam(admin)
    post(admin, f"/admin/exams/{eid}/import", page=f"/admin/exams/{eid}", csv="login,password\npc01,New-Pass\npc09,P9\n")
    ids = slot_ids(admin, eid)
    assert len(ids) == 3
    # правка без ввода пароля не стирает его
    post(admin, f"/admin/exams/{eid}/slots/{ids[0]}", login="pc01")
    s = app.test_client()
    activate(admin, student_code(s), ids[0])
    assert "New-Pass" in s.get("/").get_data(as_text=True)


def test_clone_exam_copies_layout_not_slots(admin):
    e1 = make_exam(admin)
    post(admin, "/admin/exams/new", page="/admin/exams", title="Копия", source=f"exam:{e1}")
    ids = [int(x) for x in re.findall(r"/admin/exams/(\d+)\"", admin.get("/admin/exams").get_data(as_text=True))]
    clone = max(ids)
    assert clone != e1 and slot_ids(admin, clone) == []


def test_delete_exam_removes_data(admin, raw_db):
    eid = make_exam(admin)
    post(admin, f"/admin/exams/{eid}/delete", page=f"/admin/exams/{eid}")
    assert raw_db("SELECT COUNT(*) FROM slots")[0][0] == 0


# ── безопасность вывода ────────────────────────────────────

def test_values_are_html_escaped(admin, app):
    eid = make_exam(admin, csv='login;password\n"<script>alert(1)</script>";"a\'b\\"c"\n')
    s = app.test_client()
    activate(admin, student_code(s), slot_ids(admin, eid)[0])
    page = s.get("/").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_non_http_link_not_rendered_as_anchor(admin, app):
    eid = make_exam(admin, csv="login;password\njavascript:alert(1);x\n")
    cards = '[{"title":"t","fields":[{"label":"l","value":"{login}","link":true}]}]'
    post(admin, f"/admin/exams/{eid}", title="t", columns="login; L\npassword; P; secret", cards=cards)
    s = app.test_client()
    activate(admin, student_code(s), slot_ids(admin, eid)[0])
    assert 'href="javascript' not in s.get("/").get_data(as_text=True)


def test_security_headers_and_no_store(app):
    r = app.test_client().get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"
    assert "fonts.googleapis" not in r.get_data(as_text=True)


def test_audit_log_records_actions_without_secrets(admin, app):
    eid = make_exam(admin)
    activate(admin, student_code(app.test_client()), slot_ids(admin, eid)[0])
    page = admin.get("/admin/audit").get_data(as_text=True)
    assert "activate" in page and "exam_create" in page and "Sekret" not in page


# ── шаблоны и JSON ─────────────────────────────────────────

def latest_exam(admin):
    return max(int(x) for x in re.findall(r"/admin/exams/(\d+)\"", admin.get("/admin/exams").get_data(as_text=True)))


def test_create_from_preset(admin, app):
    post(admin, "/admin/exams/new", page="/admin/exams", title="Чемпионат", source="preset:programming")
    eid = latest_exam(admin)
    page = admin.get(f"/admin/exams/{eid}").get_data(as_text=True)
    assert "ad_login" in page and "Gogs" in page


def test_unknown_preset_rejected(admin):
    r = post(admin, "/admin/exams/new", page="/admin/exams", title="x", source="preset:../../etc/passwd")
    assert "Неизвестный шаблон" in r.get_data(as_text=True)


def test_import_legacy_config_json(admin, app):
    legacy = ('[{"ad_login":"ws01","ad_password":"Pw-1","db_login":"ws01","db_password":"Pw-2"},'
              '{"ad_login":"ws02","ad_password":"Pw-3","db_login":"ws02","db_password":"Pw-4","smb_login":"x"}]')
    r = post(admin, "/admin/exams/import-json", page="/admin/exams", title="Старый", json=legacy)
    assert "загружено мест: 2" in r.get_data(as_text=True)
    eid = latest_exam(admin)
    page = admin.get(f"/admin/exams/{eid}").get_data(as_text=True)
    assert "smb_login" in page and "Pw-1" not in page      # пароли скрыты в админке
    s = app.test_client()
    activate(admin, student_code(s), slot_ids(admin, eid)[0])
    assert "Pw-1" in s.get("/").get_data(as_text=True)


def test_template_export_has_no_passwords_and_reimports(admin):
    eid = make_exam(admin)
    r = admin.get(f"/admin/exams/{eid}/export")
    assert r.headers["Content-Disposition"].startswith("attachment")
    body = r.get_data(as_text=True)
    assert "Sekret" not in body and "pc01" not in body and "slots" not in body
    out = post(admin, "/admin/exams/import-json", page="/admin/exams", json=body)
    assert "загружено мест: 0" in out.get_data(as_text=True)


def test_import_template_with_slots(admin):
    tpl = ('{"title":"Лаба 3","columns":[{"key":"host","label":"Хост"},{"key":"pw","label":"Пароль","secret":true}],'
           '"cards":[{"title":"VM","badge":"SSH","fields":[{"label":"Хост","value":"{host}"}]}],'
           '"slots":[{"host":"vm1","pw":"a"},{"host":"vm2","pw":"b"}]}')
    r = post(admin, "/admin/exams/import-json", page="/admin/exams", json=tpl)
    assert "Лаба 3" in r.get_data(as_text=True) and "загружено мест: 2" in r.get_data(as_text=True)


@pytest.mark.parametrize("payload,msg", [
    ("not json", "Это не JSON"),
    ('{"columns": "x"}', "columns"),
    ('{"columns":[{"key":"Bad Key"}]}', "ключ"),
    ('{"columns":[{"key":"a"}],"cards":[{"title":"t","fields":[{"label":"l","value":"{zzz}"}]}]}', "нет колонок zzz"),
    ('[]', "Ожидается список"),
])
def test_bad_json_import(admin, payload, msg):
    r = post(admin, "/admin/exams/import-json", page="/admin/exams", title="t", json=payload)
    assert msg in r.get_data(as_text=True)


def test_badge_rendered_and_fonts_local(admin, app):
    post(admin, "/admin/exams/new", page="/admin/exams", title="B", source="preset:programming")
    eid = latest_exam(admin)
    post(admin, f"/admin/exams/{eid}/import", page=f"/admin/exams/{eid}",
         csv="ad_login,ad_password,db_login,db_password\nu1,p1,d1,q1\n")
    s = app.test_client()
    activate(admin, student_code(s), slot_ids(admin, eid)[0])
    page = s.get("/").get_data(as_text=True)
    assert 'class="card-badge">Gogs<' in page
    css = s.get("/static/app.css")
    assert b"fonts/inter-cyrillic-400-normal.woff2" in css.data
    assert s.get("/static/fonts/inter-cyrillic-400-normal.woff2").status_code == 200


def test_min_password_len_configurable(tmp_path, monkeypatch):
    from conftest import token
    from cryptography.fernet import Fernet
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("MIN_PASSWORD_LEN", "6")
    app = create_app()
    from app import auth
    with app.app_context():
        auth.create_admin("boss", "sixsix", "owner")          # 6 символов проходит
        with pytest.raises(ValueError, match="короче 6"):
            auth.check_new_password("12345")


def test_csv_header_template_and_default_tab(admin):
    eid = make_exam(admin, csv=None)
    page = admin.get(f"/admin/exams/{eid}").get_data(as_text=True)
    assert 'data-default="layout"' in page                  # пустой экзамен открывается на настройке страницы
    r = admin.get(f"/admin/exams/{eid}/slots.csv")
    assert r.get_data(as_text=True) == "login;password\n"
    post(admin, f"/admin/exams/{eid}/import", page=f"/admin/exams/{eid}", csv=CSV)
    assert 'data-default="places"' in admin.get(f"/admin/exams/{eid}").get_data(as_text=True)


def test_student_page_never_blocked_for_many_visitors(app):
    for _ in range(30):
        assert app.test_client().get("/").status_code == 200


def test_secret_field_masked_on_student_page():
    from app.util import render_cards
    cols = [{"key": "login", "label": "L", "secret": False}, {"key": "pw", "label": "P", "secret": True}]
    cards = [{"title": "t", "fields": [{"label": "a", "value": "{login}"}, {"label": "b", "value": "{pw}"}]}]
    out = render_cards(cards, {"login": "u", "pw": "x"}, cols)[0]["fields"]
    assert [f["masked"] for f in out] == [False, True]


def test_secret_field_masked_on_student_page():
    from app.util import render_cards
    cols = [{"key": "login", "label": "L", "secret": False}, {"key": "pw", "label": "P", "secret": True}]
    cards = [{"title": "t", "fields": [{"label": "a", "value": "{login}"}, {"label": "b", "value": "{pw}"}]}]
    out = render_cards(cards, {"login": "u", "pw": "x"}, cols)[0]["fields"]
    assert [f["masked"] for f in out] == [False, True]


def test_wrong_key_detected_on_start(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    import app as appmod
    monkeypatch.setenv("SECRET_KEY", "s" * 40)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    a = appmod.create_app()
    assert a.config["KEY_OK"]
    with a.app_context():
        from app import util
        from app.db import get_db
        db = get_db()
        db.execute("INSERT INTO exams (title, columns, cards, created_at) VALUES ('e','[]','[]',0)")
        util.upsert_slots(1, [{"key": "login", "label": "L", "secret": False}], [{"login": "a"}])
        db.commit()
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert appmod.create_app().config["KEY_OK"] is False


def test_owner_can_delete_admin_but_not_self(app, admin):
    with app.app_context():
        auth.create_admin("temp", "temp-password-1", "admin")
    page = admin.get("/admin/admins").get_data(as_text=True)
    ids = [int(x) for x in re.findall(r"/admin/admins/(\d+)/delete", page)]
    assert len(ids) == 1                       # у себя кнопки «Удалить» нет
    r = post(admin, f"/admin/admins/{ids[0]}/delete", page="/admin/admins")
    assert "temp" not in r.get_data(as_text=True).split("<tbody>")[1]
    boss = int(re.search(r"/admin/admins/(\d+)/password", page).group(1))
    # если id совпал бы с id temp, берём любой другой: проверяем отказ на себе
    with app.app_context():
        me = get_db().execute("SELECT id FROM admins WHERE username='boss'").fetchone()["id"]
    r = post(admin, f"/admin/admins/{me}/delete", page="/admin/admins")
    assert "Себя удалить нельзя" in r.get_data(as_text=True)
