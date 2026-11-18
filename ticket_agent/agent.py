import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import load_settings_from_environment
from .decide import Decision, decide_ticket
from .faq import load_faq_text
from .helpdesk import (
    AlreadyHandled,
    FatalHelpdeskError,
    Helpdesk,
    HelpdeskError,
    RejectedRequest,
)
from .llm import ModelAnswerNeeded, create_llm_backend
from .run_log import RunLog
from .state import DONE, REJECTED, StateStore

FAQ_PATH = Path("faq.md")
STATE_PATH = Path("state.json")
LOG_DIRECTORY = Path("logs")


@dataclass
class RunSummary:
    outcomes: dict[str, int] = field(default_factory=dict)

    def count(self, outcome: str) -> None:
        self.outcomes[outcome] = self.outcomes.get(outcome, 0) + 1

    def has_unfinished_tickets(self) -> bool:
        return any(outcome not in ("posted", "already_handled", "dry_run") for outcome in self.outcomes)


def send_decision_to_helpdesk(helpdesk: Helpdesk, decision_as_dict: dict) -> str:
    decision = Decision(**decision_as_dict)
    try:
        helpdesk.submit_decision(decision.ticket_id, decision.action, decision.build_request_body())
    except AlreadyHandled:
        return "already_handled"
    return "posted"


def send_and_record_outcome(helpdesk, state_store, run_log, decision_as_dict, started_at, retries_before) -> str:
    ticket_id = decision_as_dict["ticket_id"]
    try:
        outcome = send_decision_to_helpdesk(helpdesk, decision_as_dict)
        state_store.mark_status(ticket_id, DONE)
    except RejectedRequest as error:
        print(f"{ticket_id}: helpdesk rejected the decision: {error}")
        state_store.mark_status(ticket_id, REJECTED)
        outcome = "rejected"
    except HelpdeskError as error:
        print(f"{ticket_id}: will retry on next run: {error}")
        outcome = "left_pending"
    run_log.append_ticket_line(
        ticket_id, decision_as_dict, outcome, helpdesk.retries_used - retries_before, time.monotonic() - started_at
    )
    return outcome


def resend_pending_decisions_from_previous_run(helpdesk, state_store, run_log, summary: RunSummary) -> None:
    for decision_as_dict in state_store.list_pending_decisions():
        outcome = send_and_record_outcome(
            helpdesk, state_store, run_log, decision_as_dict, time.monotonic(), helpdesk.retries_used
        )
        summary.count(outcome)


def decide_and_send_new_tickets(helpdesk, backend, faq_text, state_store, run_log, summary: RunSummary) -> None:
    for ticket in helpdesk.fetch_open_tickets():
        if state_store.knows_ticket(ticket["id"]):
            continue
        started_at = time.monotonic()
        retries_before = helpdesk.retries_used
        try:
            decision = decide_ticket(ticket, backend, faq_text)
        except ModelAnswerNeeded:
            summary.count("waiting_for_model_answer")
            continue
        state_store.record_decision_before_sending(ticket["id"], decision.to_state_dict())
        outcome = send_and_record_outcome(
            helpdesk, state_store, run_log, decision.to_state_dict(), started_at, retries_before
        )
        summary.count(outcome)


def show_decisions_without_sending(helpdesk, backend, faq_text) -> None:
    for ticket in helpdesk.fetch_open_tickets():
        try:
            decision = decide_ticket(ticket, backend, faq_text)
        except ModelAnswerNeeded:
            print(f"{ticket['id']} waiting for a model answer")
            continue
        print(
            f"{decision.ticket_id} {decision.action:8} {decision.language} {decision.category:16} "
            f"{decision.priority} rule={decision.rule_triggered} verifier={decision.verifier_result}"
        )


def run_agent(helpdesk, backend, faq_text, state_store, run_log) -> RunSummary:
    summary = RunSummary()
    resend_pending_decisions_from_previous_run(helpdesk, state_store, run_log, summary)
    decide_and_send_new_tickets(helpdesk, backend, faq_text, state_store, run_log, summary)
    return summary


def parse_command_line_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Triage every open Roosterly helpdesk ticket.")
    parser.add_argument("--dry-run", action="store_true", help="decide and print, send nothing, write no state")
    parser.add_argument(
        "--reset-practice-first",
        action="store_true",
        help="re-open all practice tickets and forget local state before running (for the final run)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_command_line_arguments()
    settings = load_settings_from_environment()
    helpdesk = Helpdesk(settings)
    backend = create_llm_backend(settings)
    faq_text = load_faq_text(FAQ_PATH)
    state_store = StateStore(STATE_PATH)
    try:
        if arguments.dry_run:
            show_decisions_without_sending(helpdesk, backend, faq_text)
            return 0
        if arguments.reset_practice_first:
            helpdesk.reset_practice_tickets()
            state_store.forget_everything()
        summary = run_agent(helpdesk, backend, faq_text, state_store, RunLog(LOG_DIRECTORY))
    except FatalHelpdeskError as error:
        print(f"Stopping: {error}")
        return 2
    print("Run finished:", summary.outcomes)
    return 1 if summary.has_unfinished_tickets() else 0
