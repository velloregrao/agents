"""
Platform-agnostic message contracts for the agent orchestration layer.

AgentMessage  — normalised inbound message from any channel adapter
                (Teams, Slack, WhatsApp, Telegram, MCP, ...)

AgentResponse — normalised outbound response returned to any channel adapter

Channel adapters (teamsBot.ts, future SlackAdapter, etc.) are responsible
for translating platform-native formats to/from these contracts.
The orchestrator and all agent pipelines only ever see these types.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentMessage:
    """
    Normalised inbound message from any channel.

    Fields:
        user_id     Platform-scoped unique user identifier.
                    Format: "<platform>:<native_id>", e.g. "teams:29:abc123"
                    Used to scope memory, portfolio and risk state per user.
        platform    Source channel: "teams" | "slack" | "whatsapp" | "telegram" | "mcp"
        text        Raw user text, stripped of platform-specific formatting
                    (e.g. @-mentions removed by the Teams adapter).
        thread_id   Conversation or thread identifier from the platform.
                    Used for reply threading and conversation context.
        timestamp   ISO-8601 message timestamp from the platform.
    """
    user_id:   str
    platform:  str
    text:      str
    thread_id: str = ""
    timestamp: str = ""


@dataclass
class AgentResponse:
    """
    Normalised outbound response to any channel.

    Fields:
        intent              The classified intent, e.g. "analyze" | "trade" | "portfolio".
                            Logged for observability; used by channel adapters to pick
                            the right rendering template.
        text                Markdown-formatted response text. Channel adapters convert
                            this to platform-native format (Block Kit for Slack,
                            Adaptive Card for Teams, plain text for WhatsApp).
        requires_approval   True when the risk agent returns an ESCALATE verdict.
                            Channel adapter must render an interactive approval UI
                            rather than executing the trade immediately.
        approval_context    Populated when requires_approval is True. Contains the
                            trade proposal details needed to render the approval card
                            and to resume execution after the human approves.
                            Shape: { ticker, side, qty, reason, narrative }
    """
    intent:            str
    text:              str
    requires_approval: bool        = False
    approval_context:  Any | None  = None
