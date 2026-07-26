from flask import Flask, request, jsonify
import sqlite3

app = Flask(__name__)
DB_PATH = "notes.db"


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


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
