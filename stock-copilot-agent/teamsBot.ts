import { TeamsActivityHandler, TurnContext } from "botbuilder";
import config from "./config";

const API = config.pythonApiUrl;

// ── HTTP helper ───────────────────────────────────────────────────────────────
async function callAPI(path: string, body?: object): Promise<any> {
  const res = await fetch(`${API}${path}`, {
    method: body !== undefined ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path} returned ${res.status}: ${text}`);
  }
  return res.json();
}

// ── Individual command functions ──────────────────────────────────────────────
async function runAnalysis(ticker: string): Promise<string> {
  const data = await callAPI("/analyze", { ticker });
  return data.result;
}

async function runTradingAgent(tickers: string[], request: string = ""): Promise<string> {
  const data = await callAPI("/trade", { tickers, request });
  return data.result;
}

async function getPortfolio(): Promise<string> {
  const data = await callAPI("/portfolio");

  const balance   = data.balance;
  const positions = data.positions?.positions ?? [];
  const perf      = data.performance;

  if (balance?.error) return `❌ Alpaca API error: ${balance.error}`;

  const fmt = (n: any) =>
    n !== undefined && n !== null
      ? Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : "N/A";

  let response = `## 📊 Portfolio Status\n\n`;
  response += `**Cash:** $${fmt(balance.cash)}  **Portfolio Value:** $${fmt(balance.portfolio_value)}  **Buying Power:** $${fmt(balance.buying_power)}\n\n`;

  if (positions.length > 0) {
    response += `### Open Positions\n`;
    positions.forEach((p: any) => {
      const pnlEmoji = p.unrealized_pnl >= 0 ? "📈" : "📉";
      response += `- **${p.ticker}**: ${p.quantity} shares @ $${p.entry_price} | `;
      response += `Current: $${p.current_price} | `;
      response += `${pnlEmoji} ${p.unrealized_pnl >= 0 ? "+" : ""}$${p.unrealized_pnl?.toFixed(2)} (${p.unrealized_pnl_pct?.toFixed(1)}%)\n`;
    });
  } else {
    response += `### No open positions\n`;
  }

  if (perf.total_trades > 0) {
    response += `\n### Performance\n`;
    response += `- **Total Trades:** ${perf.total_trades}\n`;
    response += `- **Win Rate:** ${perf.win_rate}%\n`;
    response += `- **Total P&L:** $${perf.total_pnl}\n`;
    response += `- **Avg Return:** ${perf.avg_return_pct}%\n`;
  }

  return response;
}

async function runReflection(): Promise<string> {
  const result = await callAPI("/reflect", {});

  if (result.status === "skipped") return `⚠️ ${result.reason}`;

  let response = `## 🧠 Reflection Complete\n\n`;
  response += `**Trades Analyzed:** ${result.trades_analyzed}\n`;
  response += `**Lessons Extracted:** ${result.lessons_extracted}\n\n`;
  response += `### New Lessons\n`;
  result.lessons?.forEach((l: string, i: number) => {
    response += `${i + 1}. ${l}\n`;
  });
  response += `\n### Summary\n${result.summary}`;
  return response;
}

async function monitorPositions(): Promise<string> {
  const data = await callAPI("/monitor", {});
  return data.result;
}

async function runResearch(ticker: string, request: string = ""): Promise<string> {
  const data = await callAPI("/research", { ticker, request });
  return data.result;
}

// ── Parse intent from user message ───────────────────────────────────────────
function parseIntent(text: string): { intent: string; tickers: string[]; raw: string } {
  const upper = text.toUpperCase();
  const skipWords = new Set([
    "ANALYZE", "ANALYSIS", "STOCK", "SHARE", "PRICE", "GET", "SHOW",
    "TELL", "WHAT", "HOW", "IS", "THE", "FOR", "ME", "TRADE", "TRADES",
    "BUY", "SELL", "PORTFOLIO", "PERFORMANCE", "REFLECT", "REFLECTION",
    "MONITOR", "POSITIONS", "HELP", "HI", "HELLO", "AND", "ON", "A",
    "RUN", "CHECK", "MY",
  ]);

  const words   = upper.replace(/[^A-Z\s]/g, "").split(/\s+/);
  const tickers = words.filter(w => w.length >= 1 && w.length <= 5 && !skipWords.has(w));

  if (/^(hi|hello|hey|help)$/i.test(text.trim()))          return { intent: "help",      tickers: [],     raw: text };
  if (/portfolio|positions|holdings/i.test(text))           return { intent: "portfolio", tickers,         raw: text };
  if (/performance|stats|statistics|pnl|profit/i.test(text)) return { intent: "portfolio", tickers,       raw: text };
  if (/reflect|reflection|lessons|learn/i.test(text))       return { intent: "reflect",   tickers: [],     raw: text };
  if (/monitor|check positions|review positions/i.test(text)) return { intent: "monitor", tickers: [],    raw: text };
  if (/research|deep.?dive|full.?analysis|recommend/i.test(text) && tickers.length > 0)
                                                             return { intent: "research",  tickers,         raw: text };
  if (/trade|buy|sell|invest|run agent/i.test(text) && tickers.length > 0)
                                                             return { intent: "trade",     tickers,         raw: text };
  if (tickers.length > 0)                                    return { intent: "analyze",   tickers,         raw: text };

  return { intent: "unknown", tickers: [], raw: text };
}

// ── Main bot handler ──────────────────────────────────────────────────────────
export class TeamsBot extends TeamsActivityHandler {
  constructor() {
    super();

    this.onMessage(async (context: TurnContext, next) => {
      const rawText  = TurnContext.removeRecipientMention(context.activity) ?? "";
      const userText = rawText.replace(/\n|\r/g, "").trim();
      console.log(`User message: ${userText}`);

      const { intent, tickers, raw } = parseIntent(userText);

      try {
        switch (intent) {
          case "help":
            await context.sendActivity(
              "## 🤖 Stock Trading Agent v2\n\n" +
              "**Commands:**\n" +
              "- **Analyze AAPL** — Quick stock analysis\n" +
              "- **Research NVDA** — Deep multi-agent research (news + technicals + memory)\n" +
              "- **Trade AAPL MSFT TSLA** — Run trading agent on watchlist\n" +
              "- **Portfolio** — Show positions and balance\n" +
              "- **Reflect** — Extract lessons from trade history\n" +
              "- **Monitor** — Review open positions for exits\n\n" +
              "*Powered by Claude + Alpaca paper trading*"
            );
            break;

          case "analyze":
            await context.sendActivity(`🔍 Analyzing **${tickers[0]}**...`);
            await context.sendActivity(await runAnalysis(tickers[0]));
            break;

          case "research":
            await context.sendActivity(`🧠 Running multi-agent research on **${tickers[0]}**... this may take 30–60 seconds.`);
            await context.sendActivity(await runResearch(tickers[0], raw));
            break;

          case "trade":
            await context.sendActivity(`🤖 Running trading agent on **${tickers.join(", ")}**... this may take 30–60 seconds.`);
            await context.sendActivity(await runTradingAgent(tickers, raw));
            break;

          case "portfolio":
            await context.sendActivity(`📊 Fetching portfolio...`);
            await context.sendActivity(await getPortfolio());
            break;

          case "reflect":
            await context.sendActivity(`🧠 Running reflection engine...`);
            await context.sendActivity(await runReflection());
            break;

          case "monitor":
            await context.sendActivity(`👁️ Monitoring open positions...`);
            await context.sendActivity(await monitorPositions());
            break;

          default:
            await context.sendActivity(
              "I didn't understand that. Try:\n" +
              "- **Analyze AAPL**\n" +
              "- **Trade AAPL MSFT**\n" +
              "- **Portfolio**\n" +
              "- **Reflect**\n" +
              "- **Monitor**"
            );
        }
      } catch (err: any) {
        console.error(`Error handling intent "${intent}":`, err.message);
        await context.sendActivity(`❌ Error: ${err.message}`);
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
