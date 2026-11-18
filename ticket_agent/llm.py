import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

ANSWER_TOOL_NAME = "submit_answer"
MAX_ANSWER_TOKENS = 1500


@dataclass
class LlmResponse:
    data: dict
    input_tokens: int
    output_tokens: int


class LlmUnavailable(Exception):
    pass


class ModelAnswerNeeded(Exception):
    pass


class AnthropicBackend:
    def __init__(self, api_key: str, model: str):
        import anthropic

        self.anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3)
        self.model = model

    def ask_for_structured_answer(
        self, purpose: str, system_prompt: str, user_message: str, output_schema: dict
    ) -> LlmResponse:
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_ANSWER_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                tools=[
                    {
                        "name": ANSWER_TOOL_NAME,
                        "description": "Submit the structured answer.",
                        "input_schema": output_schema,
                    }
                ],
                tool_choice={"type": "tool", "name": ANSWER_TOOL_NAME},
            )
        except self.anthropic.APIError as error:
            raise LlmUnavailable(str(error)) from error
        answer_block = next((block for block in message.content if block.type == "tool_use"), None)
        if answer_block is None:
            raise LlmUnavailable("Model returned no structured answer")
        return LlmResponse(answer_block.input, message.usage.input_tokens, message.usage.output_tokens)


GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MAX_ATTEMPTS = 4
GROQ_DEFAULT_WAIT_SECONDS = 2.0
GROQ_TIMEOUT_SECONDS = 60.0


class GroqBackend:
    def __init__(self, api_key: str, model: str, http_client: httpx.Client | None = None, sleep=time.sleep):
        self.model = model
        self.sleep = sleep
        self.http_client = http_client or httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=GROQ_TIMEOUT_SECONDS
        )

    def build_request_body(self, system_prompt: str, user_message: str, output_schema: dict) -> dict:
        return {
            "model": self.model,
            "max_tokens": MAX_ANSWER_TOKENS,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": ANSWER_TOOL_NAME,
                        "description": "Submit the structured answer.",
                        "parameters": output_schema,
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": ANSWER_TOOL_NAME}},
        }

    def response_is_worth_retrying(self, response: httpx.Response) -> bool:
        return response.status_code in (429, 500, 502, 503) or (
            response.status_code == 400 and "tool_use_failed" in response.text
        )

    def read_wait_seconds(self, response: httpx.Response) -> float:
        try:
            return max(float(response.headers.get("retry-after", GROQ_DEFAULT_WAIT_SECONDS)), 0.0)
        except ValueError:
            return GROQ_DEFAULT_WAIT_SECONDS

    def send_request_with_retries(self, body: dict) -> httpx.Response:
        for attempt in range(1, GROQ_MAX_ATTEMPTS + 1):
            try:
                response = self.http_client.post(GROQ_CHAT_COMPLETIONS_URL, json=body)
            except httpx.TransportError as error:
                if attempt == GROQ_MAX_ATTEMPTS:
                    raise LlmUnavailable(str(error)) from error
                self.sleep(GROQ_DEFAULT_WAIT_SECONDS)
                continue
            if response.status_code < 400:
                return response
            if attempt == GROQ_MAX_ATTEMPTS or not self.response_is_worth_retrying(response):
                raise LlmUnavailable(f"Groq returned {response.status_code}: {response.text[:300]}")
            self.sleep(self.read_wait_seconds(response))
        raise LlmUnavailable("Groq retries exhausted")

    def ask_for_structured_answer(
        self, purpose: str, system_prompt: str, user_message: str, output_schema: dict
    ) -> LlmResponse:
        response = self.send_request_with_retries(self.build_request_body(system_prompt, user_message, output_schema))
        payload = response.json()
        try:
            tool_call = payload["choices"][0]["message"]["tool_calls"][0]
            answer = json.loads(tool_call["function"]["arguments"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise LlmUnavailable(f"Groq returned no usable structured answer: {error}") from error
        usage = payload.get("usage", {})
        return LlmResponse(answer, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))


class FileExchangeBackend:
    def __init__(self, exchange_directory: Path):
        self.exchange_directory = exchange_directory
        self.exchange_directory.mkdir(parents=True, exist_ok=True)

    def build_exchange_key(self, purpose: str, system_prompt: str, user_message: str) -> str:
        digest = hashlib.sha256(f"{purpose}\n{system_prompt}\n{user_message}".encode()).hexdigest()
        return f"{purpose}-{digest[:12]}"

    def ask_for_structured_answer(
        self, purpose: str, system_prompt: str, user_message: str, output_schema: dict
    ) -> LlmResponse:
        key = self.build_exchange_key(purpose, system_prompt, user_message)
        answer_path = self.exchange_directory / f"{key}.answer.json"
        if answer_path.exists():
            return LlmResponse(json.loads(answer_path.read_text(encoding="utf-8")), 0, 0)
        request_path = self.exchange_directory / f"{key}.request.json"
        request_path.write_text(
            json.dumps(
                {"purpose": purpose, "system_prompt": system_prompt, "user_message": user_message, "output_schema": output_schema},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise ModelAnswerNeeded(key)


def create_llm_backend(settings, exchange_directory: Path = Path("eval/pending")):
    if settings.llm_backend == "anthropic":
        if not settings.anthropic_api_key:
            raise SystemExit("LLM_BACKEND=anthropic needs ANTHROPIC_API_KEY. See .env.example.")
        return AnthropicBackend(settings.anthropic_api_key, settings.model)
    if settings.llm_backend == "groq":
        if not settings.groq_api_key:
            raise SystemExit("LLM_BACKEND=groq needs GROQ_API_KEY. See .env.example.")
        return GroqBackend(settings.groq_api_key, settings.model)
    if settings.llm_backend == "file_exchange":
        return FileExchangeBackend(exchange_directory)
    raise SystemExit(f"Unknown LLM_BACKEND {settings.llm_backend!r}. Use anthropic, groq or file_exchange.")
