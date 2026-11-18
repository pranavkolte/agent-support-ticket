import json

import httpx
import pytest

from ticket_agent.llm import GroqBackend, LlmUnavailable


def build_backend(handler):
    waits = []
    backend = GroqBackend("key", "some-model", http_client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=waits.append)
    backend.recorded_waits = waits
    return backend


def tool_call_response(arguments: dict) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"tool_calls": [{"function": {"name": "submit_answer", "arguments": json.dumps(arguments)}}]}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    })


def ask(backend):
    return backend.ask_for_structured_answer("classify", "system", "user", {"type": "object", "properties": {}})


def test_structured_answer_and_token_usage_are_read_from_the_tool_call():
    response = ask(build_backend(lambda request: tool_call_response({"language": "nl"})))
    assert response.data == {"language": "nl"} and response.input_tokens == 100 and response.output_tokens == 20


def test_rate_limit_is_waited_out_and_retried():
    responses = iter([httpx.Response(429, headers={"retry-after": "3"}), tool_call_response({"ok": True})])
    backend = build_backend(lambda request: next(responses))
    assert ask(backend).data == {"ok": True}
    assert backend.recorded_waits == [3.0]


def test_failed_tool_generation_is_retried_once_then_succeeds():
    responses = iter([httpx.Response(400, json={"error": {"code": "tool_use_failed"}}), tool_call_response({"ok": True})])
    assert ask(build_backend(lambda request: next(responses))).data == {"ok": True}


def test_auth_error_is_not_retried_and_becomes_llm_unavailable():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(LlmUnavailable):
        ask(build_backend(handler))
    assert len(calls) == 1


def test_response_without_tool_call_becomes_llm_unavailable():
    with pytest.raises(LlmUnavailable):
        ask(build_backend(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})))
