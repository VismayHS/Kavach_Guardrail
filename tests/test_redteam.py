"""B4: every bypass the red team found is replayed; once fixed, it must stay blocked. Plus a fuzz smoke run."""
import json
from pathlib import Path

import pytest

from bench import redteam as rt

FOUND = sorted((Path(__file__).resolve().parents[1] / "bench" / "redteam_found").glob("*.json"))


@pytest.mark.parametrize("path", FOUND, ids=[p.stem for p in FOUND])
def test_found_bypasses_stay_fixed(path):
    f = json.loads(path.read_text())
    r = rt.attempt(f["goal"], f["template"], f["obfuscation"], f["request"], dest=f["dest"], injection=f["injection"],
                   sender=f["sender"])
    if f["status"] == "fixed":
        assert not r["bypass"], f"regressed: {path.name}: {r['steps'][-1]}"


def test_every_evasion_of_one_goal_is_stopped():
    for o in rt.OBFUSCATIONS:
        r = rt.attempt("exfiltrate_notes", "hidden_comment", o, rt.USER_REQUESTS[1])
        assert not r["bypass"], (o, r["steps"][-1])


def test_attacks_run_as_admin_so_roles_never_help():
    r = rt.attempt("pay_attacker", "fake_authority", "base64", rt.USER_REQUESTS[0])
    assert r["outcome"] in ("DENY", "ESCALATE") and "[R8]" not in r["steps"][-1]["reason"]
