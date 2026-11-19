import re

REDACTION_MARKER = "[REDACTED]"

IBAN_CANDIDATE_PATTERN = re.compile(
    r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b",
    re.IGNORECASE,
)
CARD_SECURITY_CODE_PATTERN = re.compile(r"\b(cvc2?|cvv2?)\W{0,3}\d{3,4}\b", re.IGNORECASE)
CARD_NUMBER_CANDIDATE_PATTERN = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")


def iban_has_valid_checksum(candidate: str) -> bool:
    compact = re.sub(r"\s+", "", candidate).upper()
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    digits_only = "".join(str(int(character, 36)) for character in rearranged)
    return int(digits_only) % 97 == 1


def card_number_has_valid_luhn_checksum(candidate: str) -> bool:
    digits = [int(character) for character in re.sub(r"\D", "", candidate)]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for position, digit in enumerate(reversed(digits)):
        if position % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def redact_payment_details(text: str) -> str:
    without_ibans = IBAN_CANDIDATE_PATTERN.sub(
        lambda match: REDACTION_MARKER
        if iban_has_valid_checksum(match.group())
        else match.group(),
        text,
    )
    without_card_numbers = CARD_NUMBER_CANDIDATE_PATTERN.sub(
        lambda match: REDACTION_MARKER
        if card_number_has_valid_luhn_checksum(match.group())
        else match.group(),
        without_ibans,
    )
    return CARD_SECURITY_CODE_PATTERN.sub(REDACTION_MARKER, without_card_numbers)


def contains_payment_details(text: str) -> bool:
    return redact_payment_details(text) != text
