"""API-key authentication, rate limiting and upload validation."""

import hashlib
import hmac
import io
import re
import time
import zipfile
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, UploadFile, status
from fastapi.security import APIKeyHeader

from backend.deps import RedisDep, SettingsDep
from common.logging import get_logger

log = get_logger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def key_fingerprint(key: str) -> str:
    return "key:" + hashlib.sha256(key.encode()).hexdigest()[:12]


async def require_api_key(
    request: Request,
    settings: SettingsDep,
    api_key: Annotated[str | None, Depends(_api_key_header)],
) -> str:
    """Return a non-secret actor id for the caller, or reject with 401."""
    if api_key:
        for configured in settings.api_keys:
            if hmac.compare_digest(api_key.encode(), configured.get_secret_value().encode()):
                actor = key_fingerprint(api_key)
                request.state.actor = actor
                return actor
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Missing or invalid API key",
        headers={"WWW-Authenticate": "APIKey"},
    )


ActorDep = Annotated[str, Depends(require_api_key)]

_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour|day)\s*$")
_PERIODS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_rate(spec: str) -> tuple[int, int]:
    m = _RATE_RE.match(spec)
    if not m:
        raise ValueError(f"Invalid rate limit {spec!r}; expected e.g. '120/minute'")
    return int(m.group(1)), _PERIODS[m.group(2)]


async def rate_limit(actor: ActorDep, redis: RedisDep, settings: SettingsDep) -> None:
    """Fixed-window limiter in Redis. Fails open if Redis is down, so the API stays usable."""
    limit, period = parse_rate(settings.rate_limit_default)
    window = int(time.time() // period)
    key = f"ratelimit:{actor}:{window}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            count, _ = await pipe.incr(key).expire(key, period + 1).execute()
    except Exception as exc:  # pragma: no cover - exercised only when Redis is down
        log.warning("rate_limit_unavailable", error=str(exc))
        return
    if count > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Rate limit exceeded",
            headers={"Retry-After": str(period - int(time.time()) % period)},
        )


@dataclass(frozen=True)
class ValidatedUpload:
    content: bytes
    content_type: str
    extension: str
    sha256: str


PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def read_validated_resume(file: UploadFile, max_bytes: int) -> ValidatedUpload:
    """Accept only real PDF/DOCX files (checked by content, not by extension) under max_bytes."""
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"File exceeds {max_bytes // (1024 * 1024)} MB",
        )
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")

    if content.startswith(b"%PDF-"):
        kind = (PDF_MIME, "pdf")
    elif content.startswith(b"PK\x03\x04") and _is_docx(content):
        kind = (DOCX_MIME, "docx")
    else:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF and DOCX resumes are accepted"
        )
    return ValidatedUpload(
        content=content,
        content_type=kind[0],
        extension=kind[1],
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _is_docx(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return False
    return "word/document.xml" in names and "[Content_Types].xml" in names
