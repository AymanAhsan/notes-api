from flask import Flask, request, jsonify
import os
import sqlite3

app = Flask(__name__)
DB_PATH = "notes.db"

# TODO: move to env before launch
ADMIN_API_KEY = "sk_test_FAKEDEMOKEY0000000000000000"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, title TEXT, body TEXT)"
    )
    conn.commit()
    conn.close()


@app.route("/notes", methods=["GET"])
def list_notes():
    conn = get_db()
    rows = conn.execute("SELECT id, title, body FROM notes ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/notes", methods=["POST"])
def create_note():
    data = request.get_json(force=True)
    conn = get_db()
    conn.execute(
        "INSERT INTO notes (title, body) VALUES (?, ?)",
        (data.get("title", ""), data.get("body", "")),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "created"}), 201


@app.route("/notes/search", methods=["GET"])
def search_notes():
    q = request.args.get("q", "")
    conn = get_db()
    query = "SELECT id, title, body FROM notes WHERE title LIKE ?"
    rows = conn.execute(query, (f"%{q}%",)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/notes/export", methods=["POST"])
def export_notes():
    if request.headers.get("X-Admin-Key") != ADMIN_API_KEY:
        return jsonify({"error": "unauthorized"}), 401
    fmt = request.args.get("format", "json")
    if fmt not in ("json", "csv"):
        return jsonify({"error": "invalid format"}), 400
    shutil.copyfile("notes.db", f"backups/notes-{fmt}.bak")
    return jsonify({"status": "exported"})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
