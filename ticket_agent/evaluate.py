import argparse
import json
from pathlib import Path

from .config import load_settings_from_environment
from .decide import decide_ticket
from .faq import load_faq_text
from .helpdesk import EXAMPLE_LIST_KEYS, Helpdesk, extract_list_from_payload
from .llm import ModelAnswerNeeded, create_llm_backend

FAQ_PATH = Path("faq.md")
RESULTS_DIRECTORY = Path("eval")
LABEL_FIELDS = ["language", "category", "priority", "action"]


def load_labelled_examples(examples_file: Path | None, helpdesk: Helpdesk | None) -> list[dict]:
    if examples_file:
        return extract_list_from_payload(json.loads(examples_file.read_text(encoding="utf-8")), EXAMPLE_LIST_KEYS)
    return helpdesk.fetch_labelled_examples()


def compare_decision_with_label(decision, label: dict) -> dict:
    return {field: getattr(decision, field) == label.get(field) for field in LABEL_FIELDS}


def evaluate_examples(examples: list[dict], backend, faq_text: str) -> tuple[dict, int]:
    rows = []
    waiting_for_model_answer = 0
    for example in examples:
        try:
            decision = decide_ticket(example, backend, faq_text)
        except ModelAnswerNeeded:
            waiting_for_model_answer += 1
            continue
        label = example["label"]
        rows.append(
            {
                "id": example["id"],
                "expected": {field: label.get(field) for field in LABEL_FIELDS},
                "got": {field: getattr(decision, field) for field in LABEL_FIELDS},
                "matches": compare_decision_with_label(decision, label),
                "label_reason": label.get("reason"),
                "rule_triggered": decision.rule_triggered,
                "verifier_result": decision.verifier_result,
                "draft_reply": decision.draft_reply,
                "english_translation": decision.english_translation,
                "input_tokens": decision.input_tokens,
                "output_tokens": decision.output_tokens,
            }
        )
    return summarise_rows(rows), waiting_for_model_answer


def summarise_rows(rows: list[dict]) -> dict:
    total = len(rows)
    accuracy = {
        field: sum(row["matches"][field] for row in rows) / total if total else None for field in LABEL_FIELDS
    }
    unsafe_replies = [row["id"] for row in rows if row["got"]["action"] == "reply" and row["expected"]["action"] != "reply"]
    needless_escalations = [
        row["id"] for row in rows if row["got"]["action"] != "reply" and row["expected"]["action"] == "reply"
    ]
    return {
        "examples_evaluated": total,
        "accuracy": accuracy,
        "unsafe_replies": unsafe_replies,
        "needless_escalations": needless_escalations,
        "average_input_tokens": sum(row["input_tokens"] for row in rows) / total if total else None,
        "average_output_tokens": sum(row["output_tokens"] for row in rows) / total if total else None,
        "rows": rows,
    }


def print_summary(summary: dict) -> None:
    print(f"examples evaluated: {summary['examples_evaluated']}")
    for field, value in summary["accuracy"].items():
        print(f"  {field:9} accuracy: {value:.0%}" if value is not None else f"  {field}: n/a")
    print(f"unsafe replies (replied where a human was needed): {summary['unsafe_replies']}")
    print(f"needless escalations (human where a reply was right): {summary['needless_escalations']}")
    for row in summary["rows"]:
        wrong_fields = [field for field in LABEL_FIELDS if not row["matches"][field]]
        if wrong_fields:
            print(f"  MISS {row['id']}: " + ", ".join(
                f"{field} expected {row['expected'][field]} got {row['got'][field]}" for field in wrong_fields
            ) + f" | rule={row['rule_triggered']} | label reason: {row['label_reason']}")


def parse_command_line_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the agent on the labelled examples.")
    parser.add_argument("--name", required=True, help="name of this run, for example baseline or after_fix")
    parser.add_argument("--examples-file", type=Path, help="read labelled examples from a file instead of the helpdesk")
    return parser.parse_args()


def main() -> int:
    arguments = parse_command_line_arguments()
    settings = load_settings_from_environment(require_helpdesk_access=arguments.examples_file is None)
    helpdesk = None if arguments.examples_file else Helpdesk(settings)
    examples = load_labelled_examples(arguments.examples_file, helpdesk)
    summary, waiting_for_model_answer = evaluate_examples(
        examples, create_llm_backend(settings), load_faq_text(FAQ_PATH)
    )
    if waiting_for_model_answer:
        print(f"{waiting_for_model_answer} examples are waiting for a model answer in eval/pending")
        return 3
    RESULTS_DIRECTORY.mkdir(exist_ok=True)
    (RESULTS_DIRECTORY / f"results-{arguments.name}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
