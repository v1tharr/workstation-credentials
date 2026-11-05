import json
import sqlite3
import time

from flask import (Blueprint, Response, abort, flash, redirect, render_template,
                   request, session, url_for)

from . import auth, crypto
from .auth import current_admin, login_required, owner_required
from .db import get_db
from .util import (DEFAULT_COLUMNS, audit, columns_to_text, default_cards,
                   export_template, list_presets, load_preset, parse_cards,
                   parse_columns, parse_csv, parse_template, render_cards,
                   slot_data, upsert_slots)

bp = Blueprint("admin", __name__)


def log(action, details=""):
    audit(current_admin()["username"], action, details)


def get_exam(exam_id):
    row = get_db().execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
    if row is None:
        abort(404)
    return row


def revoke_exam_sessions(exam_id):
    cur = get_db().execute(
        "UPDATE sessions SET status='revoked' WHERE status='active' AND slot_id IN "
        "(SELECT id FROM slots WHERE exam_id=?)", (exam_id,))
    return cur.rowcount


# ── вход / выход ───────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        admin, error = auth.try_login(request.form.get("username", "").strip(),
                                      request.form.get("password", ""))
        if admin:
            session.clear()
            session.permanent = True
            session["admin_id"] = admin["id"]
            return redirect(url_for("admin.panel"))
    return render_template("admin/login.html", error=error)


@bp.post("/logout")
def logout():
    session.pop("admin_id", None)
    return redirect(url_for("admin.login"))


# ── главная: коды и привязка ───────────────────────────────

@bp.get("/")
@login_required
def panel():
    db = get_db()
    pending = db.execute("SELECT * FROM sessions WHERE status='pending' ORDER BY created_at DESC").fetchall()
    active = db.execute(
        "SELECT x.*, s.label, e.title FROM sessions x "
        "JOIN slots s ON s.id = x.slot_id JOIN exams e ON e.id = s.exam_id "
        "WHERE x.status='active' ORDER BY x.activated_at DESC").fetchall()
    free = db.execute(
        "SELECT s.id, s.label, e.title FROM slots s JOIN exams e ON e.id = s.exam_id "
        "WHERE e.status='open' AND NOT EXISTS "
        "(SELECT 1 FROM sessions x WHERE x.slot_id = s.id AND x.status='active') "
        "ORDER BY e.title, s.label").fetchall()
    groups = {}
    for r in free:
        groups.setdefault(r["title"], []).append(r)
    return render_template("admin/panel.html", pending=pending, active=active, groups=groups)


@bp.post("/activate")
@login_required
def activate():
    db = get_db()
    code = request.form.get("code", "").strip()
    slot = db.execute(
        "SELECT s.label, e.title, e.status FROM slots s JOIN exams e ON e.id = s.exam_id WHERE s.id=?",
        (request.form.get("slot_id", type=int),)).fetchone()
    if slot is None or slot["status"] != "open":
        flash("Выберите рабочее место открытого мероприятия", "err")
        return redirect(url_for("admin.panel"))
    try:
        cur = db.execute(
            "UPDATE sessions SET status='active', slot_id=?, activated_at=?, activated_by=? "
            "WHERE code=? AND status='pending'",
            (request.form.get("slot_id", type=int), time.time(), current_admin()["username"], code))
    except sqlite3.IntegrityError:
        flash("Это рабочее место уже занято — сначала сбросьте прежний сеанс", "err")
        return redirect(url_for("admin.panel"))
    if cur.rowcount == 0:
        flash(f"Код {code} уже не ожидает активации", "err")
    else:
        log("activate", f"{code} -> {slot['title']} / {slot['label']}")
        flash(f"Код {code} → {slot['title']} / {slot['label']}", "ok")
    db.commit()
    return redirect(url_for("admin.panel"))


@bp.post("/revoke")
@login_required
def revoke():
    db = get_db()
    code = request.form.get("code", "").strip()
    db.execute("UPDATE sessions SET status='revoked' WHERE code=?", (code,))
    log("revoke", code)
    db.commit()
    flash(f"Код {code} сброшен", "ok")
    return redirect(url_for("admin.panel"))


@bp.post("/pending/delete")
@login_required
def pending_delete():
    db = get_db()
    if request.form.get("all"):
        n = db.execute("DELETE FROM sessions WHERE status='pending'").rowcount
    else:
        n = db.execute("DELETE FROM sessions WHERE status='pending' AND code=?",
                       (request.form.get("code", ""),)).rowcount
    db.commit()
    flash(f"Удалено ожидающих кодов: {n}", "ok")
    return redirect(url_for("admin.panel"))


# ── мероприятия ───────────────────────────────────────────────

@bp.get("/exams")
@login_required
def exams():
    rows = get_db().execute(
        "SELECT e.*, "
        " (SELECT COUNT(*) FROM slots WHERE exam_id = e.id) AS n_slots, "
        " (SELECT COUNT(*) FROM sessions x JOIN slots s ON s.id = x.slot_id "
        "   WHERE s.exam_id = e.id AND x.status='active') AS n_active "
        "FROM exams e ORDER BY e.status, e.created_at DESC").fetchall()
    return render_template("admin/exams.html", exams=rows, presets=list_presets())


def create_exam(title, columns, cards, rows=()):
    db = get_db()
    cur = db.execute(
        "INSERT INTO exams (title, columns, cards, created_at) VALUES (?,?,?,?)",
        (title, json.dumps(columns, ensure_ascii=False),
         json.dumps(cards, ensure_ascii=False), time.time()))
    created = upsert_slots(cur.lastrowid, columns, rows)[0] if rows else 0
    return cur.lastrowid, created


@bp.post("/exams/new")
@login_required
def exam_new():
    title = request.form.get("title", "").strip()
    if not title:
        flash("Укажите название мероприятия", "err")
        return redirect(url_for("admin.exams"))

    # source: "" — пустой, "preset:<id>" — встроенный шаблон, "exam:<id>" — копия мероприятия
    kind, _, ref = request.form.get("source", "").partition(":")
    try:
        if kind == "preset":
            tpl = load_preset(ref)
            columns, cards = tpl["columns"], tpl["cards"]
        elif kind == "exam":
            base = get_exam(int(ref))
            columns, cards = json.loads(base["columns"]), json.loads(base["cards"])
        else:
            columns = parse_columns(DEFAULT_COLUMNS)
            cards = default_cards(columns)
    except ValueError as e:
        flash(str(e), "err")
        return redirect(url_for("admin.exams"))

    exam_id, _ = create_exam(title, columns, cards)
    log("exam_create", f"{title} ({request.form.get('source') or 'пустой'})")
    get_db().commit()
    return redirect(url_for("admin.exam_edit", exam_id=exam_id))


@bp.post("/exams/import-json")
@login_required
def exam_import_json():
    """Создать мероприятие из JSON: шаблон (columns/cards/slots) или старый config.json."""
    text = request.form.get("json", "")
    upload = request.files.get("file")
    if upload and upload.filename:
        text = upload.read().decode("utf-8-sig", errors="replace")
    try:
        tpl = parse_template(json.loads(text))
    except json.JSONDecodeError as e:
        flash(f"Это не JSON: {e}", "err")
        return redirect(url_for("admin.exams"))
    except ValueError as e:
        flash(str(e), "err")
        return redirect(url_for("admin.exams"))

    title = request.form.get("title", "").strip() or tpl["title"]
    if not title:
        flash("Укажите название мероприятия", "err")
        return redirect(url_for("admin.exams"))
    exam_id, created = create_exam(title, tpl["columns"], tpl["cards"], tpl["rows"])
    log("exam_import_json", f"{title}: мест {created}")
    get_db().commit()
    flash(f"Мероприятие создано, загружено мест: {created}", "ok")
    return redirect(url_for("admin.exam_edit", exam_id=exam_id))


@bp.get("/exams/<int:exam_id>/slots.csv")
@login_required
def slots_csv_header(exam_id):
    """Заготовка CSV: одна строка заголовка с ключами колонок."""
    keys = [c["key"] for c in json.loads(get_exam(exam_id)["columns"])]
    return Response(";".join(keys) + "\n", mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename=exam-{exam_id}-slots.csv"})


@bp.get("/exams/<int:exam_id>/export")
@login_required
def exam_export(exam_id):
    exam = get_exam(exam_id)
    body = json.dumps(export_template(exam["title"], json.loads(exam["columns"]),
                                      json.loads(exam["cards"])), ensure_ascii=False, indent=2)
    log("exam_export", f"#{exam_id} (без паролей)")
    get_db().commit()
    return Response(body, mimetype="application/json", headers={
        "Content-Disposition": f"attachment; filename=exam-{exam_id}-template.json"})


@bp.route("/exams/<int:exam_id>", methods=["GET", "POST"])
@login_required
def exam_edit(exam_id):
    db = get_db()
    exam = get_exam(exam_id)
    columns = json.loads(exam["columns"])
    form = {"title": exam["title"], "columns": columns_to_text(columns),
            "cards": json.dumps(json.loads(exam["cards"]), ensure_ascii=False, indent=2)}

    if request.method == "POST":
        form = {k: request.form.get(k, "") for k in form}
        try:
            title = form["title"].strip()
            if not title:
                raise ValueError("Название не может быть пустым")
            new_cols = parse_columns(form["columns"])
            new_cards = parse_cards(form["cards"], new_cols)
        except ValueError as e:
            flash(str(e), "err")
        else:
            db.execute("UPDATE exams SET title=?, columns=?, cards=? WHERE id=?",
                       (title, json.dumps(new_cols, ensure_ascii=False),
                        json.dumps(new_cards, ensure_ascii=False), exam_id))
            log("exam_edit", f"#{exam_id} {title}")
            db.commit()
            flash("Сохранено", "ok")
            return redirect(url_for("admin.exam_edit", exam_id=exam_id, _anchor="layout"))

    slots = db.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM sessions x WHERE x.slot_id = s.id AND x.status='active') AS busy "
        "FROM slots s WHERE exam_id=? ORDER BY label", (exam_id,)).fetchall()
    rows = [{"id": s["id"], "busy": s["busy"], "data": slot_data(s)} for s in slots]
    return render_template("admin/exam.html", exam=exam, columns=columns, form=form, slots=rows,
                           default_tab="places" if rows else "layout")


@bp.post("/exams/<int:exam_id>/status")
@login_required
def exam_status(exam_id):
    db = get_db()
    exam = get_exam(exam_id)
    new = "closed" if exam["status"] == "open" else "open"
    db.execute("UPDATE exams SET status=? WHERE id=?", (new, exam_id))
    msg = "Мероприятие открыто" if new == "open" else "Мероприятие закрыто"
    if new == "closed":
        msg += f", сброшено сеансов: {revoke_exam_sessions(exam_id)}"
    log("exam_" + new, f"#{exam_id} {exam['title']}")
    db.commit()
    flash(msg, "ok")
    return redirect(url_for("admin.exam_edit", exam_id=exam_id))


@bp.post("/exams/<int:exam_id>/revoke-all")
@login_required
def exam_revoke_all(exam_id):
    get_exam(exam_id)
    n = revoke_exam_sessions(exam_id)
    log("exam_revoke_all", f"#{exam_id}: {n}")
    get_db().commit()
    flash(f"Сброшено сеансов: {n}", "ok")
    return redirect(url_for("admin.exam_edit", exam_id=exam_id))


@bp.post("/exams/<int:exam_id>/delete")
@login_required
def exam_delete(exam_id):
    db = get_db()
    exam = get_exam(exam_id)
    revoke_exam_sessions(exam_id)
    db.execute("DELETE FROM exams WHERE id=?", (exam_id,))
    log("exam_delete", f"#{exam_id} {exam['title']}")
    db.commit()
    flash(f"Мероприятие «{exam['title']}» удалено вместе с учётными данными", "ok")
    return redirect(url_for("admin.exams"))


# ── рабочие места ──────────────────────────────────────────

@bp.post("/exams/<int:exam_id>/import")
@login_required
def slots_import(exam_id):
    exam = get_exam(exam_id)
    columns = json.loads(exam["columns"])
    text = request.form.get("csv", "")
    upload = request.files.get("file")
    if upload and upload.filename:
        text = upload.read().decode("utf-8-sig", errors="replace")
    try:
        created, updated = upsert_slots(exam_id, columns, parse_csv(text, columns))
    except ValueError as e:
        flash(str(e), "err")
    else:
        log("slots_import", f"#{exam_id}: +{created}, обновлено {updated}")
        get_db().commit()
        flash(f"Импорт: добавлено {created}, обновлено {updated}", "ok")
    return redirect(url_for("admin.exam_edit", exam_id=exam_id, _anchor="places"))


@bp.route("/exams/<int:exam_id>/slots/new", methods=["GET", "POST"])
@bp.route("/exams/<int:exam_id>/slots/<int:slot_id>", methods=["GET", "POST"])
@login_required
def slot_edit(exam_id, slot_id=None):
    db = get_db()
    exam = get_exam(exam_id)
    columns = json.loads(exam["columns"])
    slot = None
    data = {c["key"]: "" for c in columns}
    if slot_id:
        slot = db.execute("SELECT * FROM slots WHERE id=? AND exam_id=?", (slot_id, exam_id)).fetchone()
        if slot is None:
            abort(404)
        data.update(slot_data(slot))

    if request.method == "POST":
        new = {}
        for c in columns:
            val = request.form.get(c["key"], "").strip()
            # пустой секрет при редактировании = «не менять»
            new[c["key"]] = data[c["key"]] if (slot and c["secret"] and not val) else val
        label = new[columns[0]["key"]]
        if not label:
            flash(f"Поле «{columns[0]['label']}» обязательно", "err")
        else:
            try:
                if slot:
                    db.execute("UPDATE slots SET label=?, data=? WHERE id=?",
                               (label, crypto.encrypt(new), slot_id))
                else:
                    db.execute("INSERT INTO slots (exam_id, label, data) VALUES (?,?,?)",
                               (exam_id, label, crypto.encrypt(new)))
            except sqlite3.IntegrityError:
                flash(f"Рабочее место «{label}» уже есть в этом мероприятии", "err")
            else:
                log("slot_save", f"#{exam_id} {label}")
                db.commit()
                return redirect(url_for("admin.exam_edit", exam_id=exam_id, _anchor="places"))
        data = {k: v for k, v in new.items()}

    return render_template("admin/slot.html", exam=exam, columns=columns, slot=slot,
                           data=data)


@bp.post("/exams/<int:exam_id>/slots/<int:slot_id>/delete")
@login_required
def slot_delete(exam_id, slot_id):
    db = get_db()
    row = db.execute("SELECT label FROM slots WHERE id=? AND exam_id=?", (slot_id, exam_id)).fetchone()
    if row is None:
        abort(404)
    db.execute("UPDATE sessions SET status='revoked' WHERE slot_id=? AND status='active'", (slot_id,))
    db.execute("DELETE FROM slots WHERE id=?", (slot_id,))
    log("slot_delete", f"#{exam_id} {row['label']}")
    db.commit()
    return redirect(url_for("admin.exam_edit", exam_id=exam_id, _anchor="places"))


@bp.get("/exams/<int:exam_id>/slots/<int:slot_id>/preview")
@login_required
def slot_preview(exam_id, slot_id):
    exam = get_exam(exam_id)
    slot = get_db().execute("SELECT * FROM slots WHERE id=? AND exam_id=?", (slot_id, exam_id)).fetchone()
    if slot is None:
        abort(404)
    cards = render_cards(json.loads(exam["cards"]), slot_data(slot),
                         json.loads(exam["columns"]))
    return render_template("dashboard.html", cards=cards, exam=exam["title"],
                           label=slot["label"], preview=True)


# ── администраторы ─────────────────────────────────────────

@bp.route("/admins", methods=["GET", "POST"])
@owner_required
def admins():
    db = get_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        role = "owner" if request.form.get("role") == "owner" else "admin"
        try:
            if not username:
                raise ValueError("Укажите логин")
            auth.create_admin(username, request.form.get("password", ""), role)
        except ValueError as e:
            flash(str(e), "err")
        except sqlite3.IntegrityError:
            flash("Такой логин уже есть", "err")
        else:
            log("admin_create", f"{username} ({role})")
            db.commit()
            flash(f"Администратор {username} создан", "ok")
        return redirect(url_for("admin.admins"))
    rows = db.execute("SELECT * FROM admins ORDER BY username").fetchall()
    return render_template("admin/admins.html", admins=rows)


@bp.post("/admins/<int:admin_id>/toggle")
@owner_required
def admin_toggle(admin_id):
    db = get_db()
    row = db.execute("SELECT * FROM admins WHERE id=?", (admin_id,)).fetchone()
    if row is None:
        abort(404)
    if row["id"] == current_admin()["id"]:
        flash("Себя отключить нельзя", "err")
    else:
        db.execute("UPDATE admins SET active = 1 - active WHERE id=?", (admin_id,))
        log("admin_toggle", row["username"])
        db.commit()
    return redirect(url_for("admin.admins"))


@bp.post("/admins/<int:admin_id>/delete")
@owner_required
def admin_delete(admin_id):
    db = get_db()
    row = db.execute("SELECT * FROM admins WHERE id=?", (admin_id,)).fetchone()
    if row is None:
        abort(404)
    if row["id"] == current_admin()["id"]:
        flash("Себя удалить нельзя", "err")
    else:
        db.execute("DELETE FROM admins WHERE id=?", (admin_id,))
        log("admin_delete", row["username"])
        db.commit()
        flash(f"Администратор {row['username']} удалён", "ok")
    return redirect(url_for("admin.admins"))


@bp.post("/admins/<int:admin_id>/password")
@owner_required
def admin_reset_password(admin_id):
    row = get_db().execute("SELECT username FROM admins WHERE id=?", (admin_id,)).fetchone()
    if row is None:
        abort(404)
    try:
        auth.set_password(admin_id, request.form.get("password", ""))
    except ValueError as e:
        flash(str(e), "err")
    else:
        log("admin_password_reset", row["username"])
        get_db().commit()
        flash(f"Пароль {row['username']} изменён", "ok")
    return redirect(url_for("admin.admins"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    me = current_admin()
    if request.method == "POST":
        _, err = auth.try_login(me["username"], request.form.get("old", ""))
        try:
            if err:
                raise ValueError("Текущий пароль указан неверно")
            auth.set_password(me["id"], request.form.get("new", ""))
        except ValueError as e:
            flash(str(e), "err")
        else:
            log("password_change")
            get_db().commit()
            flash("Пароль изменён", "ok")
            return redirect(url_for("admin.account"))
    return render_template("admin/account.html")


@bp.get("/audit")
@login_required
def audit_log():
    rows = get_db().execute("SELECT * FROM audit ORDER BY id DESC LIMIT 300").fetchall()
    return render_template("admin/audit.html", rows=rows)
