"""LLM providers behind one interface, so tests and CI run without an API key."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from django.conf import settings


class AssistantUnavailable(Exception):
    """The model could not be reached; the caller hands off instead of failing the chat."""


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMTurn:
    text: str
    tool_calls: list[ToolCall]
    # Assistant content to append to the transcript unchanged (keeps thinking blocks).
    content: list[Any]
    stop_reason: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    extra: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    def run(self, system: str, messages: list[dict], tools: list[dict]) -> LLMTurn: ...


class AnthropicProvider:
    """Claude via the Messages API with client-side tools."""

    name = "anthropic"
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, model: str | None = None, effort: str | None = None, client=None):
        import anthropic

        self._anthropic = anthropic
        self.model = model or settings.LLM_MODEL
        self.effort = effort or settings.LLM_EFFORT
        self.client = client or anthropic.Anthropic(max_retries=2, timeout=60.0)

    def run(self, system: str, messages: list[dict], tools: list[dict]) -> LLMTurn:
        anthropic = self._anthropic
        try:
            # Stable prefix (tools + system) is cached; per-turn context lives in messages.
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                tools=tools,
                messages=messages,
                cache_control={"type": "ephemeral"},
                output_config={"effort": self.effort},
                betas=[self.FALLBACK_BETA],
                fallbacks="default",
            )
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            raise AssistantUnavailable(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise AssistantUnavailable(str(exc)) from exc
            raise

        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, input=dict(b.input))
            for b in response.content
            if b.type == "tool_use"
        ]
        return LLMTurn(
            text=text,
            tool_calls=calls if response.stop_reason == "tool_use" else [],
            content=response.content,
            stop_reason=response.stop_reason,
            model=response.model,
            input_tokens=response.usage.input_tokens or 0,
            output_tokens=response.usage.output_tokens or 0,
        )


def get_provider(name: str | None = None) -> LLMProvider:
    name = name or settings.LLM_PROVIDER
    if name == "anthropic":
        return AnthropicProvider()
    if name == "mock":
        from .mock_provider import MockProvider

        return MockProvider()
    raise ValueError(f"unknown LLM provider {name!r}")
