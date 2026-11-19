from langdetect import DetectorFactory, LangDetectException, detect_langs

DetectorFactory.seed = 0

SUPPORTED_LANGUAGE_CODES = ("nl", "en", "de")
LANGUAGE_DETECTOR_CERTAINTY = 0.9


def detect_language_with_certainty(text: str) -> str | None:
    try:
        best_guess = detect_langs(text)[0]
    except LangDetectException:
        return None
    if best_guess.prob >= LANGUAGE_DETECTOR_CERTAINTY and best_guess.lang in SUPPORTED_LANGUAGE_CODES:
        return best_guess.lang
    return None
