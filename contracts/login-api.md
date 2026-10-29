# Login API contract

## Purpose

Authenticate an existing account with its email address and password. This contract defines the HTTP interface; persistence, password hashing, and token signing remain implementation details.

## Endpoint

`POST /auth/login`

The endpoint accepts JSON and returns JSON. It does not create accounts, refresh tokens, or provide a logout operation.

### Request

`Content-Type: application/json`

```json
{
  "email": "sam@example.com",
  "password": "correct horse battery staple"
}
```

Both fields are required non-empty strings. The server may trim surrounding whitespace from the email, but must not trim or otherwise alter the password. Unknown fields are ignored. Missing, empty, non-string, or malformed JSON input returns `400 Bad Request`.

### Successful response

`200 OK`

```json
{
  "access_token": "<opaque-or-signed-token>",
  "token_type": "Bearer",
  "expires_in": 3600,
  "user": {
    "id": "usr_123",
    "email": "sam@example.com"
  }
}
```

`access_token` is a non-empty credential. `token_type` is always `Bearer`. `expires_in` is the token lifetime in seconds as a positive integer. The `user` object contains the stable user identifier and canonical account email. The response must not include a password, password hash, or other authentication secret.

Clients send the token on authenticated requests using:

```http
Authorization: Bearer <access_token>
```

### Errors

All error responses use `Content-Type: application/json` and this shape:

```json
{
  "error": {
    "code": "invalid_credentials",
    "message": "Email or password is incorrect."
  }
}
```

| Status | Code | Meaning |
| --- | --- | --- |
| `400` | `invalid_request` | Malformed JSON or missing/invalid required fields. |
| `401` | `invalid_credentials` | Account does not exist, password is incorrect, or account cannot authenticate. Do not reveal which condition occurred. |
| `429` | `rate_limited` | Login attempts are temporarily limited. Include `Retry-After` when available. |
| `500` | `internal_error` | Unexpected server failure; do not expose internals. |

Credential failures must use the same status and response shape regardless of whether the email exists. Do not log submitted passwords or return them in any response.

## Example

```bash
curl -X POST http://127.0.0.1:5000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"sam@example.com","password":"correct horse battery staple"}'
```

## Acceptance criteria

- Valid credentials return `200` with a bearer access token, positive `expires_in`, and the public user identity.
- Invalid credentials return `401` with the generic `invalid_credentials` error.
- Malformed or invalid input returns `400` with the `invalid_request` error.
- Every documented error has the shared JSON error shape and exposes no stack trace or secret.
- Login attempts can be rate limited, with `429` and `Retry-After` when applicable.
