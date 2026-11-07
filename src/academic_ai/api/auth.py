from fastapi import APIRouter

from academic_ai.api.schemas import LoginRequest, RegisterRequest, TokenResponse
from academic_ai.auth import cognito_client

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
async def register(req: RegisterRequest):
    result = cognito_client.register(req.email, req.password)
    return {"user_id": result["sub"], "email": result["email"]}


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    return TokenResponse(**cognito_client.login(req.email, req.password))
