"""The evaluation scripts run offline and keep their promises about what they write."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench import semantic_eval  # noqa: E402


def test_semantic_cases_are_balanced_and_left_to_meaning():
    labels = [c["label"] for c in semantic_eval.CASES]
    assert labels.count(0) == labels.count(1) == 12
    out = semantic_eval.main(offline=True)
    assert out["rule_decided"] == []          # every case reaches the judge; a rule that decides one is reported
    assert "on" not in out["cases"][0]        # offline never pretends to have asked a model
