"""sera-core: human-in-the-loop safety layer for local Codex agents."""
from .approvals import (APPROVAL_TOOL, APPROVAL_TOOL_NAME, ApprovalBroker, ApprovalError,
                        PendingRequest, mcp_confirmation_supported, redact, session_eligible)
from .chat_approvals import ChatApprovals, normalize_phone
from .codex_bridge import BridgeError, CodexBridge, find_codex

__version__ = "0.1.0"
__all__ = ["APPROVAL_TOOL", "APPROVAL_TOOL_NAME", "ApprovalBroker", "ApprovalError", "PendingRequest",
           "mcp_confirmation_supported", "redact", "session_eligible", "ChatApprovals", "normalize_phone",
           "BridgeError", "CodexBridge", "find_codex", "__version__"]
