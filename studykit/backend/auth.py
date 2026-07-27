
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from config import settings

security = HTTPBearer()

_jwks_cache: dict | None = None

async def get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json")
        res.raise_for_status()
        _jwks_cache = res.json()
        return _jwks_cache

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    try:
        jwks = await get_jwks()
        # find the matching key by kid in token header
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        key = next(
            (k for k in jwks["keys"] if k.get("kid") == kid),
            jwks["keys"][0],  # fallback to first key if no kid match
        )
        payload = jwt.decode(
            token,
            key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )