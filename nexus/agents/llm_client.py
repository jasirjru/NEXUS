"""Provider-agnostic LLM client.

Providers:
- echo: deterministic offline "LLM" that composes answers ONLY from supplied
  evidence (used in tests/CI and when no API key is configured). It never
  invents content - it structures what it is given.
- openai / anthropic / ollama: real providers via HTTP, all behind the same
  interface with identical grounding rules baked into the system prompt.

Grounding contract (enforced downstream): the investigator validates that
claims in reports reference evidence ids; ungrounded claims are flagged as
LLM_HYPOTHESIS, never as observed fact.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from nexus.config import settings
from nexus.core.errors import NexusError
from nexus.core.logging_setup import get_logger

log = get_logger("nexus.agents.llm")

SYSTEM_PROMPT = """You are NEXUS Investigator, an AI analyst embedded in a blockchain
intelligence platform. You receive structured evidence collected by deterministic tools
(transaction history, feature values, anomaly scores, graph neighborhoods).

STRICT RULES:
1. You NEVER invent blockchain facts. Every factual claim must cite an evidence id like [E3].
2. Distinguish clearly: OBSERVED FACTS (cited evidence), ML INFERENCE (scores/probabilities),
   your HYPOTHESIS (interpretation), and UNKNOWN (missing information).
3. If evidence is insufficient, say exactly what is unknown and which tool would resolve it.
4. Be concise, technical, and non-speculative.
"""


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str | None = None
    usage: dict = field(default_factory=dict)


class BaseLLMClient(ABC):
    name = "base"

    @abstractmethod
    def complete(self, system: str, user: str) -> LLMResponse: ...


class EchoClient(BaseLLMClient):
    """Deterministic evidence-only responder. Structures the provided evidence
    without adding any claim that is not traceable to it."""

    name = "echo"

    def complete(self, system: str, user: str) -> LLMResponse:
        # The user payload contains an "EVIDENCE" section with [E#] items and a
        # "QUESTION" section. We compose a grounded briefing from them.
        evidence_lines = [
            ln.strip() for ln in user.splitlines() if ln.strip().startswith("[E")
        ]
        question = ""
        for ln in user.splitlines():
            if ln.startswith("QUESTION:"):
                question = ln[len("QUESTION:"):].strip()
                break

        facts = [ln for ln in evidence_lines if "observed_fact" in ln]
        inference = [ln for ln in evidence_lines if "ml_inference" in ln]

        lines = [
            f"Investigation summary (deterministic, evidence-grounded):",
            "",
            "OBSERVED FACTS:",
        ]
        lines += [f"  {ln}" for ln in facts[:12]] or ["  (none supplied)"]
        lines.append("")
        lines.append("ML INFERENCE:")
        lines += [f"  {ln}" for ln in inference[:8]] or ["  (none supplied)"]
        lines.append("")
        lines.append("LLM HYPOTHESIS:")
        if facts or inference:
            lines.append(
                "  The evidence above is consistent with the question raised "
                f"('{question}'); interpretation is limited to these items and "
                "no further claims are made."
            )
        else:
            lines.append("  No evidence available; no hypothesis can be formed.")
        lines.append("")
        lines.append("UNKNOWN:")
        lines.append(
            "  Any behavior not covered by the supplied evidence items "
            "(e.g., off-chain intent, attribution) remains unknown."
        )
        return LLMResponse(text="\n".join(lines), provider=self.name)


class OpenAIClient(BaseLLMClient):
    name = "openai"

    def __init__(self) -> None:
        import os

        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise NexusError("OPENAI_API_KEY not set")
        self.model = settings.llm_model or "gpt-4o-mini"
        self.base = "https://api.openai.com/v1"

    def complete(self, system: str, user: str) -> LLMResponse:
        with httpx.Client(timeout=90) as client:
            resp = client.post(
                f"{self.base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            provider=self.name,
            model=self.model,
            usage=data.get("usage", {}),
        )


class AnthropicClient(BaseLLMClient):
    name = "anthropic"

    def __init__(self) -> None:
        import os

        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise NexusError("ANTHROPIC_API_KEY not set")
        self.model = settings.llm_model or "claude-sonnet-4-20250514"
        self.base = "https://api.anthropic.com/v1"

    def complete(self, system: str, user: str) -> LLMResponse:
        with httpx.Client(timeout=90) as client:
            resp = client.post(
                f"{self.base}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model,
                    "max_tokens": 1500,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return LLMResponse(
            text=data["content"][0]["text"],
            provider=self.name,
            model=self.model,
            usage=data.get("usage", {}),
        )


class OllamaClient(BaseLLMClient):
    name = "ollama"

    def __init__(self) -> None:
        self.base = settings.llm_model and None or "http://localhost:11434"
        self.model = settings.llm_model or "llama3.1"

    def complete(self, system: str, user: str) -> LLMResponse:
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{self.base}/api/generate",
                json={
                    "model": self.model,
                    "prompt": user,
                    "system": system,
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return LLMResponse(text=data["response"], provider=self.name, model=self.model)


def get_llm_client(name: str | None = None) -> BaseLLMClient:
    name = (name or settings.llm_provider).lower()
    try:
        if name == "openai":
            return OpenAIClient()
        if name == "anthropic":
            return AnthropicClient()
        if name == "ollama":
            return OllamaClient()
    except NexusError as e:
        log.warning("LLM provider %s unavailable (%s); falling back to echo", name, e)
    return EchoClient()
