"""Server-managed opaque bearer authentication with hashed token lookup."""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CustomerIdentity:
    customer_id: UUID


async def authenticate_customer(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> CustomerIdentity:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
        if 32 <= len(token) <= 512:
            fingerprint = hashlib.sha256(token.encode()).hexdigest()
            settings: Settings = request.app.state.settings
            for expected, customer_id in settings.auth_token_customers.items():
                if hmac.compare_digest(fingerprint, expected):
                    return CustomerIdentity(customer_id)
    raise AppError("unauthorized", "A valid customer bearer token is required.", 401)


AuthenticatedCustomer = Annotated[CustomerIdentity, Depends(authenticate_customer)]


async def authenticate_administrator(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("unauthorized", "An administrator bearer token is required.", 401)
    token = credentials.credentials
    settings: Settings = request.app.state.settings
    if 32 <= len(token) <= 512:
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        if any(
            hmac.compare_digest(fingerprint, expected)
            for expected in settings.auth_admin_token_hashes
        ):
            return
    raise AppError("forbidden", "Administrator access is required.", 403)


Administrator = Annotated[None, Depends(authenticate_administrator)]
