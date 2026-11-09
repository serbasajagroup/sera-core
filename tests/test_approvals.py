import json

import pytest

from sera_core import (APPROVAL_TOOL_NAME, ApprovalBroker, ApprovalError, mcp_confirmation_supported,
                       redact, session_eligible)
from sera_core.approvals import COMMAND_APPROVAL, DYNAMIC_TOOL_CALL, FILE_APPROVAL, MCP_ELICITATION


class Recorder:
    def __init__(self):
        self.sent = []

    def __call__(self, identifier, result=None, error=None):
        self.sent.append((identifier, result, error))


def broker():
    rec = Recorder()
    return ApprovalBroker(respond=rec, engine=object()), rec


def cmd(i, command):
    return {"id": i, "method": COMMAND_APPROVAL, "params": {"command": command, "cwd": "/w"}}


@pytest.mark.parametrize("command,ok", [
    ("ls -la", True), ("cat README.md", True), ("pwd", True),
    ("rm -rf /", False), ("ls; rm -rf /", False), ("cat $(whoami)", False),
    ("ls | sh", False), ("cat a > b", False), ("python3 x.py", False), ("ls \\\nrm", False),
])
def test_session_only_for_simple_read_only_commands(command, ok):
    assert session_eligible(COMMAND_APPROVAL, {"command": command}) is ok


def test_file_changes_never_get_session_grants():
    assert not session_eligible(FILE_APPROVAL, {"grantRoot": "/"})


def test_allow_once_does_not_persist():
    b, rec = broker()
    b.receive(cmd(1, "ls"), "chat-a")
    assert b.decide(1, True) == {"decision": "accept"}
    assert b.receive(cmd(2, "ls"), "chat-a") is not None  # asked again
    assert rec.sent == [(1, {"decision": "accept"}, None)]


def test_only_literal_true_allows():
    b, _ = broker()
    b.receive(cmd(1, "ls"), "c")
    assert b.decide(1, "yes") == {"decision": "decline"}


def test_session_grant_is_scoped_to_chat_and_action():
    b, rec = broker()
    b.receive(cmd(1, "ls"), "chat-a")
    b.decide(1, True, session=True)
    assert b.receive(cmd(2, "ls"), "chat-a") is None  # auto-accepted
    assert rec.sent[-1] == (2, {"decision": "accept"}, None)
    assert b.receive(cmd(3, "ls"), "chat-b") is not None  # other chat
    assert b.receive(cmd(4, "ls -la"), "chat-a") is not None  # other action


def test_session_refused_for_dangerous_command():
    b, rec = broker()
    b.receive(cmd(1, "rm -rf build"), "c")
    with pytest.raises(ApprovalError):
        b.decide(1, True, session=True)
    assert rec.sent == [] and "1" in b.pending


def test_reset_drops_grants_and_stale_decisions():
    b, _ = broker()
    old = b.engine
    b.receive(cmd(1, "ls"), "c")
    b.decide(1, True, session=True)
    b.receive(cmd(2, "cat x"), "c")
    b.reset(engine=object())
    assert not b.grants and not b.pending
    b.receive(cmd(3, "ls"), "c")
    with pytest.raises(ApprovalError):
        b.decide(3, True, expected_engine=old)


def test_revoke_chat():
    b, _ = broker()
    b.receive(cmd(1, "ls"), "a")
    b.decide(1, True, session=True)
    assert b.revoke_chat("a") == 1
    assert b.receive(cmd(2, "ls"), "a") is not None


def test_dynamic_approval_tool():
    b, rec = broker()
    msg = {"id": 9, "method": DYNAMIC_TOOL_CALL, "params": {"tool": APPROVAL_TOOL_NAME, "arguments": {
        "action": "Send invoice", "target": "client@example.com", "reason": "asked", "risk": "external"}}}
    assert b.handles(msg)
    item = b.receive(msg, "c")
    assert item.public()["target"] == "client@example.com"
    result = b.decide(9, False)
    assert json.loads(result["contentItems"][0]["text"])["allowed"] is False


def test_irreversible_tool_call_has_no_session_option():
    b, _ = broker()
    msg = {"id": 1, "method": DYNAMIC_TOOL_CALL, "params": {"tool": APPROVAL_TOOL_NAME,
           "arguments": {"action": "Delete", "target": "db", "reason": "r", "risk": "irreversible"}}}
    assert b.receive(msg, "c").session_allowed is False


def test_mcp_forms():
    plain = {"mode": "form", "requestedSchema": {"type": "object", "properties": {}}}
    data = {"mode": "form", "requestedSchema": {"type": "object", "properties": {"password": {"type": "string"}}}}
    assert mcp_confirmation_supported(plain)
    assert not mcp_confirmation_supported(data)
    assert not mcp_confirmation_supported({"mode": "url", "url": "https://x"})
    b, rec = broker()
    b.receive({"id": 5, "method": MCP_ELICITATION, "params": data}, "c")
    with pytest.raises(ApprovalError):
        b.decide(5, True)
    assert b.decide(5, False) == {"action": "decline", "content": None}


def test_redaction():
    text = "use sk-abcdefghijklmnop and Bearer xyz and ghp_" + "a" * 36
    out = redact({"command": text, "list": [text]})
    assert "sk-abc" not in json.dumps(out) and "ghp_" not in json.dumps(out) and "xyz" not in json.dumps(out)


def test_public_view_is_redacted_but_reply_uses_original():
    b, rec = broker()
    item = b.receive(cmd(1, "cat sk-abcdefghijklmnop"), "c")
    assert "sk-" not in item.public()["action"]
    assert item.params["command"].startswith("cat sk-")


def test_deny_chat_and_resolved():
    b, rec = broker()
    b.receive(cmd(1, "ls"), "a")
    b.receive(cmd(2, "ls"), "b")
    assert b.deny_chat("a") == 1
    b.resolved(2)
    assert not b.pending
