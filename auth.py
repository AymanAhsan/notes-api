"""Login persistence and HTTP interface; accounts are provisioned out of band."""

from contextlib import closing
import hashlib
import math
import secrets
import time

from flask import jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash


TOKEN_LIFETIME = 3600
# Match the cost of checking a real account when an email is unknown.
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32))


def init_auth_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS access_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
            client TEXT PRIMARY KEY,
            window_start REAL NOT NULL,
            attempts INTEGER NOT NULL
        );
    """)


def register_login(app, get_db):
    app.config.setdefault("LOGIN_RATE_LIMIT", 10)
    app.config.setdefault("LOGIN_RATE_WINDOW", 60)

    def error(status, code, message, retry_after=None):
        response = jsonify(error={"code": code, "message": message})
        response.status_code = status
        response.headers["Cache-Control"] = "no-store"
        if retry_after is not None:
            response.headers["Retry-After"] = str(retry_after)
        return response

    @app.post("/auth/login")
    def login():
        try:
            now = time.time()
            # Use the actual peer, not a caller-controlled forwarding header.
            client = request.remote_addr or "unknown"
            window = app.config["LOGIN_RATE_WINDOW"]
            with closing(get_db()) as conn, conn:
                # Serialize read/update across workers sharing the database.
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "DELETE FROM login_attempts WHERE window_start <= ?",
                    (now - window,),
                )
                attempt = conn.execute(
                    "SELECT window_start, attempts FROM login_attempts WHERE client = ?",
                    (client,),
                ).fetchone()
                if attempt and attempt["attempts"] >= app.config["LOGIN_RATE_LIMIT"]:
                    return error(429, "rate_limited", "Too many login attempts. Try again later.",
                                 max(1, math.ceil(attempt["window_start"] + window - now)))
                conn.execute(
                    "INSERT INTO login_attempts VALUES (?, ?, 1) "
                    "ON CONFLICT(client) DO UPDATE SET attempts = attempts + 1",
                    (client, now),
                )

            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return error(400, "invalid_request", "Email and password must be non-empty strings.")
            email, password = data.get("email"), data.get("password")
            if (not isinstance(email, str) or not email.strip()
                    or not isinstance(password, str) or not password):
                return error(400, "invalid_request", "Email and password must be non-empty strings.")

            with closing(get_db()) as conn, conn:
                user = conn.execute(
                    "SELECT id, email, password_hash, active FROM users WHERE email = ?",
                    (email.strip(),),
                ).fetchone()
                password_hash = user["password_hash"] if user else DUMMY_HASH
                try:
                    valid = check_password_hash(password_hash, password)
                except (ValueError, TypeError):
                    valid = False
                if not valid or not user or not user["active"]:
                    return error(401, "invalid_credentials", "Email or password is incorrect.")

                token = secrets.token_urlsafe(32)
                issued_at = time.time()
                conn.execute("DELETE FROM access_tokens WHERE expires_at <= ?", (issued_at,))
                conn.execute(
                    "INSERT INTO access_tokens VALUES (?, ?, ?)",
                    (hashlib.sha256(token.encode()).hexdigest(), user["id"], issued_at + TOKEN_LIFETIME),
                )
                identity = {"id": user["id"], "email": user["email"]}
            response = jsonify(access_token=token, token_type="Bearer",
                               expires_in=TOKEN_LIFETIME, user=identity)
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception:
            # Exception text/tracebacks can contain SQL values or credentials.
            app.logger.error("Login failed due to an internal error.")
            return error(500, "internal_error", "An internal error occurred.")
