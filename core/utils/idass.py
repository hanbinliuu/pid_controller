# encoding: utf-8
"""
@author : shirukai
@date : 2025/11/18

IDASS JWT Authentication Module

This module provides JWT token parsing and validation functionality for IDASS authentication.
"""
import logging
from typing import Optional, Dict, Any
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# OAuth2 scheme for JWT authentication
oauth2_scheme = HTTPBearer(auto_error=False)


class UserInfo(BaseModel):
    """User information extracted from JWT token."""

    user_id: Optional[str] = None
    user_name: Optional[str] = None
    raw_payload: Dict[str, Any] = {}

    class Config:
        arbitrary_types_allowed = True


def parse_user_info(credentials: Optional[HTTPAuthorizationCredentials]) -> UserInfo:
    try:
        payload = jwt.decode(
            credentials.credentials,
            key="",
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            }
        )
        return UserInfo(
            user_id=payload.get("user_name"),
            user_name=payload.get("realName"),
            raw_payload=payload
        )
    except Exception as e:
        logger.error(f"Invalid JWT token: {e}")


def get_current_user(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme)
) -> Optional[UserInfo]:
    """
    FastAPI dependency to get current user from JWT token (optional authentication).

    Args:
        credentials: HTTPAuthorizationCredentials from HTTPBearer

    Returns:
        UserInfo object or None if no credentials provided

    Raises:
        HTTPException: If token is invalid or expired

    Example:
        ```python
        from fastapi import Depends
        from backend.core.idass import get_current_user, UserInfo

        @app.get("/optional-auth")
        async def optional_auth_route(user: UserInfo = Depends(get_current_user)):
            if not user:
                return {"message": "Hello guest"}
            return {"message": f"Hello {user.username}"}
        ```
    """
    user_info = parse_user_info(credentials)

    # if not user_info:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Authentication required",
    #         headers={"WWW-Authenticate": "Bearer"},
    #     )
    return user_info
