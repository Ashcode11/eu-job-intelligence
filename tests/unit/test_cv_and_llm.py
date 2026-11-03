import io
import textwrap

import httpx
import pytest

from agents.cv_intelligence.parser import UnsupportedResume, analyse_text, extract_text
from agents.llm.ollama import LLMUnavailable, OllamaClient
from common.config import Settings

CV_TEXT = (
    "Jane Doe. Cloud Architect at Nagarro (2019 - present). Capgemini 2013 - 2019. "
    "12+ years of experience in cloud architecture. AWS Certified Solutions Architect - "
    "Professional. AZ-305. Migrated SQL Server to Amazon RDS with AWS DMS and CDC. "
    "Terraform, Terragrunt, Kubernetes, Helm, Jenkins, Spring Boot microservices."
)


def make_docx(text: str) -> bytes:
    from docx import Document

    doc = Document()
    for part in text.split(". "):
        doc.add_paragraph(part)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pdf(text: str) -> bytes:
    """A minimal valid one-page PDF with a text stream (no extra dependencies)."""
    lines = textwrap.wrap(text, 90)
    ops = (
        "BT /F1 10 Tf 40 800 Td 12 TL "
        + " ".join(
            "(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '"
            for ln in lines
        )
        + " ET"
    )
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


@pytest.mark.parametrize(
    "maker,ctype",
    [
        (make_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (make_pdf, "application/pdf"),
    ],
)
def test_extract_and_analyse(maker, ctype):
    text = extract_text(maker(CV_TEXT), ctype)
    facts = analyse_text(text, 2026)
    names = {s["name"] for s in facts["skills"]}
    assert {"AWS", "AWS DMS", "Amazon RDS", "Terraform", "Kubernetes", "SQL Server"} <= names
    assert "AWS Certified Solutions Architect – Professional" in facts["certifications"]
    assert facts["years_experience"] == 12 and facts["years_experience_from_dates"] == 13


def test_scanned_or_empty_pdf_rejected():
    with pytest.raises(UnsupportedResume):
        extract_text(make_pdf(" "), "application/pdf")


async def test_ollama_availability_and_usage():
    def handler(req: httpx.Request):
        if req.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "llama3.2:3b"}, {"name": "nomic-embed-text:latest"}]}
            )
        if req.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[0.1] * 768]})
        return httpx.Response(
            200, json={"message": {"content": '{"a": 1}'}, "prompt_eval_count": 7, "eval_count": 3}
        )

    async with OllamaClient(
        Settings(_env_file=None), transport=httpx.MockTransport(handler)
    ) as llm:
        assert await llm.available()
        assert len((await llm.embed(["x"]))[0]) == 768
        assert await llm.chat_json("s", "p", {"type": "object"}) == {"a": 1}
        assert (llm.usage.calls, llm.usage.prompt_tokens, llm.usage.completion_tokens) == (1, 7, 3)


async def test_ollama_unreachable_is_reported_not_raised():
    def handler(req: httpx.Request):
        raise httpx.ConnectError("refused")

    async with OllamaClient(
        Settings(_env_file=None), transport=httpx.MockTransport(handler)
    ) as llm:
        assert await llm.available() is False
        with pytest.raises(LLMUnavailable):
            await llm.embed(["x"])


async def test_wrong_embedding_dimension_rejected():
    def handler(req: httpx.Request):
        return httpx.Response(200, json={"embeddings": [[0.1] * 384]})

    async with OllamaClient(
        Settings(_env_file=None), transport=httpx.MockTransport(handler)
    ) as llm:
        with pytest.raises(LLMUnavailable, match="384"):
            await llm.embed(["x"])
