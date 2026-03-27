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

import { TeamsActivityHandler, TurnContext } from "botbuilder";
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

// ── HTTP helper ───────────────────────────────────────────────────────────────

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

// ── Main bot handler ──────────────────────────────────────────────────────────

export class TeamsBot extends TeamsActivityHandler {
  constructor() {
    super();

    this.onMessage(async (context: TurnContext, next) => {
      const rawText  = TurnContext.removeRecipientMention(context.activity) ?? "";
      const userText = rawText.replace(/\n|\r/g, "").trim();

      const userId   = context.activity.from?.id          ?? "unknown";
      const threadId = context.activity.conversation?.id  ?? "";
      const timestamp = context.activity.timestamp        ?? new Date().toISOString();

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
        await context.sendActivity(response.text);
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
