"""PII detection with Microsoft Presidio plus Indian recognisers (E8).

KAVACH's own provenance traces PII *values* it saw in tool outputs labelled personal (a CRM row's email, phone).
Presidio adds detection in free text: personal data inside a web page or document (so the task counts as having
read private data), and personal data in an outgoing message that KAVACH never saw come in (the agent typed an
Aadhaar number from memory, or pasted a name and phone from a PDF) so rule R2 still counts it.

Indian identifiers: PAN, Aadhaar (Verhoeff check digit), UPI id, voter id (EPIC), passport, GSTIN, and +91 phone
numbers in the common spacings. Needs `pip install presidio-analyzer` and a spaCy model
(`python -m spacy download en_core_web_sm`); KAVACH_PII_MODEL picks another model.
"""
from __future__ import annotations

import os

# Entity types that identify a person (counted for R2). Locations, dates and URLs alone are not.
PERSONAL = {"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "US_SSN", "UK_NHS",
            "IN_PAN", "IN_AADHAAR", "IN_UPI", "IN_VOTER", "IN_PASSPORT", "IN_PHONE"}
STRUCTURED = PERSONAL - {"PERSON"}      # values with a canonical form that provenance can trace


def _recognizers():
    from presidio_analyzer import Pattern, PatternRecognizer

    from .provenance import _aadhaar_ok, _digits

    class AadhaarRecognizer(PatternRecognizer):
        def validate_result(self, pattern_text: str) -> bool:
            return _aadhaar_ok(_digits(pattern_text))

    return [
        PatternRecognizer(supported_entity="IN_PAN", patterns=[Pattern("pan", r"\b[A-Z]{5}\d{4}[A-Z]\b", 0.8)],
                          context=["pan", "permanent account"]),
        AadhaarRecognizer(supported_entity="IN_AADHAAR",
                          patterns=[Pattern("aadhaar", r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b", 0.6)],
                          context=["aadhaar", "uid", "uidai"]),
        PatternRecognizer(supported_entity="IN_UPI",
                          patterns=[Pattern("upi", r"\b[\w.-]{2,}@(?:ok)?[a-z]{2,}bank\b|\b[\w.-]{2,}@(?:ybl|ibl|axl|"
                                                   r"paytm|upi|apl|oksbi|okicici|okaxis|okhdfcbank)\b", 0.7)]),
        PatternRecognizer(supported_entity="IN_VOTER", patterns=[Pattern("epic", r"\b[A-Z]{3}\d{7}\b", 0.5)],
                          context=["voter", "epic", "election"]),
        PatternRecognizer(supported_entity="IN_PASSPORT",
                          patterns=[Pattern("passport", r"\b[A-PR-WY][1-9]\d\s?\d{4}[1-9]\b", 0.5)],
                          context=["passport"]),
        PatternRecognizer(supported_entity="IN_GSTIN",
                          patterns=[Pattern("gstin", r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", 0.8)]),
        PatternRecognizer(supported_entity="IN_PHONE",
                          patterns=[Pattern("in-phone", r"(?:\+91[\s-]?|\b0)?[6-9]\d{4}[\s-]?\d{5}\b", 0.6)],
                          context=["phone", "mobile", "call", "whatsapp", "contact"]),
    ]


class PIIDetector:
    def __init__(self, model: str | None = None, threshold: float = 0.5):
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        name = model or os.environ.get("KAVACH_PII_MODEL", "en_core_web_sm")
        nlp = NlpEngineProvider(nlp_configuration={"nlp_engine_name": "spacy",
                                                   "models": [{"lang_code": "en", "model_name": name}]}).create_engine()
        self.engine = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
        for r in _recognizers():
            self.engine.registry.add_recognizer(r)
        self.threshold = threshold

    def find(self, text: str) -> list[dict]:
        """Personal data in `text`: [{'type', 'value', 'score'}], overlapping hits merged to the strongest."""
        text = str(text or "")[:20000]
        hits = [r for r in self.engine.analyze(text=text, language="en") if r.score >= self.threshold
                and r.entity_type in PERSONAL]
        hits.sort(key=lambda r: (-r.score, r.start))
        taken: list[tuple[int, int]] = []
        out = []
        for r in hits:
            if any(r.start < e and s < r.end for s, e in taken):
                continue
            taken.append((r.start, r.end))
            out.append({"type": r.entity_type, "value": text[r.start:r.end], "score": round(r.score, 2)})
        return out

    def count(self, text: str) -> int:
        return len(self.find(text))


def available() -> bool:
    try:
        import presidio_analyzer  # noqa: F401
        import spacy
        return bool(spacy.util.is_package(os.environ.get("KAVACH_PII_MODEL", "en_core_web_sm")))
    except Exception:
        return False
