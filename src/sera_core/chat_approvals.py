"""Approve or deny agent actions from a chat app (for example WhatsApp).

A decision typed in a chat is only accepted when it comes from an
allowlisted sender, in the same chat where the request was shown, before the
request expires, and while the same engine connection is alive.  Bare
commands (``/allow``) are only accepted when exactly one decision is open in
that chat, so a reply can never land on the wrong request.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass, field

from .approvals import ApprovalBroker, ApprovalError, PendingRequest

DECISIONS = {"/allow": (True, False), "/deny": (False, False),
             "/alwaysallow": (True, True), "/always_allow": (True, True)}
DEFAULT_TTL = 15 * 60


def normalize_phone(value: str) -> str:
    """Return digits in international format (``+62 812-...`` -> ``62812...``)."""
    value = re.sub(r"[\s()+-]", "", str(value))
    if not re.fullmatch(r"[1-9][0-9]{5,14}", value):
        raise ValueError("Use an international number with country code and no leading 0.")
    return value


@dataclass
class _Code:
    request: str
    sender: str
    chat: str
    engine: object
    expires: float


@dataclass
class ChatApprovals:
    broker: ApprovalBroker
    allowed_senders: set
    ttl: float = DEFAULT_TTL
    clock: callable = time.time
    codes: dict = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self):
        self.allowed_senders = {normalize_phone(p) for p in self.allowed_senders}
        if not 1 <= len(self.allowed_senders) <= 8:
            raise ValueError("Allow between 1 and 8 sender numbers.")

    def _prune(self) -> None:
        now = self.clock()
        self.codes = {k: c for k, c in self.codes.items()
                      if c.expires >= now and c.engine is self.broker.engine and c.request in self.broker.pending}

    def prompt(self, item: PendingRequest, sender: str, chat: str) -> str:
        """Create a decision code for ``item`` and return the message to send."""
        sender = normalize_phone(sender)
        if sender not in self.allowed_senders:
            raise ApprovalError("Sender is not allowlisted.")
        with self.lock:
            self._prune()
            code = secrets.token_hex(3).upper()
            self.codes[code] = _Code(str(item.id), sender, chat, self.broker.engine, self.clock() + self.ttl)
        view = item.public()
        lines = ["APPROVAL NEEDED", str(view.get("action") or "Action on this computer")[:1500]]
        if view.get("target"):
            lines.append("Target: " + str(view["target"])[:500])
        lines += ["Reason: " + str(view.get("reason") or "This action needs your consent.")[:1200],
                  "Warning: " + view["warning"],
                  "/allow - allow once", "/deny - deny"]
        lines.append("/alwaysallow - same action in this chat" if view["allow_session"]
                     else "Always allow is not available for this action.")
        lines.append(f"Valid for {int(self.ttl // 60)} minutes. Code: {code}")
        return "\n".join(lines)

    def handle(self, sender: str, chat: str, text: str) -> str | None:
        """Process a chat message. Returns a reply, or ``None`` if it is not a decision."""
        parts = text.strip().split()
        if not parts:
            return None
        command = parts[0].lower()
        if command == "/resetallow":
            removed = self.broker.revoke_chat(chat)
            return f"Session grants revoked ({removed})."
        if command not in DECISIONS:
            return None
        try:
            sender = normalize_phone(sender)
        except ValueError:
            return "Decision ignored: sender is not allowlisted."
        if sender not in self.allowed_senders:
            return "Decision ignored: sender is not allowlisted."
        if len(parts) > 2:
            return "Send only the command, optionally followed by its code."
        allow, session = DECISIONS[command]
        with self.lock:
            self._prune()
            if len(parts) == 2:
                token = parts[1].upper()
            else:
                mine = [k for k, c in self.codes.items() if c.sender == sender and c.chat == chat]
                if not mine:
                    return "No open approval in this chat."
                if len(mine) > 1:
                    return "Several approvals are open. Reply with the command and its code."
                token = mine[0]
            code = self.codes.get(token)
            if not code or code.sender != sender or code.chat != chat:
                return "This approval is not valid for this chat or has expired."
            try:
                self.broker.decide(code.request, allow, session, expected_engine=code.engine)
            except ApprovalError as exc:
                return str(exc)
            self.codes.pop(token, None)
        if not allow:
            return "Denied."
        return "Always allowed for this action in this chat." if session else "Allowed once."
