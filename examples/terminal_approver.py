"""Run a Codex turn and approve or deny each action from the terminal.

    python examples/terminal_approver.py "List the files in this folder"

Requires the Codex CLI (`codex`) and a signed-in account.
"""
import sys
import threading

from sera_core import APPROVAL_TOOL, ApprovalBroker, CodexBridge

done = threading.Event()
prompts = []


def on_event(message):
    if broker.handles(message):
        item = broker.receive(message, chat="terminal")
        if item:
            prompts.append(item)
    elif message.get("method") == "item/agentMessage/delta":
        print(message["params"].get("delta", ""), end="", flush=True)
    elif message.get("method") in ("turn/completed", "bridge/disconnected"):
        done.set()


bridge = CodexBridge(on_event, ".sera-core-logs")
broker = ApprovalBroker(respond=bridge.respond, engine=bridge)
bridge.start()
thread = bridge.call("thread/start", {"cwd": ".", "approvalPolicy": "on-request", "sandbox": "workspace-write",
                                      "dynamicTools": [APPROVAL_TOOL]})["thread"]["id"]
bridge.call("turn/start", {"threadId": thread, "input": [{"type": "text", "text": " ".join(sys.argv[1:]) or "Say hello"}]})

while not done.wait(0.2):
    while prompts:
        view = prompts.pop(0).public()
        print(f"\n\n[approval] {view['action']}\n  reason: {view.get('reason', '')}\n  {view['warning']}")
        answer = input("  allow? [y/N/a=always] ").strip().lower()
        broker.decide(view["id"], answer in ("y", "a"), session=answer == "a" and view["allow_session"])
bridge.close()
