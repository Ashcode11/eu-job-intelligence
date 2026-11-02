import io
import zipfile

import pytest
from fastapi import HTTPException, UploadFile

from backend.security import DOCX_MIME, PDF_MIME, key_fingerprint, parse_rate, read_validated_resume


def _upload(content: bytes, name: str = "cv.pdf") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name)


def _docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def test_parse_rate():
    assert parse_rate("120/minute") == (120, 60)
    assert parse_rate(" 5 / second ") == (5, 1)
    with pytest.raises(ValueError):
        parse_rate("lots")


def test_fingerprint_is_stable_and_not_the_key():
    fp = key_fingerprint("super-secret")
    assert fp == key_fingerprint("super-secret")
    assert "super-secret" not in fp


async def test_accepts_pdf_by_magic_bytes():
    up = await read_validated_resume(_upload(b"%PDF-1.7 rest"), 1024)
    assert up.content_type == PDF_MIME and up.extension == "pdf"


async def test_accepts_docx():
    up = await read_validated_resume(_upload(_docx_bytes(), "cv.docx"), 1024 * 1024)
    assert up.content_type == DOCX_MIME


async def test_rejects_renamed_executable():
    with pytest.raises(HTTPException) as e:
        await read_validated_resume(_upload(b"MZ\x90\x00binary", "cv.pdf"), 1024)
    assert e.value.status_code == 415


async def test_rejects_plain_zip_pretending_to_be_docx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("payload.txt", "x")
    with pytest.raises(HTTPException) as e:
        await read_validated_resume(_upload(buf.getvalue(), "cv.docx"), 1024 * 1024)
    assert e.value.status_code == 415


async def test_rejects_oversize():
    with pytest.raises(HTTPException) as e:
        await read_validated_resume(_upload(b"%PDF-" + b"0" * 2000), 1024)
    assert e.value.status_code == 413


async def test_rejects_empty():
    with pytest.raises(HTTPException) as e:
        await read_validated_resume(_upload(b""), 1024)
    assert e.value.status_code == 400
