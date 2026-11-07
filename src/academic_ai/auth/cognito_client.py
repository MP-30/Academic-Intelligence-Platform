import logging

import boto3
from fastapi import HTTPException

from academic_ai.config import settings

log = logging.getLogger(__name__)
_client = None


def _cognito():
    global _client
    if _client is None:
        _client = boto3.client("cognito-idp", region_name=settings.cognito_region)
    return _client


def register(email: str, password: str) -> dict:
    try:
        resp = _cognito().admin_create_user(
            UserPoolId=settings.cognito_user_pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
            MessageAction="SUPPRESS",
        )
        _cognito().admin_set_user_password(
            UserPoolId=settings.cognito_user_pool_id,
            Username=email,
            Password=password,
            Permanent=True,
        )
        sub = next(
            (a["Value"] for a in resp["User"]["Attributes"] if a["Name"] == "sub"),
            None,
        )
        return {"sub": sub, "email": email}
    except _cognito().exceptions.UsernameExistsException:
        raise HTTPException(409, "Email already registered")
    except Exception as e:
        log.exception("register failed")
        raise HTTPException(500, f"Registration failed: {e.__class__.__name__}")


def login(email: str, password: str) -> dict:
    try:
        resp = _cognito().initiate_auth(
            ClientId=settings.cognito_client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
        r = resp["AuthenticationResult"]
        return {
            "id_token":      r["IdToken"],
            "access_token":  r["AccessToken"],
            "refresh_token": r.get("RefreshToken"),
            "expires_in":    r["ExpiresIn"],
            "token_type":    r["TokenType"],
        }
    except (_cognito().exceptions.NotAuthorizedException,
            _cognito().exceptions.UserNotFoundException):
        raise HTTPException(401, "Invalid email or password")
    except Exception as e:
        log.exception("login failed")
        raise HTTPException(500, f"Login failed: {e.__class__.__name__}")
