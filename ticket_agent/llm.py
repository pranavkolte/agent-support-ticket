import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

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
    if settings.llm_backend == "file_exchange":
        return FileExchangeBackend(exchange_directory)
    raise SystemExit(f"Unknown LLM_BACKEND {settings.llm_backend!r}. Use anthropic or file_exchange.")
