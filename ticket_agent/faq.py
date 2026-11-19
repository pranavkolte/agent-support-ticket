import re
from pathlib import Path

FAQ_ENTRY_HEADING_PATTERN = re.compile(r"^## (F\d+) · .*$", re.MULTILINE)
FAQ_RULES_HEADING = "## The client's rules for the support team"


def load_faq_text(faq_path: Path) -> str:
    return faq_path.read_text(encoding="utf-8")


def split_faq_into_entries(faq_text: str) -> dict[str, str]:
    help_centre_text = faq_text.split(FAQ_RULES_HEADING)[0]
    headings = list(FAQ_ENTRY_HEADING_PATTERN.finditer(help_centre_text))
    entries = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(help_centre_text)
        entries[heading.group(1)] = help_centre_text[heading.start():end].strip().rstrip("-").strip()
    return entries
