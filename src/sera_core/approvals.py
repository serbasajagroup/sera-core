"""Human-approval broker for the Codex App Server.

The Codex App Server sends JSON-RPC *server requests* whenever an agent wants
to run a command, change files, widen its permissions, ask the user a
question, or confirm an MCP tool action.  This module decides how those
requests are held, shown and answered so that:

* nothing is approved silently;
* an "Allow" covers exactly one request;
* an "Always allow" grant is scoped to one chat, one exact action and target,
  and only exists in memory (it never edits Codex config or exec policy);
* grants and pending requests are discarded when the engine reconnects,
  because JSON-RPC ids belong to a single connection;
* secrets are redacted before a request is shown to a human or sent to a
  messaging channel.
"""
from __future__ import annotations

import copy
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

COMMAND_APPROVAL = "item/commandExecution/requestApproval"
FILE_APPROVAL = "item/fileChange/requestApproval"
PERMISSIONS_APPROVAL = "item/permissions/requestApproval"
USER_INPUT = ("item/tool/requestUserInput", "tool/requestUserInput")
MCP_ELICITATION = "mcpServer/elicitation/request"
DYNAMIC_TOOL_CALL = "item/tool/call"

#: Name of the dynamic tool an agent calls to ask for consent before a
#: sensitive action that Codex itself would not gate (sending a message,
#: submitting a form, spending money...).
APPROVAL_TOOL_NAME = "request_approval"

APPROVAL_TOOL = {
    "type": "function",
    "name": APPROVAL_TOOL_NAME,
    "description": (
        "Ask the human for explicit consent before a sensitive or external action "
        "that was not clearly authorised. Describe the action, the exact target and "
        "the risk, then wait for allowed=true. A decision covers only the described "
        "action. Never ask for or store credentials."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "What will be done."},
            "target": {"type": "string", "description": "Exact recipient, file, URL or account."},
            "reason": {"type": "string", "description": "Why it is needed."},
            "risk": {"type": "string", "enum": ["low", "sensitive", "external", "irreversible"]},
        },
        "required": ["action", "target", "reason", "risk"],
        "additionalProperties": False,
    },
}

_SESSION_RISKS = {"sensitive", "external"}
_SHELL_META = re.compile(r"[;&|`$<>\n\\]")
_READ_ONLY = re.compile(
    r"(?:/(?:usr/)?bin/)?(?:pwd|ls|cat|head|tail|rg|wc)(?: [\w ./_:@+,-]+)?"
)
_SECRET = re.compile(
    r"(?i)(sk-[a-z0-9_-]{8,}|gh[pousr]_[a-z0-9]{20,}|xox[abpr]-[a-z0-9-]{10,}"
    r"|bearer\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
REDACTED = "[redacted]"


class ApprovalError(ValueError):
    """Raised when a decision cannot be applied safely."""


def redact(value: Any) -> Any:
    """Recursively mask API keys, tokens and private keys."""
    if isinstance(value, str):
        return _SECRET.sub(REDACTED, value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def mcp_confirmation_supported(params: dict) -> bool:
    """Only plain confirmation forms (empty object schema) can be accepted.

    URL/OAuth flows and data-entry forms need their own UI; accepting them with
    an empty payload would silently send wrong data.
    """
    schema = params.get("requestedSchema")
    allowed = {"type", "properties", "required", "additionalProperties", "$schema", "title", "description"}
    return (
        params.get("mode") == "form"
        and isinstance(schema, dict)
        and schema.get("type") == "object"
        and schema.get("properties") == {}
        and schema.get("required", []) in ([], None)
        and set(schema) <= allowed
    )


def session_eligible(method: str, params: dict) -> bool:
    """Whether an "Always allow" grant may be offered for this request."""
    if method == DYNAMIC_TOOL_CALL:
        args = params.get("arguments") or {}
        return isinstance(args, dict) and args.get("risk") in _SESSION_RISKS
    if method != COMMAND_APPROVAL:
        return False
    command = str(params.get("command", "")).strip()
    # Shell composition and scripts can change meaning while the text stays
    # identical, so only simple read-only commands qualify.
    if _SHELL_META.search(command):
        return False
    return bool(_READ_ONLY.fullmatch(command))


def signature(chat: str, method: str, params: dict, request_id: Any) -> tuple:
    """Fingerprint of an action. Ids change per call, so they are excluded."""
    if method == DYNAMIC_TOOL_CALL:
        action: Any = params.get("arguments") or {}
    else:
        action = {k: params[k] for k in ("command", "cwd", "grantRoot", "permissions", "additionalPermissions") if k in params}
        if not action:
            action = {"request_id": request_id}
    return (chat, method, json.dumps(action, sort_keys=True, default=str))


@dataclass
class PendingRequest:
    id: Any
    method: str
    params: dict
    chat: str
    engine: Any = None
    session_allowed: bool = False

    def public(self) -> dict:
        """A redacted, display-safe copy for a UI or chat channel."""
        params = redact(copy.deepcopy(self.params))
        view = {"id": self.id, "method": self.method, "chat": self.chat, "params": params,
                "allow_session": self.session_allowed}
        if self.method == DYNAMIC_TOOL_CALL:
            args = params.get("arguments") or {}
            view.update(action=str(args.get("action", ""))[:600], target=str(args.get("target", ""))[:500],
                        reason=str(args.get("reason", ""))[:1000], risk=args.get("risk"))
        elif self.method == MCP_ELICITATION:
            meta = params.get("_meta") or {}
            view.update(reason=params.get("message", "Review this tool action."),
                        action=json.dumps({"server": params.get("serverName"),
                                           "parameters": meta.get("tool_params", {}) if isinstance(meta, dict) else {}},
                                          ensure_ascii=False, indent=2),
                        confirmation_supported=mcp_confirmation_supported(self.params))
        else:
            view.update(action=params.get("command") or params.get("grantRoot") or "", reason=params.get("reason", ""))
        view["warning"] = ("Allow covers only this action and target." if not self.session_allowed else
                           "Always allow covers the same action and target in this chat until the app closes.")
        return view


@dataclass
class ApprovalBroker:
    """Holds pending approval requests and turns human decisions into replies.

    ``respond(request_id, result=None, error=None)`` is called to answer the
    engine (for example :meth:`sera_core.CodexBridge.respond`).
    """

    respond: Callable[..., None]
    engine: Any = None
    pending: dict = field(default_factory=dict)
    grants: set = field(default_factory=set)
    lock: threading.RLock = field(default_factory=threading.RLock)

    APPROVAL_METHODS = (COMMAND_APPROVAL, FILE_APPROVAL, PERMISSIONS_APPROVAL, MCP_ELICITATION, *USER_INPUT)

    def handles(self, message: dict) -> bool:
        method = message.get("method")
        if "id" not in message:
            return False
        if method == DYNAMIC_TOOL_CALL:
            return (message.get("params") or {}).get("tool") == APPROVAL_TOOL_NAME
        return method in self.APPROVAL_METHODS

    def receive(self, message: dict, chat: str) -> PendingRequest | None:
        """Register a server request. Returns it if a human must decide,
        or ``None`` if an existing session grant answered it automatically."""
        method, params = message["method"], dict(message.get("params") or {})
        with self.lock:
            sig = signature(chat, method, params, message["id"])
            if sig in self.grants:
                self._reply(message["id"], method, params, allow=True)
                return None
            item = PendingRequest(message["id"], method, params, chat, self.engine,
                                  session_eligible(method, params))
            self.pending[str(message["id"])] = item
            return item

    def decide(self, request_id: Any, allow: bool, session: bool = False,
               answers: dict | None = None, expected_engine: Any = None) -> dict:
        """Apply a human decision. ``allow`` must be exactly ``True`` to approve."""
        with self.lock:
            if expected_engine is not None and expected_engine is not self.engine:
                raise ApprovalError("The engine reconnected; old decisions are no longer valid.")
            item = self.pending.get(str(request_id))
            if not item:
                raise ApprovalError("This request is finished or expired.")
            allow = allow is True
            if session and allow and not item.session_allowed:
                raise ApprovalError("Always allow is not available for this action. Use allow once or deny.")
            if item.method == MCP_ELICITATION and allow and not mcp_confirmation_supported(item.params):
                raise ApprovalError("This MCP form is not supported. Nothing was sent; deny to cancel.")
            result = self._reply(item.id, item.method, item.params, allow, answers)
            if allow and session:
                self.grants.add(signature(item.chat, item.method, item.params, item.id))
            self.pending.pop(str(request_id), None)
            return result

    def _reply(self, request_id, method, params, allow, answers=None) -> dict:
        if method == DYNAMIC_TOOL_CALL:
            text = json.dumps({"allowed": allow, "scope": "only the described action; no new authorization"})
            result = {"success": True, "contentItems": [{"type": "inputText", "text": text}]}
        elif method in (COMMAND_APPROVAL, FILE_APPROVAL):
            # Never install persistent exec-policy amendments.
            result = {"decision": "accept" if allow else "decline"}
        elif method == PERMISSIONS_APPROVAL:
            result = {"permissions": params.get("permissions", {}) if allow else {}, "scope": "turn"}
        elif method in USER_INPUT:
            answers = answers or {}
            result = {"answers": {q["id"]: {"answers": [str(answers.get(q["id"], ""))[:4000]]}
                                  for q in params.get("questions", [])}}
        elif method == MCP_ELICITATION:
            # No persist metadata: this approves only the current call.
            result = {"action": "accept", "content": {}} if allow else {"action": "decline", "content": None}
        else:
            self.respond(request_id, error={"code": -32601, "message": "Unsupported request."})
            return {}
        self.respond(request_id, result=result)
        return result

    def resolved(self, request_id: Any) -> None:
        """Call on ``serverRequest/resolved`` notifications."""
        with self.lock:
            self.pending.pop(str(request_id), None)

    def revoke_chat(self, chat: str) -> int:
        """Remove every session grant for one chat. Returns how many were removed."""
        with self.lock:
            before = len(self.grants)
            self.grants = {g for g in self.grants if g[0] != chat}
            return before - len(self.grants)

    def deny_chat(self, chat: str) -> int:
        """Deny every pending request of a chat (for example on /stop)."""
        with self.lock:
            ids = [k for k, v in self.pending.items() if v.chat == chat]
        for request_id in ids:
            self.decide(request_id, False)
        return len(ids)

    def reset(self, engine: Any = None) -> None:
        """Call when the engine reconnects: ids and grants belong to one connection."""
        with self.lock:
            self.pending.clear()
            self.grants.clear()
            self.engine = engine
