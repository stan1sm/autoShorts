"""Provider-agnostic LLM interface. Providers are imported lazily so the app
runs without every SDK installed."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str


class LLMProvider(ABC):
    name: str

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def complete(self, system: str, prompt: str, max_tokens: int = 4096) -> LLMResponse: ...


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str):
        super().__init__(model)
        try:
            import anthropic
        except ImportError as exc:
            raise LLMError("`pip install anthropic` required for the anthropic provider") from exc
        self._client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env

    def complete(self, system: str, prompt: str, max_tokens: int = 4096) -> LLMResponse:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        return LLMResponse(
            text=text,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            model=self.model,
            provider=self.name,
        )


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str):
        super().__init__(model)
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMError("`pip install openai` required for the openai provider") from exc
        self._client = OpenAI()  # OPENAI_API_KEY from env

    def complete(self, system: str, prompt: str, max_tokens: int = 4096) -> LLMResponse:
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        usage = resp.usage
        return LLMResponse(
            text=resp.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=self.model,
            provider=self.name,
        )


_PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def get_provider(name: str, model: str) -> LLMProvider:
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise LLMError(f"unknown LLM provider '{name}'; available: {sorted(_PROVIDERS)}")
    return cls(model)


def extract_json(text: str) -> Any:
    """Pull a JSON value out of an LLM response, tolerating code fences and prose."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the first bracketed span that parses, whichever opener
    # appears earliest (so an object containing arrays isn't misread as a list).
    openers = sorted(
        p for p in ((text.find(o), o, c) for o, c in (("[", "]"), ("{", "}"))) if p[0] != -1
    )
    for start, opener, closer in openers:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise LLMError(f"no parseable JSON in LLM response: {text[:200]!r}")
