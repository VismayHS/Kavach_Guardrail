"""AgentOS hook adapter: tool-shape mapping (the HTTP path is exercised against a live server by hand)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations"))
from agentos_hook import to_kavach  # noqa: E402


def test_agentos_tool_mapping():
    assert to_kavach("run_sql_query", {"query": "SELECT 1"}) == ("crm.query", {"sql": "SELECT 1"})
    assert to_kavach("run_sql_query", {"query": " delete from customers"})[0] == "crm.execute"
    assert to_kavach("write_file", {"path": "/workspace/notes.txt", "content": "x"}) == \
        ("files.write", {"path": "notes.txt", "content": "x"})
    assert to_kavach("shell", {"command": "cat /workspace/deploy.env"}) == ("files.read", {"path": "deploy.env"})
    assert to_kavach("shell", {"command": "rm -f /workspace/q3.csv"}) == ("files.delete", {"path": "q3.csv"})
    assert to_kavach("shell", {"command": "ls | wc -l"}) == ("shell", {"command": "ls | wc -l"})   # unknown -> fail closed
    assert to_kavach("payments.refund", {"amount": 5}) == ("payments.refund", {"amount": 5})
