import json
import os
from pathlib import Path

PENDING = "pending"
DONE = "done"
REJECTED = "rejected"


class StateStore:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.entries: dict[str, dict] = {}
        if state_path.exists():
            self.entries = json.loads(state_path.read_text(encoding="utf-8"))

    def save_atomically(self) -> None:
        temporary_path = self.state_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_path, self.state_path)

    def has_unfinished_entry(self, ticket_id: str) -> bool:
        return ticket_id in self.entries and self.entries[ticket_id]["status"] != DONE

    def is_done(self, ticket_id: str) -> bool:
        return self.entries.get(ticket_id, {}).get("status") == DONE

    def record_decision_before_sending(self, ticket_id: str, decision_as_dict: dict) -> None:
        self.entries[ticket_id] = {"status": PENDING, "decision": decision_as_dict}
        self.save_atomically()

    def mark_status(self, ticket_id: str, status: str) -> None:
        self.entries[ticket_id]["status"] = status
        self.save_atomically()

    def list_pending_decisions(self) -> list[dict]:
        return [entry["decision"] for entry in self.entries.values() if entry["status"] == PENDING]

    def forget_everything(self) -> None:
        self.entries = {}
        self.save_atomically()
