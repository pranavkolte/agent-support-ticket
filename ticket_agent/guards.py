import re

ALWAYS_HUMAN_TOPIC_PATTERNS = {
    "refund": [
        r"terugbetal", r"geld terug", r"terugstort", r"restitutie", r"\brefund",
        r"terugboeking", r"\bstorneren", r"chargeback", r"betwist",
        r"onterecht(e)? (afgeschreven|afschrijving|incasso|gefactureerd)",
        r"dubbel (afgeschreven|betaald|gefactureerd)",
    ],
    "cancellation": [
        r"\bopzeg", r"stopzetten", r"beëindig\w* (ons |onze |mijn |het )?(abonnement|contract|account)",
        r"(abonnement|contract|account|licentie|subscription)\W+(\w+\W+){0,3}(annuler|cancel|stopzet|beëindig)",
        r"(annuler|cancel)\w*\W+(\w+\W+){0,4}(abonnement|contract|account|subscription)",
    ],
    "contract": [r"contractwijziging", r"contract (wijzig|aanpass|opzeg)", r"change (our|my) contract"],
    "gdpr": [
        r"\bavg\b", r"\bgdpr\b", r"inzageverzoek", r"verzoek tot inzage",
        r"recht op vergetelheid", r"gegevens (laten )?verwijderen",
        r"verwijder\w* (al )?(mijn|onze|alle) (persoons)?gegevens",
        r"delete (all )?(my|our) data",
    ],
    "security": [
        r"gehackt", r"\bhack", r"datalek", r"inbraak", r"phishing", r"onbevoegd",
        r"ongeautoriseerd", r"security (incident|breach)", r"data ?breach",
        r"niet (van )?mij(n)? (account|login)", r"onbekende (login|inlog)",
    ],
    "legal": [
        r"advocaat", r"rechtszaak", r"juridische stappen", r"dagvaard", r"aansprakelijk",
        r"aanklagen", r"\blawyer", r"legal action", r"\bsue\b", r"kantonrechter",
    ],
    "churn_threat": [
        r"overstappen", r"over te stappen", r"\bconcurrent", r"switch(ing)? to",
        r"stoppen met roosterly", r"stappen (wij )?over", r"zeggen (we|wij) (het |ons |onze )?(abonnement |contract )?op\b",
    ],
}

INJECTION_PATTERNS = [
    r"ignore (all |the |any )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"ignore (your|the) (instructions|rules|guidelines)",
    r"system prompt",
    r"negeer (alle |de |je |jouw )?(vorige|eerdere|bovenstaande)?\s?(instructies|regels|opdracht)",
    r"vergeet (alle |je |jouw )?(instructies|regels)",
    r"\byou are now\b",
    r"\b(je|jij) bent nu\b",
    r"nieuwe instructies?",
    r"new instructions?",
    r"reveal (your|the) (prompt|instructions)",
    r"</?\s*ticket\s*>",
]


def is_ticket_empty(ticket: dict) -> bool:
    subject = (ticket.get("subject") or "").strip()
    body = (ticket.get("body") or "").strip()
    return not subject and not body


def build_ticket_text(ticket: dict) -> str:
    return f"{ticket.get('subject') or ''}\n{ticket.get('body') or ''}"


def find_always_human_topic_in_text(text: str) -> str | None:
    lowered = text.lower()
    for topic, patterns in ALWAYS_HUMAN_TOPIC_PATTERNS.items():
        if any(re.search(pattern, lowered) for pattern in patterns):
            return topic
    return None


def contains_prompt_injection_attempt(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in INJECTION_PATTERNS)
