/**
 * Teams channel adapter — thin wrapper around the Python agent API.
 *
 * Responsibilities:
 *   1. Extract user identity, text and thread context from the Teams activity
 *   2. POST a normalised AgentMessage to POST /agent
 *   3. Render the AgentResponse.text back to the Teams conversation
 *   4. Store ConversationReference on every message for proactive push
 *   5. Poll /alerts/pending every 30 s and push signal cards via continueConversation()
 *
 * All intent classification, routing, and business logic lives in Python
 * (orchestrator/router.py). This file has no awareness of intents, tickers,
 * or trading logic beyond rendering the cards it receives back.
 */

import {
  TeamsActivityHandler,
  TurnContext,
  CardFactory,
  MessageFactory,
  CloudAdapter,
  ConversationReference,
} from "botbuilder";
import config from "./config";

const API = config.pythonApiUrl;

// Polling interval: 30 seconds
const ALERT_POLL_INTERVAL_MS = 30_000;

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

interface SignalPayload {
  ticker:    string;
  score:     number;
  direction: string;
  summary:   string;
  price:     number;
  rsi:       number;
}

interface RiskPayload {
  verdict:      string;
  adjusted_qty: number;
  reason:       string;
  narrative:    string;
}

interface EarningsPayload {
  ticker:           string;
  earnings_date:    string;
  days_until:       number;
  eps_estimate:     number | null;
  eps_low:          number | null;
  eps_high:         number | null;
  revenue_estimate: number | null;
  analyst_rating:   string | null;
  analyst_target:   number | null;
  thesis:           string;
  summary:          string;
  sentiment:        string;
}

interface PendingAlert {
  id:               number;
  user_id:          string;
  ticker:           string;
  alert_type:       string;          // "signal" | "earnings"
  signal:           SignalPayload | EarningsPayload;
  risk:             RiskPayload;
  proposed_qty:     number;
  created_at:       string;
  conversation_ref: ConversationReference | null;
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

async function storeConversationRef(
  userId: string,
  ref:    Partial<ConversationReference>,
): Promise<void> {
  await fetch(`${API}/alerts/store-ref`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ user_id: userId, conversation_ref: ref }),
  });
}

async function fetchPendingAlerts(): Promise<PendingAlert[]> {
  const res = await fetch(`${API}/alerts/pending`);
  if (!res.ok) return [];
  const data = (await res.json()) as { alerts: PendingAlert[] };
  return data.alerts ?? [];
}

async function markAlertDelivered(alertId: number): Promise<void> {
  await fetch(`${API}/alerts/delivered/${alertId}`, { method: "POST" });
}

// ── Adaptive Card builders ────────────────────────────────────────────────────

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
        type:    "TextBlock",
        text:    narrative,
        wrap:    true,
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

function buildSignalCard(alert: PendingAlert) {
  const { ticker, risk, proposed_qty, id } = alert;
  const signal = alert.signal as SignalPayload;

  // Direction emoji and colour
  const isBullish = signal.direction === "bullish";
  const emoji     = isBullish ? "📈" : "📉";
  const color     = isBullish ? "Good" : "Attention";

  // Risk verdict badge
  const verdictBadge: Record<string, string> = {
    APPROVED:  "✅ APPROVED",
    RESIZE:    "🔄 RESIZE",
    ESCALATE:  "⚠️ ESCALATE",
  };
  const verdictLabel = verdictBadge[risk.verdict] ?? risk.verdict;

  // Effective qty: risk.adjusted_qty if available, else proposed
  const qty  = risk.adjusted_qty > 0 ? risk.adjusted_qty : proposed_qty;
  const side = isBullish ? "BUY" : "SELL";

  return CardFactory.adaptiveCard({
    type:    "AdaptiveCard",
    version: "1.4",
    body: [
      {
        type:   "TextBlock",
        text:   `${emoji} ${ticker} — ${signal.direction.toUpperCase()} Signal Fired`,
        weight: "Bolder",
        size:   "Large",
        color,
      },
      {
        type:  "FactSet",
        facts: [
          { title: "Score",     value: `${signal.score > 0 ? "+" : ""}${signal.score.toFixed(1)} / 10` },
          { title: "Price",     value: `$${signal.price.toFixed(2)}`  },
          { title: "RSI",       value: signal.rsi.toFixed(1)          },
          { title: "Risk",      value: verdictLabel                   },
          { title: "Qty",       value: `${qty} shares (${side})`      },
        ],
      },
      {
        type:    "TextBlock",
        text:    signal.summary,
        wrap:    true,
        spacing: "Medium",
        isSubtle: true,
      },
      ...(risk.narrative ? [{
        type:    "TextBlock",
        text:    `⚠️ ${risk.narrative}`,
        wrap:    true,
        spacing: "Small",
        color:   "Warning",
        isSubtle: true,
      }] : []),
    ],
    actions: [
      {
        type:  "Action.Submit",
        title: `🚀 Trade Now (${side} ${qty})`,
        style: "positive",
        data:  {
          action:   "trade_signal",
          ticker,
          qty,
          side:     side.toLowerCase(),
          alert_id: id,
        },
      },
      {
        type:  "Action.Submit",
        title: "✖ Dismiss",
        data:  { action: "dismiss_alert", alert_id: id },
      },
    ],
  });
}

function buildEarningsCard(alert: PendingAlert) {
  const e       = alert.signal as EarningsPayload;
  const { id }  = alert;

  const sentColor: Record<string, string> = {
    bullish: "Good", bearish: "Attention", neutral: "Default",
  };
  const sentEmoji: Record<string, string> = {
    bullish: "🟢", bearish: "🔴", neutral: "🟡",
  };
  const color = sentColor[e.sentiment] ?? "Default";
  const emoji = sentEmoji[e.sentiment] ?? "🟡";

  const epsStr = e.eps_estimate != null ? `$${e.eps_estimate.toFixed(2)}` : "N/A";
  const epsRange = (e.eps_low != null && e.eps_high != null)
    ? ` (${e.eps_low.toFixed(2)} – ${e.eps_high.toFixed(2)})`
    : "";
  const revStr = e.revenue_estimate != null
    ? `$${(e.revenue_estimate / 1e9).toFixed(1)}B`
    : "N/A";
  const targetStr = e.analyst_target != null
    ? `$${e.analyst_target.toFixed(2)}`
    : "N/A";

  return CardFactory.adaptiveCard({
    type:    "AdaptiveCard",
    version: "1.4",
    body: [
      {
        type:   "TextBlock",
        text:   `📅 ${alert.ticker} — Earnings in ${e.days_until} day(s)`,
        weight: "Bolder",
        size:   "Large",
        color,
      },
      {
        type:  "FactSet",
        facts: [
          { title: "Date",           value: e.earnings_date },
          { title: "EPS Estimate",   value: `${epsStr}${epsRange}` },
          { title: "Revenue Est",    value: revStr },
          { title: "Analyst Target", value: targetStr },
          { title: "Rating",         value: e.analyst_rating ?? "N/A" },
          { title: "Sentiment",      value: `${emoji} ${(e.sentiment ?? "neutral").toUpperCase()}` },
        ],
      },
      {
        type:     "TextBlock",
        text:     e.summary,
        wrap:     true,
        spacing:  "Medium",
        weight:   "Bolder",
      },
      {
        type:     "TextBlock",
        text:     e.thesis,
        wrap:     true,
        spacing:  "Small",
        isSubtle: true,
      },
    ],
    actions: [
      {
        type:  "Action.Submit",
        title: `🔍 Research ${alert.ticker}`,
        style: "positive",
        data:  { action: "analyze_earnings", ticker: alert.ticker, alert_id: id },
      },
      {
        type: "Action.Submit",
        title: "✖ Dismiss",
        data: { action: "dismiss_alert", alert_id: id },
      },
    ],
  });
}

// ── Main bot handler ──────────────────────────────────────────────────────────

export class TeamsBot extends TeamsActivityHandler {
  private readonly adapter: CloudAdapter;

  constructor(adapter: CloudAdapter) {
    super();
    this.adapter = adapter;

    this.onMessage(async (context: TurnContext, next) => {
      const userId    = context.activity.from?.id         ?? "unknown";
      const threadId  = context.activity.conversation?.id ?? "";
      const timestamp = context.activity.timestamp        ?? new Date().toISOString();
      const teamsBotId = `teams:${userId}`;

      // ── Store ConversationReference for proactive push ─────────────────────
      try {
        const ref = TurnContext.getConversationReference(context.activity);
        await storeConversationRef(teamsBotId, ref);
      } catch (err) {
        console.warn("[proactive] failed to store conversation ref:", err);
      }

      // ── Handle Adaptive Card button submissions ────────────────────────────
      const cardValue = context.activity.value as
        | { action?: string; approval_id?: string; ticker?: string; qty?: number; side?: string; alert_id?: number }
        | undefined;

      if (cardValue?.action) {
        const { action } = cardValue;

        // Approval card: Approve / Reject
        if ((action === "approve" || action === "reject") && cardValue.approval_id) {
          console.log(`[teams:${userId}] card action: ${action} / ${cardValue.approval_id}`);
          try {
            const response = await callApprove(teamsBotId, cardValue.approval_id, action);
            await context.sendActivity(response.text);
          } catch (err: unknown) {
            const message = err instanceof Error ? err.message : String(err);
            console.error(`Approve error for [teams:${userId}]:`, message);
            await context.sendActivity(`❌ Error: ${message}`);
          }
          await next();
          return;
        }

        // Earnings card: Research Now
        if (action === "analyze_earnings" && cardValue.ticker) {
          if (cardValue.alert_id) await markAlertDelivered(cardValue.alert_id).catch(() => {});
          console.log(`[teams:${userId}] earnings research: ${cardValue.ticker}`);
          try {
            const msg: AgentMessage = {
              user_id:   teamsBotId,
              platform:  "teams",
              text:      `research ${cardValue.ticker}`,
              thread_id: threadId,
              timestamp: String(timestamp),
            };
            const response = await callAgent(msg);
            await context.sendActivity(response.text);
          } catch (err: unknown) {
            const message = err instanceof Error ? err.message : String(err);
            await context.sendActivity(`❌ Research error: ${message}`);
          }
          await next();
          return;
        }

        // Signal card: Trade Now
        if (action === "trade_signal" && cardValue.ticker) {
          const tradeText = `${cardValue.side ?? "buy"} ${cardValue.qty ?? 1} ${cardValue.ticker}`;
          console.log(`[teams:${userId}] signal trade: ${tradeText}`);
          // Mark alert delivered so it won't be re-pushed
          if (cardValue.alert_id) {
            await markAlertDelivered(cardValue.alert_id).catch(() => {});
          }
          try {
            const msg: AgentMessage = {
              user_id:   teamsBotId,
              platform:  "teams",
              text:      tradeText,
              thread_id: threadId,
              timestamp: String(timestamp),
            };
            const response = await callAgent(msg);
            if (response.requires_approval && response.approval_context) {
              await context.sendActivity(response.text);
              await context.sendActivity(MessageFactory.attachment(buildApprovalCard(response.approval_context)));
            } else {
              await context.sendActivity(response.text);
            }
          } catch (err: unknown) {
            const message = err instanceof Error ? err.message : String(err);
            await context.sendActivity(`❌ Trade error: ${message}`);
          }
          await next();
          return;
        }

        // Signal card: Dismiss
        if (action === "dismiss_alert" && cardValue.alert_id) {
          await markAlertDelivered(cardValue.alert_id).catch(() => {});
          await context.sendActivity(`✓ Alert dismissed.`);
          await next();
          return;
        }
      }

      // ── Handle normal text messages ────────────────────────────────────────
      const rawText  = TurnContext.removeRecipientMention(context.activity) ?? "";
      const userText = rawText.replace(/\n|\r/g, "").trim();

      console.log(`[teams:${userId}] ${userText}`);

      const msg: AgentMessage = {
        user_id:   teamsBotId,
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
            "Try: **Analyze AAPL** or **Trade AAPL MSFT TSLA** or **Portfolio**\n\n" +
            "_Proactive signal alerts are active — I'll push watchlist signals here automatically._"
          );
          // Store conversation reference so proactive push works from first interaction
          try {
            const ref = TurnContext.getConversationReference(context.activity);
            const newMemberId = `teams:${member.id}`;
            await storeConversationRef(newMemberId, ref);
          } catch (_) { /* non-fatal */ }
        }
      }
      await next();
    });

    // Start the proactive alert polling loop
    this.startAlertPolling();
  }

  // ── Proactive push loop ───────────────────────────────────────────────────

  private startAlertPolling(): void {
    console.log(`[proactive] alert polling started (interval: ${ALERT_POLL_INTERVAL_MS / 1000}s)`);

    setInterval(async () => {
      try {
        await this.deliverPendingAlerts();
      } catch (err) {
        console.error("[proactive] poll cycle error:", err);
      }
    }, ALERT_POLL_INTERVAL_MS);
  }

  private async deliverPendingAlerts(): Promise<void> {
    const alerts = await fetchPendingAlerts();
    if (alerts.length === 0) return;

    console.log(`[proactive] ${alerts.length} pending alert(s) to deliver`);

    for (const alert of alerts) {
      if (!alert.conversation_ref) {
        console.warn(
          `[proactive] no conversation ref for ${alert.user_id} — skipping alert ${alert.id}`,
        );
        continue;
      }

      try {
        await this.adapter.continueConversation(
          alert.conversation_ref as ConversationReference,
          async (proactiveCtx: TurnContext) => {
            const card = alert.alert_type === "earnings"
              ? buildEarningsCard(alert)
              : buildSignalCard(alert);
            await proactiveCtx.sendActivity(MessageFactory.attachment(card));
          },
        );
        await markAlertDelivered(alert.id);
        console.log(
          `[proactive] delivered alert ${alert.id} (${alert.ticker}) to ${alert.user_id}`,
        );
      } catch (err) {
        console.error(
          `[proactive] failed to deliver alert ${alert.id} to ${alert.user_id}:`,
          err,
        );
        // Don't mark delivered — will retry on next poll cycle
      }
    }
  }
}
