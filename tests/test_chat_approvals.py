import pytest

from sera_core import ApprovalBroker, ChatApprovals, normalize_phone
from sera_core.approvals import COMMAND_APPROVAL

OWNER = "+62 812-0000-0001"
OWNER_N = "6281200000001"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def setup(clock=None):
    sent = []
    b = ApprovalBroker(respond=lambda i, result=None, error=None: sent.append((i, result)), engine=object())
    chat = ChatApprovals(b, {OWNER}, clock=clock or Clock())
    return b, chat, sent


def ask(b, chat, i, command="ls", chat_id="chat-1"):
    item = b.receive({"id": i, "method": COMMAND_APPROVAL, "params": {"command": command}}, chat_id)
    return chat.prompt(item, OWNER, chat_id)


def test_normalize_phone():
    assert normalize_phone(OWNER) == OWNER_N
    with pytest.raises(ValueError):
        normalize_phone("0812000001")


def test_allow_once_from_owner():
    b, chat, sent = setup()
    msg = ask(b, chat, 1)
    assert "APPROVAL NEEDED" in msg and "/alwaysallow" in msg
    assert chat.handle(OWNER_N, "chat-1", "/allow") == "Allowed once."
    assert sent == [(1, {"decision": "accept"})]


def test_stranger_cannot_decide():
    b, chat, sent = setup()
    ask(b, chat, 1)
    assert "not allowlisted" in chat.handle("6289999999999", "chat-1", "/allow")
    assert sent == []


def test_wrong_chat_cannot_decide():
    b, chat, sent = setup()
    ask(b, chat, 1)
    assert chat.handle(OWNER_N, "chat-2", "/allow") == "No open approval in this chat."


def test_ambiguous_bare_command_is_refused():
    b, chat, sent = setup()
    ask(b, chat, 1)
    second = ask(b, chat, 2)
    assert "Several approvals" in chat.handle(OWNER_N, "chat-1", "/deny")
    code = second.rsplit("Code: ", 1)[1]
    assert chat.handle(OWNER_N, "chat-1", f"/deny {code}") == "Denied."
    assert sent == [(2, {"decision": "decline"})]


def test_expiry():
    clock = Clock()
    b, chat, sent = setup(clock)
    ask(b, chat, 1)
    clock.t += 15 * 60 + 1
    assert chat.handle(OWNER_N, "chat-1", "/allow") == "No open approval in this chat."


def test_always_allow_refused_for_risky_command():
    b, chat, sent = setup()
    msg = ask(b, chat, 1, "rm -rf build")
    assert "not available" in msg
    assert "not available" in chat.handle(OWNER_N, "chat-1", "/alwaysallow")
    assert sent == []


def test_always_allow_then_reset():
    b, chat, sent = setup()
    ask(b, chat, 1)
    assert chat.handle(OWNER_N, "chat-1", "/alwaysallow").startswith("Always allowed")
    assert b.receive({"id": 2, "method": COMMAND_APPROVAL, "params": {"command": "ls"}}, "chat-1") is None
    assert chat.handle(OWNER_N, "chat-1", "/resetallow") == "Session grants revoked (1)."


def test_engine_reconnect_invalidates_codes():
    b, chat, sent = setup()
    ask(b, chat, 1)
    b.reset(engine=object())
    assert chat.handle(OWNER_N, "chat-1", "/allow") == "No open approval in this chat."


def test_non_commands_are_ignored():
    _, chat, _ = setup()
    assert chat.handle(OWNER_N, "chat-1", "hello") is None
