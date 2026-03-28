/**
 * Teams channel adapter — thin wrapper around the Python agent API.
 *
 * Responsibilities:
 *   1. Extract user identity, text and thread context from the Teams activity
 *   2. POST a normalised AgentMessage to POST /agent
 *   3. Render the AgentResponse.text back to the Teams conversation
 *
 * All intent classification, routing, and business logic lives in Python
 * (orchestrator/router.py in Phase 2). This file has no awareness of
 * intents, tickers, or trading logic.
 */

import { TeamsActivityHandler, TurnContext, CardFactory, MessageFactory } from "botbuilder";
import config from "./config";

const API = config.pythonApiUrl;

// ── Contracts (mirrors orchestrator/contracts.py) ─────────────────────────────

interface AgentMessage {
  user_id:   string;
  platform:  string;
  text:      string;
  thread_id: string;
  timestamp: string;
}

interface AgentResponse {
  intent:             string;
  text:               string;
  requires_approval:  boolean;
  approval_context?:  Record<string, unknown>;
}

// ── HTTP helpers ──────────────────────────────────────────────────────────────

async function callAgent(msg: AgentMessage): Promise<AgentResponse> {
  const res = await fetch(`${API}/agent`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(msg),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Agent API returned ${res.status}: ${errText}`);
  }
  return res.json() as Promise<AgentResponse>;
}

async function callApprove(
  userId:     string,
  approvalId: string,
  decision:   "approve" | "reject",
): Promise<AgentResponse> {
  const res = await fetch(`${API}/agent/approve`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ approval_id: approvalId, decision, user_id: userId }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Approve API returned ${res.status}: ${errText}`);
  }
  return res.json() as Promise<AgentResponse>;
}

// ── Adaptive Card builder ─────────────────────────────────────────────────────

function buildApprovalCard(ctx: Record<string, unknown>) {
  const ticker     = String(ctx.ticker     ?? "");
  const side       = String(ctx.side       ?? "buy").toUpperCase();
  const qty        = String(ctx.qty        ?? "");
  const reason     = String(ctx.reason     ?? "");
  const narrative  = String(ctx.narrative  ?? "");
  const approvalId = String(ctx.approval_id ?? "");

  return CardFactory.adaptiveCard({
    type:    "AdaptiveCard",
    version: "1.4",
    body: [
      {
        type:   "TextBlock",
        text:   "⚠️ Trade Approval Required",
        weight: "Bolder",
        size:   "Large",
        color:  "Warning",
      },
      {
        type:  "FactSet",
        facts: [
          { title: "Ticker",      value: ticker  },
          { title: "Action",      value: `${side} ${qty} shares` },
          { title: "Risk Reason", value: reason  },
        ],
      },
      {
        type: "TextBlock",
        text: narrative,
        wrap: true,
        spacing: "Medium",
      },
    ],
    actions: [
      {
        type:  "Action.Submit",
        title: "✅ Approve",
        style: "positive",
        data:  { action: "approve", approval_id: approvalId },
      },
      {
        type:  "Action.Submit",
        title: "❌ Reject",
        style: "destructive",
        data:  { action: "reject", approval_id: approvalId },
      },
    ],
  });
}

// ── Main bot handler ──────────────────────────────────────────────────────────

export class TeamsBot extends TeamsActivityHandler {
  constructor() {
    super();

    this.onMessage(async (context: TurnContext, next) => {
      const userId    = context.activity.from?.id         ?? "unknown";
      const threadId  = context.activity.conversation?.id ?? "";
      const timestamp = context.activity.timestamp        ?? new Date().toISOString();

      // ── Handle Adaptive Card button submissions ────────────────────────────
      // When a user clicks Approve/Reject on an approval card, Teams sends
      // the activity back with activity.value containing the card action data
      // rather than activity.text.
      const cardValue = context.activity.value as
        | { action?: string; approval_id?: string }
        | undefined;

      if (cardValue?.action && cardValue?.approval_id) {
        const decision = cardValue.action as "approve" | "reject";
        console.log(`[teams:${userId}] card action: ${decision} / ${cardValue.approval_id}`);

        try {
          const response = await callApprove(
            `teams:${userId}`,
            cardValue.approval_id,
            decision,
          );
          await context.sendActivity(response.text);
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : String(err);
          console.error(`Approve error for [teams:${userId}]:`, message);
          await context.sendActivity(`❌ Error: ${message}`);
        }

        await next();
        return;
      }

      // ── Handle normal text messages ────────────────────────────────────────
      const rawText  = TurnContext.removeRecipientMention(context.activity) ?? "";
      const userText = rawText.replace(/\n|\r/g, "").trim();

      console.log(`[teams:${userId}] ${userText}`);

      const msg: AgentMessage = {
        user_id:   `teams:${userId}`,
        platform:  "teams",
        text:      userText,
        thread_id: threadId,
        timestamp: String(timestamp),
      };

      try {
        const response = await callAgent(msg);

        if (response.requires_approval && response.approval_context) {
          // Send the risk narrative as text first, then the approval card
          await context.sendActivity(response.text);
          const card = buildApprovalCard(response.approval_context);
          await context.sendActivity(MessageFactory.attachment(card));
        } else {
          await context.sendActivity(response.text);
        }
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        console.error(`Agent error for [teams:${userId}]:`, message);
        await context.sendActivity(`❌ Error: ${message}`);
      }

      await next();
    });

    this.onMembersAdded(async (context: TurnContext, next) => {
      for (const member of context.activity.membersAdded ?? []) {
        if (member.id !== context.activity.recipient.id) {
          await context.sendActivity(
            "## 👋 Stock Trading Agent Ready!\n\n" +
            "Try: **Analyze AAPL** or **Trade AAPL MSFT TSLA** or **Portfolio**"
          );
        }
      }
      await next();
    });
  }
}
