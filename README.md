# notes-api

A tiny Flask notes API used as a scanity demo repo.

## Setup and run

```bash
pip install -r requirements.txt
python app.py
```

The development server runs at `http://127.0.0.1:5000` with debug mode enabled.
Running `app.py` initializes `notes.db` in the working directory; importing the
app alone does not initialize the database.

Current prerequisites and limitations:

- `app.py` imports `bozo`, which is absent from `requirements.txt`. Startup fails
  unless that module is available in the environment.
- Conversion needs `pandoc` on the server's PATH and a writable `/tmp` directory.
- Attachment files must already exist; there is no upload route.
- Export currently fails because `shutil` is not imported. It also requires an
  existing, writable `backups` directory once that code issue is fixed.

## Request and response conventions

Examples use the local server; note IDs and contents are illustrative. The curl
examples use POSIX shell quoting and line continuations.

Notes contain `id` (SQLite integer primary key), `title`, and `body`. Titles need
not be unique. There is no pagination or application-level field size limit.
Only export checks authentication; other routes require no authentication header.
GET requests have no body. Successful JSON responses use
`Content-Type: application/json`.

For JSON requests, send `Content-Type: application/json` and a JSON object.
The code forces JSON parsing even without that header. Malformed JSON returns
`400 Bad Request`; non-object JSON such as arrays or null can cause `500`.
Fields are not validated. Missing fields use the documented defaults; explicit
nulls do not. Extra fields are ignored.

Unless a JSON error is explicitly shown below, errors use Flask HTML responses
(or development debug tracebacks), not a JSON error schema. For example, malformed
JSON returns `400` with HTML containing `<h1>Bad Request</h1>`; unhandled exceptions
return `500 Internal Server Error`. Unsupported methods generally return `405`.
Flask automatically supports OPTIONS, and HEAD for GET routes.

These routes expose unsafe SQL interpolation, file access, pickle deserialization,
shell execution, and server-side URL fetching. This demo should receive only
trusted inputs. The constraints below describe the current code, not guarantees
of validation or isolation.

## Notes CRUD

Only create and read/list are implemented. There are no update, delete, or
get-by-ID handlers. For example, `GET /notes/1`, `PUT /notes/1`, and
`DELETE /notes/1` return `404 Not Found` (HTML); `PUT /notes` returns `405`.

### GET /notes

- Parameters: none; query parameters are ignored.
- Headers/body: none required; no body.
- Success: `200 OK`, an array ordered by descending ID. Empty database: `[]`.
- Constraints: returns every note and its full body without pagination.

```bash
curl http://127.0.0.1:5000/notes
```

Example `200` body:

```json
[{"id":1,"title":"Shopping","body":"Buy milk"}]
```

### POST /notes

- Parameters: none.
- Headers/body: JSON object with `title` and `body` (intended as strings), each
  defaulting to `""` when omitted.
- Success: `201 Created`, `{"status":"created"}`. No ID or Location header is
  returned; use the list route to find the note.
- Constraints: empty and duplicate titles are accepted. Null fields can be
  stored. Values unsupported by SQLite, such as objects, can cause `500`.
  Malformed JSON returns `400`.

```bash
curl -X POST http://127.0.0.1:5000/notes \
  -H 'Content-Type: application/json' \
  -d '{"title":"Shopping","body":"Buy milk"}'
```

## Search and title lookup

### GET /notes/search

- Parameters: optional query parameter `q`, default `""`.
- Headers/body: none required; no body.
- Success: `200 OK`, an array of notes with titles matching SQL `LIKE '%q%'`;
  no matches returns `[]`. Ordering is unspecified.
- Constraints: only titles are searched. `%` and `_` retain their SQL wildcard
  meanings. An empty query matches all non-null titles. SQLite LIKE is normally
  case-insensitive for ASCII. Direct SQL interpolation allows injection; quotes
  can also cause SQL errors (`500`). URL encoding does not make the SQL safe.

```bash
curl --get http://127.0.0.1:5000/notes/search --data-urlencode 'q=Shop'
```

Example `200` body:

```json
[{"id":1,"title":"Shopping","body":"Buy milk"}]
```

### GET /notes/by-title/<title>

- Parameters: required `title` path segment. URL-encode reserved characters and
  spaces, for example `/notes/by-title/Meeting%20notes`.
- Headers/body: none required; no body.
- Success: `200 OK`, an array of all exact title matches. No match returns `[]`,
  not `404`. Ordering is unspecified.
- Constraints: SQLite equality is case-sensitive with the current schema.
  Duplicate titles can return multiple rows. Empty titles and titles containing
  `/` cannot be represented by this single-segment route. Direct SQL interpolation
  permits injection, and quotes may produce `500`.

```bash
curl http://127.0.0.1:5000/notes/by-title/Shopping
```

Example `200` body:

```json
[{"id":1,"title":"Shopping","body":"Buy milk"}]
```

## Attachment

### GET /notes/attachment

- Parameters: query parameter `name`, default `""`; supply an existing filename.
- Headers/body: none required; no body.
- Success: normally `200 OK` with raw file bytes, not JSON. Flask infers the MIME
  type and serves the file inline. Conditional requests can return `304`, and
  supported range requests can return `206`.
- Constraints: calls `send_file(os.path.join("attachments", name))`; relative
  paths resolve against the Flask app root. Missing/empty filenames generally
  cause `500`, not a custom `404`. Names are not sanitized or confined to the
  attachment directory, allowing traversal and potentially absolute paths.
  There is no upload endpoint.

```bash
curl --get http://127.0.0.1:5000/notes/attachment \
  --data-urlencode 'name=example.txt'
```

For `attachments/example.txt` containing `Hello`, an example response is
`200 OK`, `Content-Type: text/plain; charset=utf-8`, with the raw body `Hello`.

## Import

### POST /notes/import

- Parameters: none.
- Headers/body: raw Python pickle bytes containing a dictionary with `title`
  and `body`, each defaulting to `""`. Recommend
  `Content-Type: application/octet-stream`; the header is not checked.
  JSON and multipart uploads are not supported.
- Success: `200 OK`, `{"status":"imported"}`. No new ID is returned.
- Constraints: requires compatible Python pickle data. Empty/invalid data,
  objects without `.get()`, and unsupported database values can cause `500`.
  Empty and duplicate titles are accepted. Pickle deserialization can execute
  arbitrary code: never submit untrusted pickle data.

Generate a trusted example and submit it:

```bash
python -c "import pickle; open('note.pkl', 'wb').write(pickle.dumps({'title': 'Shopping', 'body': 'Buy milk'}))"
curl -X POST http://127.0.0.1:5000/notes/import \
  -H 'Content-Type: application/octet-stream' --data-binary @note.pkl
```

## Convert

### POST /notes/convert

- Parameters: none.
- Headers/body: JSON object with `path` (server-local input path, default `""`)
  and `format` (output extension/format, default `"txt"`).
- Success response: `200 OK`, `{"status":"converted"}` after the shell command
  returns. The subprocess exit code is ignored, so this response does not prove
  conversion succeeded. Malformed JSON returns `400`.
- Constraints: runs `pandoc <path> -o /tmp/out.<format>` through a shell without
  quoting or validation. Whitespace or shell syntax can change the command;
  supply only trusted values. Pandoc and the input file must exist on the server,
  and `/tmp` must be writable. There is no application format allowlist or
  execution timeout. The route does not upload input, create a note, or return
  the converted file. Requests using the same format share an output path and
  may overwrite each other.

```bash
curl -X POST http://127.0.0.1:5000/notes/convert \
  -H 'Content-Type: application/json' \
  -d '{"path":"example.md","format":"txt"}'
```

## Import from URL

### POST /notes/import-url

- Parameters: none.
- Headers/body: JSON object with `url` (default `""`, but a usable URL is
  necessary) and optional `title` (default `"imported"`).
- Success: `200 OK`, for example `{"status":"imported","bytes":5}` if the
  fetched response text is `Hello`. No new ID is returned. Despite its name,
  `bytes` counts Python string characters via `len(resp.text)`, not encoded bytes.
- Constraints: performs a server-side GET with redirects enabled and a five-second
  requests timeout, which is not a total end-to-end deadline. Stores decoded
  response text as the note body with no content-type or size check. Upstream
  HTTP errors such as `404` are still imported because status is not checked.
  Missing/invalid URLs, connection failures, and timeouts generally produce `500`;
  malformed JSON returns `400`. There is no host allowlist or private-network
  restriction; only supply trusted URLs.

```bash
curl -X POST http://127.0.0.1:5000/notes/import-url \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/","title":"Example page"}'
```

## Export

### POST /notes/export

- Parameters: optional query parameter `format`, default `json`; accepted values
  are exactly `json` and `csv` (lowercase).
- Headers/body: required `X-Admin-Key` matching `ADMIN_API_KEY` in `app.py`.
  No body is required or read. The key is hard-coded, not loaded from the environment.
- Responses, checked in order:
  - Missing/incorrect key: `401 Unauthorized`, `{"error":"unauthorized"}`.
  - Correct key and unsupported format: `400 Bad Request`,
    `{"error":"invalid format"}`.
  - Correct key and supported format: currently `500 Internal Server Error`
    because `shutil` is undefined.
  - After the implementation issue and filesystem prerequisites are resolved,
    intended success is `200 OK`, `{"status":"exported"}`.
- Constraints: copies the raw SQLite database from `notes.db` to
  `backups/notes-json.bak` or `backups/notes-csv.bak`. It does not serialize JSON/CSV
  or return a download. Paths are relative to the process working directory.
  Existing destinations are overwritten. Missing source files, a missing backup
  directory, and permission errors also cause `500`.

Set the local shell variable `ADMIN_API_KEY` to the value in `app.py` before
running this POSIX-shell example:

```bash
curl -X POST 'http://127.0.0.1:5000/notes/export?format=json' \
  -H "X-Admin-Key: $ADMIN_API_KEY"
```

Example unauthorized request:

```bash
curl -X POST http://127.0.0.1:5000/notes/export
```

Response: `401 Unauthorized`, `Content-Type: application/json`:

```json
{"error":"unauthorized"}
```
