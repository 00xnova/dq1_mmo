from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.jwk import KeySet

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


def is_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def get_authorization_url(state: str) -> str:
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "state": state,
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def verify_id_token(id_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        jwks_resp = await client.get(GOOGLE_JWKS_URL)
        jwks_resp.raise_for_status()
        key_set = KeySet.import_key_set(jwks_resp.json())

    token = jwt.decode(id_token, key_set)
    claims = token.claims

    if claims.get("aud") != GOOGLE_CLIENT_ID:
        raise ValueError("Invalid audience")
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise ValueError("Invalid issuer")
    if not claims.get("email"):
        raise ValueError("Email missing from Google token")

    return {
        "google_id": claims["sub"],
        "email": claims["email"],
        "name": claims.get("name") or claims["email"].split("@")[0],
        "email_verified": claims.get("email_verified", False),
    }
