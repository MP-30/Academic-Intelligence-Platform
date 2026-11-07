"""JWT verification against Cognito."""
import logging
from functools import lru_cache
from uuid import UUID

import httpx
from fastapi import Header, HTTPException
from jose import JWTError, jwt

from academic_ai.config import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _jwks() -> dict:
    url = (
        f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}/.well-known/jwks.json"
    )
    return httpx.get(url, timeout=10).json()


async def get_current_user(authorization: str = Header(...)) -> UUID:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        headers = jwt.get_unverified_header(token)
        key = next(k for k in _jwks()["keys"] if k["kid"] == headers["kid"])
        claims = jwt.decode(
            token,
            key,
            algorithms=[headers["alg"]],
            audience=settings.cognito_client_id,
            issuer=(
                f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
                f"{settings.cognito_user_pool_id}"
            ),
        )
    except (JWTError, StopIteration, KeyError) as e:
        log.info("jwt verify failed: %s", e)
        raise HTTPException(401, "Invalid or expired token")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(401, "Token missing sub claim")
    try:
        return UUID(sub)
    except ValueError:
        raise HTTPException(401, "Invalid sub claim format")
