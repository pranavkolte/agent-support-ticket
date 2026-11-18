import json
from datetime import datetime, timezone
from pathlib import Path

from .redaction import redact_payment_details


class RunLog:
    def __init__(self, log_directory: Path, started_at: datetime | None = None):
        log_directory.mkdir(parents=True, exist_ok=True)
        started_at = started_at or datetime.now(timezone.utc)
        self.log_path = log_directory / f"run-{started_at.strftime('%Y%m%dT%H%M%SZ')}.jsonl"

    def append_ticket_line(self, ticket_id: str, decision: dict | None, outcome: str, http_retries: int, seconds_taken: float) -> None:
        line = {
            "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ticket_id": ticket_id,
            "outcome": outcome,
            "http_retries": http_retries,
            "seconds_taken": round(seconds_taken, 2),
        }
        if decision:
            line.update(
                {
                    "language": decision["language"],
                    "category": decision["category"],
                    "priority": decision["priority"],
                    "action": decision["action"],
                    "confidence": decision["confidence"],
                    "faq_ids": decision["faq_ids"],
                    "rule_triggered": decision["rule_triggered"],
                    "verifier_result": decision["verifier_result"],
                    "reason": decision["reason"],
                    "input_tokens": decision["input_tokens"],
                    "output_tokens": decision["output_tokens"],
                }
            )
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(redact_payment_details(json.dumps(line, ensure_ascii=False)) + "\n")
