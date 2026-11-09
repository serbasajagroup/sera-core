"""Runs CodexBridge against a tiny fake App Server speaking the same stdio JSON-RPC."""
import sys
import textwrap
import threading

import pytest

from sera_core import ApprovalBroker, BridgeError, CodexBridge

FAKE_SERVER = textwrap.dedent('''
    import json, sys
    def out(m): sys.stdout.write(json.dumps(m) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        m = json.loads(line)
        if m.get("method") == "initialize":
            out({"id": m["id"], "result": {"userAgent": "fake"}})
        elif m.get("method") == "run":
            out({"id": 100, "method": "item/commandExecution/requestApproval", "params": {"command": "rm -rf build"}})
        elif m.get("method") == "fail":
            out({"id": m["id"], "error": {"message": "boom"}})
        elif m.get("id") == 100 and "result" in m:
            out({"method": "done", "params": m["result"]})
''')


@pytest.fixture
def server(tmp_path):
    path = tmp_path / "fake_server.py"
    path.write_text(FAKE_SERVER)
    return [sys.executable, str(path)]


def test_roundtrip_with_approval(server, tmp_path):
    events, done = [], threading.Event()
    holder = {}

    def on_event(message):
        events.append(message)
        if holder["broker"].handles(message):
            holder["broker"].receive(message, "chat")
        if message.get("method") == "done":
            done.set()

    bridge = CodexBridge(on_event, tmp_path / "logs", command=server)
    holder["broker"] = ApprovalBroker(respond=bridge.respond, engine=bridge)
    try:
        assert bridge.start() == {"userAgent": "fake"}
        bridge.send({"method": "run", "params": {}})
        for _ in range(100):
            if holder["broker"].pending:
                break
            done.wait(0.05)
        holder["broker"].decide(100, False)
        assert done.wait(5)
        assert events[-1]["params"] == {"decision": "decline"}
        with pytest.raises(BridgeError, match="boom"):
            bridge.call("fail")
    finally:
        bridge.close()


def test_disconnect_is_reported(tmp_path):
    seen = threading.Event()
    bridge = CodexBridge(lambda m: m.get("method") == "bridge/disconnected" and seen.set(), tmp_path,
                         command=[sys.executable, "-c", "import sys; sys.stdin.readline()"])
    with pytest.raises(BridgeError):
        bridge.start()
    assert seen.wait(5)
    bridge.close()
