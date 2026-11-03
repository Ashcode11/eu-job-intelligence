"""Minimal async Ollama client: embeddings and schema-constrained JSON chat.

Every agent works without the LLM. `LLMUnavailable` is raised when Ollama can't be reached
so callers can fall back to their deterministic path instead of failing.
"""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from common.config import Settings, get_settings
from common.logging import get_logger

log = get_logger(__name__)


class LLMUnavailable(Exception):
    """Ollama is not reachable or the model is not pulled."""


@dataclass
class LLMUsage:
    """Token accounting, copied into agent_executions."""

    model: str | None = None
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hits: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "LLMUsage") -> None:
        self.model = self.model or other.model
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cache_hits += other.cache_hits
        self.errors += other.errors


class OllamaClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.settings = settings or get_settings()
        self.chat_model = self.settings.llm_chat_model
        self.embedding_model = self.settings.llm_embedding_model
        self.usage = LLMUsage(model=self.chat_model)
        self._client = httpx.AsyncClient(
            base_url=self.settings.ollama_base_url, timeout=timeout, transport=transport
        )
        self._available: bool | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def available(self) -> bool:
        """True if Ollama answers and both configured models are pulled. Cached per client."""
        if self._available is None:
            try:
                resp = await self._client.get("/api/tags", timeout=5)
                names = {m["name"] for m in resp.json().get("models", [])}
                names |= {n.split(":")[0] for n in names}  # "nomic-embed-text:latest"
                self._available = (
                    self.chat_model in names or self.chat_model.split(":")[0] in names
                ) and (self.embedding_model in names)
                if not self._available:
                    log.warning(
                        "llm_models_missing",
                        have=sorted(names),
                        need=[self.chat_model, self.embedding_model],
                    )
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("llm_unreachable", url=self.settings.ollama_base_url, error=str(exc))
                self._available = False
        return self._available

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = await self._client.post(
                "/api/embed",
                json={"model": self.embedding_model, "input": [t[:8000] for t in texts]},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"embedding failed: {exc}") from exc
        vectors = resp.json()["embeddings"]
        dim = self.settings.embedding_dimensions
        if vectors and len(vectors[0]) != dim:
            raise LLMUnavailable(
                f"{self.embedding_model} returned {len(vectors[0])} dims, expected {dim}"
            )
        return vectors

    async def chat_json(
        self, system: str, prompt: str, schema: dict[str, Any], *, max_tokens: int = 800
    ) -> dict[str, Any]:
        """Ask for a JSON object that matches `schema` (Ollama structured outputs)."""
        try:
            resp = await self._client.post(
                "/api/chat",
                json={
                    "model": self.chat_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "format": schema,
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": max_tokens},
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            self.usage.errors.append(str(exc)[:200])
            raise LLMUnavailable(f"chat failed: {exc}") from exc
        body = resp.json()
        self.usage.calls += 1
        self.usage.prompt_tokens += int(body.get("prompt_eval_count") or 0)
        self.usage.completion_tokens += int(body.get("eval_count") or 0)
        content = body.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            self.usage.errors.append("invalid JSON from model")
            raise LLMUnavailable("model returned invalid JSON") from exc

    async def chat_text(self, system: str, prompt: str, *, max_tokens: int = 900) -> str:
        try:
            resp = await self._client.post(
                "/api/chat",
                json={
                    "model": self.chat_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": max_tokens},
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            self.usage.errors.append(str(exc)[:200])
            raise LLMUnavailable(f"chat failed: {exc}") from exc
        body = resp.json()
        self.usage.calls += 1
        self.usage.prompt_tokens += int(body.get("prompt_eval_count") or 0)
        self.usage.completion_tokens += int(body.get("eval_count") or 0)
        return body.get("message", {}).get("content", "").strip()
