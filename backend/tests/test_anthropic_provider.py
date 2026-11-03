"""AnthropicProvider against a local stub of the Messages API: checks the exact request
we send and how responses map to turns, without a key or network access."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic
import pytest

from apps.assistant.providers import AnthropicProvider, AssistantUnavailable
from apps.assistant.tools import TOOL_DEFS


class Stub:
    def __init__(self):
        self.requests: list[dict] = []
        self.responses: list[tuple[int, dict]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "body": body}
                )
                status, payload = stub.responses.pop(0)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.server.shutdown()


@pytest.fixture
def provider(stub):
    client = anthropic.Anthropic(base_url=stub.url, api_key="test-key", max_retries=0)
    return AnthropicProvider(model="claude-opus-5-5", effort="medium", client=client)


def message(content, stop_reason, **extra):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 30},
        **extra,
    }


def test_request_shape(stub, provider):
    stub.responses.append((200, message([{"type": "text", "text": "Hi"}], "end_turn")))
    provider.run("SYSTEM", [{"role": "user", "content": "hello"}], TOOL_DEFS)
    req = stub.requests[0]
    body = req["body"]
    assert req["path"].startswith("/v1/messages")
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 16000
    assert body["system"] == "SYSTEM" and body["output_config"] == {"effort": "medium"}
    assert body["fallbacks"] == "default" and body["cache_control"] == {"type": "ephemeral"}
    assert "server-side-fallback-2026-07-01" in req["headers"]["anthropic-beta"]
    assert all(t["strict"] for t in body["tools"])
    # Removed or invalid settings for this model must not be sent.
    assert not {"temperature", "top_p", "top_k", "tool_choice", "thinking"} & set(body)


def test_tool_use_turn_is_parsed(stub, provider):
    block = {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "search_units",
        "input": {
            "property_id": None,
            "beds": 2,
            "min_beds": None,
            "max_rent": None,
            "available_by": None,
        },
    }
    stub.responses.append(
        (200, message([{"type": "text", "text": "Checking."}, block], "tool_use"))
    )
    turn = provider.run("S", [{"role": "user", "content": "2 bed?"}], TOOL_DEFS)
    assert turn.stop_reason == "tool_use" and turn.tool_calls[0].name == "search_units"
    assert turn.tool_calls[0].input["beds"] == 2
    assert turn.input_tokens == 120 and turn.output_tokens == 30
    assert turn.content[1].type == "tool_use"  # appended back unchanged


def test_refusal_is_reported(stub, provider):
    stub.responses.append((200, message([], "refusal")))
    turn = provider.run("S", [{"role": "user", "content": "x"}], TOOL_DEFS)
    assert turn.stop_reason == "refusal" and turn.tool_calls == []


@pytest.mark.parametrize("status", [429, 500, 529])
def test_transient_errors_become_assistant_unavailable(stub, provider, status):
    stub.responses.append(
        (status, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    )
    with pytest.raises(AssistantUnavailable):
        provider.run("S", [{"role": "user", "content": "x"}], TOOL_DEFS)


def test_client_errors_propagate(stub, provider):
    stub.responses.append(
        (400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}})
    )
    with pytest.raises(anthropic.BadRequestError):
        provider.run("S", [{"role": "user", "content": "x"}], TOOL_DEFS)
