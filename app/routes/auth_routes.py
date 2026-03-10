"""
app/routes/auth_routes.py
--------------------------
Authentication endpoints for the CV Parser API.
Provides an endpoint to exchange the master Admin Token for a short-lived
JWT access token.
"""

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from typing import Optional

from app.config.settings import settings
from app.security.token_validator import create_access_token

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Authentication"],
)

class AdminTokenRequest(BaseModel):
    admin_token: str = Field(description="The master admin token required to generate a JWT.")

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int



admin_token_scheme = APIKeyHeader(
    name="X-Admin-Token", 
    description="Master Admin Token",
    auto_error=False
)

@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Generate a JWT Access Token",
    description="Exchange your master Admin Token for a short-lived JWT access token.",
    responses={
        200: {"description": "JWT successfully generated."},
        401: {"description": "Invalid Admin Token."},
    }
)
async def generate_token(
    request_body: Optional[AdminTokenRequest] = None,
    x_admin_token: Optional[str] = Depends(admin_token_scheme),
) -> TokenResponse:
    """
    Generate a JWT access token given a valid Admin Token.
    Accepts the token either via the request body (JSON) or via the globally authorized X-Admin-Token header.
    """
    token = ""
    # Header takes precedence if set via global Swagger UI auth
    if x_admin_token:
        token = x_admin_token
    elif request_body and request_body.admin_token:
        token = request_body.admin_token

    if token != settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Admin Token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Valid admin token, issue JWT
    jwt_token = create_access_token(data={"sub": "admin"})
    
    return TokenResponse(
        access_token=jwt_token,
        expires_in=settings.JWT_EXPIRE_MINUTES * 60
    )
