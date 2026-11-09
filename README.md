# sera-core

**A human-in-the-loop safety layer for local Codex agents.**

`sera-core` sits between the [Codex App Server](https://developers.openai.com/codex) and a person. Every time an agent wants to run a command, change files, widen its permissions or confirm an MCP tool action, `sera-core` holds the request until a human decides, from a desktop UI, a terminal or a chat app such as WhatsApp.

It is the open-source core of **Sera**, an AI work assistant built in Indonesia for small businesses that run their operations from a Mac and WhatsApp.

## Why

Agents that can act on a real computer need consent boundaries that are hard to get wrong:

| Rule | How sera-core enforces it |
|---|---|
| Nothing is approved silently | Only a literal `allow=True` approves; anything else declines. |
| "Allow" means once | A one-time approval never creates a grant. |
| "Always allow" is narrow | It covers one chat, one exact action and target, and lives in memory only. It is offered only for simple read-only commands (`ls`, `cat`, `rg`...) or for agent-declared `sensitive`/`external` actions. It is never offered for shell composition, scripts, file changes or irreversible actions. |
| No persistent policy changes | It never writes Codex config or exec-policy amendments. |
| Stale decisions die | Pending requests and grants are dropped when the engine reconnects, because JSON-RPC ids belong to one connection. |
| Secrets stay hidden | API keys, GitHub/Slack tokens, bearer tokens and private keys are redacted before a request is shown to a human or sent to a chat. |
| Forms are not auto-filled | MCP elicitations are accepted only when they are plain confirmations; data-entry and URL/OAuth forms are refused. |
| Chat decisions are bound | `/allow` from WhatsApp is accepted only from an allowlisted number, in the same chat, within 15 minutes, and only when exactly one decision is open. |

## Components

| Path | Purpose |
|---|---|
| `sera_core.CodexBridge` | Stdio JSON-RPC client for `codex app-server`. Per-process config overrides only. |
| `sera_core.ApprovalBroker` | Holds approval requests and turns decisions into protocol replies. |
| `sera_core.APPROVAL_TOOL` | A dynamic tool the agent calls to ask consent before actions Codex does not gate itself (sending a message, submitting a form). |
| `sera_core.ChatApprovals` | `/allow`, `/deny`, `/alwaysallow`, `/resetallow` from a chat app. |
| `js/whatsapp-protocol.mjs` | Dependency-free helpers for an owner-allowlisted WhatsApp bridge: sender checks, direct-chat filtering, safe file names, payload limits. |

## Quick start

```bash
pip install -e ".[dev]"
pytest -q
node --test js/whatsapp-protocol.test.mjs
```

Approve actions from your terminal (requires the Codex CLI and a signed-in account):

```bash
python examples/terminal_approver.py "List the files in this folder"
```

Minimal integration:

```python
from sera_core import ApprovalBroker, CodexBridge

def on_event(message):
    if broker.handles(message):
        item = broker.receive(message, chat="my-chat")
        if item:                      # None means an existing grant answered it
            show_to_user(item.public())  # redacted view

bridge = CodexBridge(on_event, "logs")
broker = ApprovalBroker(respond=bridge.respond, engine=bridge)
bridge.start()

# later, when the user clicks:
broker.decide(request_id, allow=True)               # once
broker.decide(request_id, allow=True, session=True)  # only if item.session_allowed
```

From a chat app:

```python
from sera_core import ChatApprovals

chat = ChatApprovals(broker, allowed_senders={"+62 812-0000-0001"})
send(chat_id, chat.prompt(item, sender, chat_id))
reply = chat.handle(sender, chat_id, incoming_text)   # None if not a decision command
```

## Status

Early stage (0.1.0). The approval rules are extracted from Sera, where they run on macOS with Codex and a WhatsApp bridge. The public API may change before 1.0. Issues and pull requests are welcome.

## Bahasa Indonesia

`sera-core` adalah lapisan persetujuan manusia untuk agen AI lokal berbasis Codex: setiap tindakan di komputer menunggu keputusan Anda (Allow sekali, Deny, atau Always Allow terbatas) dari aplikasi, terminal, atau WhatsApp. Dikembangkan oleh PT Serba Saja Grup, Jakarta.

## License

MIT © 2026 PT Serba Saja Grup. See [LICENSE](LICENSE). Security reports: see [SECURITY.md](SECURITY.md).
