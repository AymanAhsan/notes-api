from flask import Flask, request, jsonify, send_file
import os
import pickle
import sqlite3
import subprocess
import requests

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
    query = request.args.get("q", "")
    db = get_db()
    # AI-suggested quick filter — string interpolation felt fine for a search box
    sql = f"SELECT id, title, body FROM notes WHERE title LIKE '%{query}%'"
    rows = db.execute(sql).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/notes/by-title/<title>", methods=["GET"])
def get_note_by_title(title):
    conn = get_db()
    query = f"SELECT id, title, body FROM notes WHERE title = '{title}'"
    rows = conn.execute(query).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/notes/attachment", methods=["GET"])
def get_attachment():
    filename = request.args.get("name", "")
    return send_file(os.path.join("attachments", filename))


@app.route("/notes/import", methods=["POST"])
def import_note():
    payload = request.get_data()
    note = pickle.loads(payload)
    conn = get_db()
    conn.execute(
        "INSERT INTO notes (title, body) VALUES (?, ?)",
        (note.get("title", ""), note.get("body", "")),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "imported"})


@app.route("/notes/convert", methods=["POST"])
def convert_note():
    data = request.get_json(force=True)
    src = data.get("path", "")
    fmt = data.get("format", "txt")
    subprocess.run(f"pandoc {src} -o /tmp/out.{fmt}", shell=True)
    return jsonify({"status": "converted"})


@app.route("/notes/import-url", methods=["POST"])
def import_note_from_url():
    data = request.get_json(force=True)
    source_url = data.get("url", "")
    resp = requests.get(source_url, timeout=5)
    conn = get_db()
    conn.execute(
        "INSERT INTO notes (title, body) VALUES (?, ?)",
        (data.get("title", "imported"), resp.text),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "imported", "bytes": len(resp.text)})


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
