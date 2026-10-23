"""Local OAuth provider stub used only by the isolated Compose E2E stack."""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

app = FastAPI(title="Trace OAuth test provider")
_private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
_key_id = "trace-e2e-google"


def _redirect_to_callback(request: Request, provider: str) -> RedirectResponse:
    redirect_uri = request.query_params.get("redirect_uri")
    state = request.query_params.get("state")
    if not redirect_uri or not state:
        return RedirectResponse("/invalid-request", status_code=302)
    code = f"{provider}-success"
    if provider == "google":
        nonce = request.query_params.get("nonce")
        if not nonce:
            return RedirectResponse("/invalid-request", status_code=302)
        code = f"google-success.{nonce}"
    return RedirectResponse(
        f"{redirect_uri}?{urlencode({'code': code, 'state': state})}", status_code=302
    )


@app.get("/github/authorize")
async def github_authorize(request: Request) -> RedirectResponse:
    return _redirect_to_callback(request, "github")


@app.post("/github/token")
async def github_token() -> dict[str, str]:
    return {"access_token": "github-e2e-access-token", "token_type": "bearer"}


@app.get("/github/user")
async def github_user() -> dict[str, int]:
    return {"id": 7_101}


@app.get("/github/user/emails")
async def github_emails() -> list[dict[str, object]]:
    return [{"email": "github.e2e@example.test", "primary": True, "verified": True}]


@app.get("/google/authorize")
async def google_authorize(request: Request) -> RedirectResponse:
    return _redirect_to_callback(request, "google")


@app.post("/google/token")
async def google_token(request: Request) -> dict[str, str]:
    values = parse_qs((await request.body()).decode("ascii"))
    code = values.get("code", [""])[0]
    _, separator, nonce = code.partition(".")
    if not separator or not nonce:
        return {"access_token": "google-e2e-access-token"}
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "aud": "google-e2e-client",
            "email": "google.e2e@example.test",
            "email_verified": True,
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "iss": "https://accounts.google.com",
            "nonce": nonce,
            "sub": "google-e2e-subject",
        },
        _private_key,
        algorithm="RS256",
        headers={"kid": _key_id},
    )
    return {
        "access_token": "google-e2e-access-token",
        "id_token": token,
        "token_type": "bearer",
    }


@app.get("/google/jwks")
async def google_jwks() -> dict[str, list[dict[str, object]]]:
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_private_key.public_key()))
    key.update({"alg": "RS256", "kid": _key_id, "use": "sig"})
    return {"keys": [key]}
