"""
TEMP DEV AUTH — I have to replace it with real Cognito JWT verification before deploying.

Usage:
    curl -H "Authorization: Bearer <user-uuid>" ...
"""
from uuid import UUID
from fastapi import Header, HTTPException


async def get_current_user(authorization: str = Header(...)) -> UUID:
    try:
        token = authorization.removeprefix("Bearer ").strip()
        return UUID(token)
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid bearer token. Expected: Bearer <user-uuid>",
        )