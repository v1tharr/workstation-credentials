import hmac
import secrets
from datetime import timedelta

from flask import Flask, abort, render_template, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from . import config, crypto, db
from .auth import current_admin
from .util import fmt_ts


def create_app():
    app = Flask(__name__)
    app.config.update(config.load())
    app.config.update(
        SESSION_COOKIE_NAME="creds_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    app.secret_key = app.config["SECRET_KEY"]
    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    crypto.init_app(app)
    db.init_db(app.config["DB_PATH"])
    app.teardown_appcontext(db.close_db)
    app.config["KEY_OK"] = crypto.check_key(app)
    if not app.config["KEY_OK"]:
        app.logger.error("ENCRYPTION_KEY не подходит к данным в БД: пароли рабочих мест не расшифровать")

    from . import admin, student
    app.register_blueprint(student.bp)
    app.register_blueprint(admin.bp, url_prefix="/admin")

    app.jinja_env.filters["ts"] = fmt_ts

    @app.context_processor
    def inject():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["csrf"], "me": current_admin(),
                "min_pw": app.config["MIN_PASSWORD_LEN"],
                "key_ok": app.config["KEY_OK"]}

    @app.before_request
    def check_csrf():
        if request.method == "POST":
            sent = request.form.get("csrf_token", "")
            if not hmac.compare_digest(sent, session.get("csrf", "")):
                abort(400, "CSRF-токен не совпал, обновите страницу")

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'"
        )
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(crypto.KeyMismatch)
    def key_mismatch(e):
        app.logger.error("%s", e)
        return render_template(
            "error.html", e=None, title="Данные нельзя расшифровать",
            message="ENCRYPTION_KEY в .env не совпадает с ключом, которым записаны учётные данные. "
                    "Верните прежний ключ или удалите старые данные и введите их заново."), 500

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(429)
    def error(e):
        return render_template("error.html", e=e), e.code

    return app
