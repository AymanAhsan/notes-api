# Login implementation

`POST /auth/login` implements `contracts/login-api.md` from
`contract/login-api` at `ecd9c0e538ee20356bb63a0dba0adb80650913bf`.

Run `init_db()` (also called by `python app.py`) to create the account, token,
and rate-limit tables alongside notes. Existing notes are preserved.
Accounts must be provisioned out of band in `users`, with a stable string `id`,
canonical `email`, a Werkzeug `generate_password_hash(password)` value in
`password_hash`, and `active=1`. There is no registration endpoint or seeded
account. Email lookup is case sensitive and trims surrounding whitespace;
passwords are used unchanged.

Successful login issues a random 256-bit opaque bearer token, valid for 3600
seconds. Only its SHA-256 digest, account ID, and expiry are stored. Future
authenticated endpoints must hash the supplied bearer token and check its
stored expiry and account status. This change does not add authentication
requirements to the existing notes routes.

All attempts, including malformed requests and successful logins, count toward
a fixed window limit per peer IP: 10 attempts per 60 seconds by default.
Configure `LOGIN_RATE_LIMIT` and `LOGIN_RATE_WINDOW` on the Flask app to change
these positive limits. SQLite transactions share counters across workers using
the same database. Forwarding headers are not trusted; deployments behind a
proxy must configure trusted proxy handling appropriately or clients will
share the proxy's limit. Deployments on separate databases need a shared limiter.

Login responses disable caching, and login failures never log request data or
exception details. Use HTTPS for bearer credentials and disable the development
debugger in deployments. Protect database files and backups as authentication
data. Expired token records are removed on successful login.

Run coverage with `python -m unittest -v test_auth`. These tests exercise the
login module without the pre-existing unresolved `bozo` import in `app.py`.
