import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from auth import init_auth_db, register_login


class LoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "  correct horse battery staple  "
        cls.password_hash = generate_password_hash(cls.password)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.db"
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, LOGIN_RATE_LIMIT=100)
        register_login(self.app, self.get_db)
        self.client = self.app.test_client()
        with closing(self.get_db()) as conn, conn:
            init_auth_db(conn)
            conn.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
                         ("usr_123", "sam@example.com", self.password_hash, 1))

    def get_db(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def login(self, **overrides):
        data = {"email": "sam@example.com", "password": self.password}
        data.update(overrides)
        return self.client.post("/auth/login", json=data)

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(set(response.json), {"error"})
        self.assertEqual(set(response.json["error"]), {"code", "message"})
        self.assertEqual(response.json["error"]["code"], code)
        self.assertTrue(response.json["error"]["message"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn(self.password, response.get_data(as_text=True))
        self.assertNotIn(self.password_hash, response.get_data(as_text=True))

    def test_success_and_hashed_expiring_token(self):
        with patch("auth.time.time", return_value=1000):
            response = self.login(email=" sam@example.com ", ignored="extra")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        body = response.json
        self.assertEqual(set(body), {"access_token", "token_type", "expires_in", "user"})
        self.assertEqual(body["token_type"], "Bearer")
        self.assertIs(type(body["expires_in"]), int)
        self.assertEqual(body["expires_in"], 3600)
        self.assertEqual(body["user"], {"id": "usr_123", "email": "sam@example.com"})
        self.assertIsInstance(body["access_token"], str)
        self.assertTrue(body["access_token"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        with closing(self.get_db()) as conn:
            token = dict(conn.execute("SELECT * FROM access_tokens").fetchone())
        self.assertEqual(token, {
            "token_hash": hashlib.sha256(body["access_token"].encode()).hexdigest(),
            "user_id": "usr_123", "expires_at": 4600,
        })
        self.assertNotIn(body["access_token"], str(token))
        self.assertNotIn(self.password_hash, response.get_data(as_text=True))
        self.assertNotIn(self.password, response.get_data(as_text=True))
        self.assertNotEqual(self.login().json["access_token"], body["access_token"])

    def test_invalid_input(self):
        values = [None, [], "text", 123, True, {}, {"email": "sam@example.com"},
                  {"password": "secret"}]
        for field in ("email", "password"):
            for invalid in (None, "", 5, False, [], {}):
                values.append({"email": "sam@example.com", "password": "secret", field: invalid})
        values.append({"email": "   ", "password": "secret"})
        for value in values:
            with self.subTest(value=value):
                response = self.client.post("/auth/login", data=json.dumps(value),
                                            content_type="application/json")
                self.assert_error(response, 400, "invalid_request")
        for body, content_type in [("{", "application/json"), ("", "application/json"),
                                   ('{"email":"sam@example.com","password":"secret"}', "text/plain")]:
            self.assert_error(self.client.post("/auth/login", data=body, content_type=content_type),
                              400, "invalid_request")

    def test_credential_failures_are_identical(self):
        responses = [self.login(password="wrong"), self.login(email="missing@example.com"),
                     self.login(password=self.password.strip()),
                     self.login(email="' OR 1=1 --")]
        with closing(self.get_db()) as conn, conn:
            conn.execute("UPDATE users SET active = 0")
        responses.append(self.login())
        with closing(self.get_db()) as conn, conn:
            conn.execute("UPDATE users SET active = 1, password_hash = 'unusable'")
        responses.append(self.login())
        for response in responses:
            self.assert_error(response, 401, "invalid_credentials")
            self.assertEqual(response.json, responses[0].json)
        self.assertEqual(responses[0].json["error"]["message"], "Email or password is incorrect.")
        with closing(self.get_db()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM access_tokens").fetchone()[0], 0)

    def test_rate_limit_shared_across_clients_and_expires(self):
        self.app.config["LOGIN_RATE_LIMIT"] = 2
        with patch("auth.time.time", return_value=1000):
            self.assert_error(self.login(password="bad"), 401, "invalid_credentials")
            self.assert_error(self.client.post("/auth/login", data="{"), 400, "invalid_request")
            second_app = Flask("second_worker")
            second_app.config["LOGIN_RATE_LIMIT"] = 2
            register_login(second_app, self.get_db)
            limited = second_app.test_client().post("/auth/login", json={})
            self.assert_error(limited, 429, "rate_limited")
            self.assertEqual(limited.headers["Retry-After"], "60")
            spoofed = self.client.post("/auth/login", json={}, headers={"X-Forwarded-For": "1.2.3.4"})
            self.assert_error(spoofed, 429, "rate_limited")
            different_peer = self.client.post("/auth/login", json={},
                                               environ_overrides={"REMOTE_ADDR": "127.0.0.2"})
            self.assert_error(different_peer, 400, "invalid_request")
        with patch("auth.time.time", return_value=1060):
            self.assertEqual(self.login().status_code, 200)

    def test_failure_hides_exception_and_credentials_even_in_debug(self):
        self.app.debug = True
        secret = "database secret " + self.password
        with patch("auth.check_password_hash", side_effect=RuntimeError(secret)):
            with self.assertLogs(self.app.logger, level="ERROR") as captured:
                response = self.login()
        self.assert_error(response, 500, "internal_error")
        self.assertNotIn(secret, response.get_data(as_text=True))
        self.assertNotIn(secret, str(captured.output))
        self.assertNotIn("Traceback", str(captured.output))

    def test_database_failure_is_json(self):
        with closing(self.get_db()) as conn, conn:
            conn.execute("DROP TABLE login_attempts")
        with self.assertLogs(self.app.logger, level="ERROR"):
            self.assert_error(self.login(), 500, "internal_error")

    def test_app_initialization_and_route_wiring(self):
        # Isolate the unrelated, pre-existing optional import without changing it.
        spec = importlib.util.spec_from_file_location("notes_app_under_test", Path(__file__).with_name("app.py"))
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"bozo": types.ModuleType("bozo")}):
            spec.loader.exec_module(module)
        module.DB_PATH = str(self.path)
        module.init_db()
        module.init_db()
        client = module.app.test_client()
        response = client.post("/auth/login", json={"email": "sam@example.com", "password": self.password})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["id"], "usr_123")
        self.assertEqual(client.post("/notes", json={"title": "retained", "body": "text"}).status_code, 201)
        module.init_db()
        self.assertEqual(client.get("/notes").json[0]["title"], "retained")


if __name__ == "__main__":
    unittest.main()
