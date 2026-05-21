"""Input validation and service auth for AccuVerify agent routes."""

from __future__ import annotations

import os
import re
from typing import Annotated

from fastapi import Header, HTTPException, status

_USER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{4,128}$")
_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
_MAX_REASON_LEN = 500

VERIFY_SERVICE_API_KEY = os.getenv("VERIFY_SERVICE_API_KEY", "").strip()
REQUIRE_VERIFY_SERVICE_KEY = os.getenv("REQUIRE_VERIFY_SERVICE_KEY", "false").lower() in {
    "1",
    "true",
    "yes",
}


def sanitize_user_id(user_id: str) -> str:
    uid = (user_id or "").strip()
    if not _USER_ID_RE.match(uid):
        raise HTTPException(status_code=400, detail="Invalid user_id format.")
    return uid


def sanitize_agent_id(agent_id: str) -> str:
    aid = (agent_id or "").strip()
    if not _AGENT_ID_RE.match(aid):
        raise HTTPException(status_code=400, detail="Invalid agent_id format.")
    return aid


def sanitize_reject_reason(reason: str) -> str:
    text = (reason or "").strip()
    if len(text) > _MAX_REASON_LEN:
        raise HTTPException(status_code=400, detail="Reason exceeds maximum length.")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        raise HTTPException(status_code=400, detail="Reason contains invalid characters.")
    return text


async def verify_service_key(
    x_verify_service_key: Annotated[str | None, Header(alias="X-Verify-Service-Key")] = None,
) -> None:
    if not REQUIRE_VERIFY_SERVICE_KEY:
        return
    if not VERIFY_SERVICE_API_KEY or x_verify_service_key != VERIFY_SERVICE_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized.")
