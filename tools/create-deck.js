// create-deck.js — Stock Copilot Slide Deck
// Run: node tools/create-deck.js

const pptxgen = require("pptxgenjs");
const path    = require("path");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.title  = "Stock Copilot — AI-Powered Multi-Agent Trading System";

// ── Design tokens ─────────────────────────────────────────────────────────────
const C = {
  bg:       "0F1117",
  surface:  "1A1D27",
  surface2: "252836",
  border:   "2A2D3A",
  accent:   "3B82F6",
  accentDk: "1D4ED8",
  green:    "22C55E",
  red:      "EF4444",
  yellow:   "F59E0B",
  white:    "FFFFFF",
  muted:    "94A3B8",
  dim:      "4B5563",
  mono:     "818CF8",  // indigo for code/mono elements
};

const F = { title: "Inter", body: "Inter", mono: "Consolas" };

const makeShadow = () => ({
  type: "outer", blur: 8, offset: 2, angle: 135, color: "000000", opacity: 0.35
});

const SCREENS = {
  dashboard:    path.resolve(__dirname, "screens/dashboard.png"),
  chat:         path.resolve(__dirname, "screens/chat.png"),
  approval:     path.resolve(__dirname, "screens/trade-approval.png"),
  signals:      path.resolve(__dirname, "screens/signals.png"),
  journal:      path.resolve(__dirname, "screens/journal.png"),
  settings:     path.resolve(__dirname, "screens/settings.png"),
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function darkSlide() {
  const s = pres.addSlide();
  s.background = { color: C.bg };
  return s;
}

// Top nav bar with slide title
function addNav(slide, label) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.48,
    fill: { color: C.surface }, line: { color: C.border, width: 0.5 }
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.22, h: 0.48,
    fill: { color: C.accent }, line: { color: C.accent, width: 0 }
  });
  slide.addText("Stock Copilot", {
    x: 0.32, y: 0, w: 3, h: 0.48,
    fontSize: 11, bold: true, color: C.white, fontFace: F.title,
    valign: "middle", margin: 0
  });
  if (label) {
    slide.addText(label, {
      x: 0, y: 0, w: 9.6, h: 0.48,
      fontSize: 11, color: C.muted, fontFace: F.body,
      align: "right", valign: "middle", margin: 0
    });
  }
}

// Section card with left accent bar
function addCard(slide, x, y, w, h, opts = {}) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: opts.fill || C.surface },
    line: { color: opts.border || C.border, width: 0.75 },
    shadow: makeShadow()
  });
  if (opts.accent !== false) {
    slide.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.06, h,
      fill: { color: opts.accentColor || C.accent },
      line: { color: opts.accentColor || C.accent, width: 0 }
    });
  }
}

// Stat tile
function addStat(slide, x, y, value, label, color) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 2.1, h: 1.0,
    fill: { color: C.surface }, line: { color: C.border, width: 0.75 },
    shadow: makeShadow()
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 2.1, h: 0.055,
    fill: { color: color || C.accent }, line: { color: color || C.accent, width: 0 }
  });
  slide.addText(value, {
    x: x + 0.15, y: y + 0.12, w: 1.8, h: 0.5,
    fontSize: 30, bold: true, color: color || C.white,
    fontFace: F.mono, margin: 0
  });
  slide.addText(label, {
    x: x + 0.15, y: y + 0.62, w: 1.8, h: 0.28,
    fontSize: 9.5, color: C.muted, fontFace: F.body, margin: 0
  });
}

// Badge
function addBadge(slide, x, y, text, color) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 1.1, h: 0.24,
    fill: { color: color, transparency: 80 },
    line: { color: color, width: 0.75 }
  });
  slide.addText(text, {
    x, y, w: 1.1, h: 0.24,
    fontSize: 8, bold: true, color: color,
    align: "center", valign: "middle", margin: 0, fontFace: F.body
  });
}

// Pipeline step box
function addPipeBox(slide, x, y, w, h, title, subtitle, color) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: C.surface2 }, line: { color: color || C.accent, width: 1.2 },
    shadow: makeShadow()
  });
  slide.addText(title, {
    x: x + 0.12, y: y + 0.1, w: w - 0.24, h: 0.28,
    fontSize: 11, bold: true, color: color || C.white, fontFace: F.title, margin: 0
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: x + 0.12, y: y + 0.38, w: w - 0.24, h: 0.24,
      fontSize: 8.5, color: C.muted, fontFace: F.body, margin: 0
    });
  }
}

// Arrow right
function addArrow(slide, x, y, color) {
  slide.addShape(pres.shapes.LINE, {
    x, y, w: 0.32, h: 0,
    line: { color: color || C.accent, width: 1.5 }
  });
  slide.addShape(pres.shapes.LINE, {
    x: x + 0.18, y: y - 0.07, w: 0.14, h: 0.07,
    line: { color: color || C.accent, width: 1.5 }
  });
  slide.addShape(pres.shapes.LINE, {
    x: x + 0.18, y: y + 0.07, w: 0.14, h: -0.07,
    line: { color: color || C.accent, width: 1.5 }
  });
}

// Arrow down
function addArrowDown(slide, x, y, color) {
  slide.addShape(pres.shapes.LINE, {
    x, y, w: 0, h: 0.22,
    line: { color: color || C.dim, width: 1.5 }
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 1 — Title
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };

  // Left accent band
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.55, h: 5.625,
    fill: { color: C.accent }, line: { color: C.accent, width: 0 }
  });

  // Top-right decorative grid dots (3x3)
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 4; c++) {
      s.addShape(pres.shapes.OVAL, {
        x: 8.5 + c * 0.38, y: 0.3 + r * 0.38, w: 0.08, h: 0.08,
        fill: { color: C.border }, line: { color: C.border, width: 0 }
      });
    }
  }

  // Main title
  s.addText("Stock Copilot", {
    x: 0.9, y: 1.2, w: 8.5, h: 1.4,
    fontSize: 58, bold: true, color: C.white, fontFace: F.title,
    margin: 0
  });

  // Accent line under title
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.9, y: 2.65, w: 5.2, h: 0.055,
    fill: { color: C.accent }, line: { color: C.accent, width: 0 }
  });

  // Subtitle
  s.addText("AI-Powered Multi-Agent Trading System", {
    x: 0.9, y: 2.8, w: 8.5, h: 0.55,
    fontSize: 22, color: C.muted, fontFace: F.body, margin: 0
  });

  // Tag pills
  const tags = ["Anthropic Claude", "Alpaca Markets", "Azure Container Apps", "React Web UI"];
  tags.forEach((t, i) => {
    const tx = 0.9 + i * 2.15;
    s.addShape(pres.shapes.RECTANGLE, {
      x: tx, y: 3.55, w: 2.0, h: 0.3,
      fill: { color: C.surface2 }, line: { color: C.border, width: 0.75 }
    });
    s.addText(t, {
      x: tx, y: 3.55, w: 2.0, h: 0.3,
      fontSize: 9, color: C.muted, align: "center", valign: "middle",
      fontFace: F.body, margin: 0
    });
  });

  // Bottom bar
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.27, w: 10, h: 0.355,
    fill: { color: C.surface }, line: { color: C.border, width: 0 }
  });
  s.addText("Multi-Agent Architecture  ·  Figma Design  ·  Azure Deployment  ·  Automated Testing", {
    x: 0.6, y: 5.27, w: 9.0, h: 0.355,
    fontSize: 9.5, color: C.dim, fontFace: F.body, valign: "middle", margin: 0
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 2 — System at a Glance
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "System Overview");

  s.addText("System at a Glance", {
    x: 0.5, y: 0.65, w: 9, h: 0.55,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  // Stats row
  addStat(s, 0.5,  1.35, "3",   "Interface Channels",    C.accent);
  addStat(s, 2.75, 1.35, "6",   "Agent Modules",         C.green);
  addStat(s, 5.0,  1.35, "4",   "Risk Safety Rules",     C.yellow);
  addStat(s, 7.25, 1.35, "272", "Automated Tests",       C.mono);

  // Description cards
  const cards = [
    { title: "Teams Bot", desc: "Azure Bot Service with Adaptive Cards for alerts, approvals, and commands" },
    { title: "Claude Desktop", desc: "7 MCP tools expose all agent capabilities to Claude locally" },
    { title: "Web UI", desc: "React dashboard deployed to Azure Static Web Apps, live data from same API" },
    { title: "Python API", desc: "FastAPI backend on Azure Container Apps — single source of truth for all channels" },
  ];
  cards.forEach((c, i) => {
    const cx = 0.5 + i * 2.35;
    addCard(s, cx, 2.65, 2.18, 1.8);
    s.addText(c.title, {
      x: cx + 0.18, y: 2.72, w: 1.9, h: 0.3,
      fontSize: 11, bold: true, color: C.white, fontFace: F.title, margin: 0
    });
    s.addText(c.desc, {
      x: cx + 0.18, y: 3.04, w: 1.9, h: 1.2,
      fontSize: 9, color: C.muted, fontFace: F.body, margin: 0
    });
  });

  // One rule banner
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 4.65, w: 9, h: 0.65,
    fill: { color: C.surface }, line: { color: C.border, width: 0.75 }
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 4.65, w: 0.06, h: 0.65,
    fill: { color: C.red }, line: { color: C.red, width: 0 }
  });
  s.addText("Critical Rule:", {
    x: 0.72, y: 4.72, w: 1.4, h: 0.52,
    fontSize: 10, bold: true, color: C.red, fontFace: F.body,
    valign: "middle", margin: 0
  });
  s.addText("Every trade proposal MUST pass through risk_agent.evaluate_proposal() before any order is submitted to Alpaca. Never call trade.py directly.", {
    x: 2.1, y: 4.72, w: 7.2, h: 0.52,
    fontSize: 10, color: C.muted, fontFace: F.body, valign: "middle", margin: 0, italic: true
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 3 — Multi-Agent Architecture Pipeline
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "Architecture");

  s.addText("Multi-Agent Architecture", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  // Horizontal pipeline
  const steps = [
    { label: "User Channel",     sub: "Teams · Claude\nDesktop · Web UI", color: C.muted  },
    { label: "Router",           sub: "Intent classify\nHaiku model",      color: C.accent },
    { label: "Risk Agent",       sub: "4 rules\nGenerator-critic",         color: C.red    },
    { label: "Analysis Agent",   sub: "Claude Sonnet\nRSI · EMA · VWAP",  color: C.green  },
    { label: "Trade Execution",  sub: "Alpaca Markets\nPaper trading",     color: C.yellow },
  ];

  const bw = 1.6, bh = 1.0, gap = 0.3;
  const startX = 0.4;
  steps.forEach((st, i) => {
    const x = startX + i * (bw + gap);
    addPipeBox(s, x, 1.4, bw, bh, st.label, st.sub, st.color);
    if (i < steps.length - 1) {
      addArrow(s, x + bw + 0.04, 1.4 + bh / 2, st.color);
    }
  });

  // Detail cards below
  const details = [
    {
      title: "orchestrator/router.py",
      items: ["Haiku for routing (fast/cheap)", "Regex fallback classification", "Dispatches to specialist agents", "Returns requires_approval flag"],
      color: C.accent
    },
    {
      title: "orchestrator/risk_agent.py",
      items: ["Runs BEFORE every trade", "APPROVED / RESIZE / BLOCK / ESCALATE", "Iterative: RESIZE triggers re-run", "Posts Teams card on ESCALATE"],
      color: C.red
    },
    {
      title: "stock-analysis-agent/",
      items: ["RSI, EMA, VWAP, Momentum", "Brave Search for news sentiment", "Sonnet for thesis generation", "Multi-timeframe support (planned)"],
      color: C.green
    },
    {
      title: "orchestrator/portfolio_optimizer.py",
      items: ["Iterative refinement pattern", "Propose → Critique → Refine", "Accounts for pending orders", "Requires human approval"],
      color: C.yellow
    },
  ];

  details.forEach((d, i) => {
    const cx = 0.4 + i * 2.4;
    addCard(s, cx, 2.72, 2.28, 2.45, { accentColor: d.color });
    s.addText(d.title, {
      x: cx + 0.2, y: 2.78, w: 2.0, h: 0.3,
      fontSize: 9.5, bold: true, color: d.color, fontFace: F.mono, margin: 0
    });
    d.items.forEach((item, j) => {
      s.addText([
        { text: "› ", options: { color: d.color, bold: true } },
        { text: item, options: { color: C.muted } }
      ], {
        x: cx + 0.2, y: 3.1 + j * 0.34, w: 2.0, h: 0.3,
        fontSize: 9, fontFace: F.body, margin: 0
      });
    });
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 4 — Agent Design Patterns
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "Agent Patterns");

  s.addText("Agent Design Patterns", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  const patterns = [
    { name: "Generator + Critic",       where: "risk_agent.py",          desc: "Analysis agent proposes trades. Risk agent critiques and vetoes or resizes before execution.", color: C.red,    status: "LIVE" },
    { name: "Sequential Pipeline",      where: "router.py",              desc: "Signal → risk check → execution. Strict ordering. No step can be skipped.", color: C.accent, status: "LIVE" },
    { name: "Human-in-the-Loop",        where: "Teams Adaptive Cards",   desc: "ESCALATE and BLOCK verdicts send approval cards. No trade executes without human sign-off.", color: C.green,  status: "LIVE" },
    { name: "Iterative Refinement",     where: "portfolio_optimizer.py", desc: "Portfolio optimizer proposes → risk critic resizes → re-runs until within limits.", color: C.yellow, status: "LIVE" },
    { name: "Coordinator / Dispatcher", where: "router.py",              desc: "Single entry point routes all natural language commands to specialist agents.", color: C.mono,   status: "LIVE" },
    { name: "Parallel Fan-out",         where: "Watchlist monitor",      desc: "asyncio.gather() scans N tickers concurrently. Signals filtered through scoring threshold.", color: C.muted,  status: "PLANNED" },
  ];

  patterns.forEach((p, i) => {
    const row = Math.floor(i / 3);
    const col = i % 3;
    const cx = 0.4 + col * 3.1;
    const cy = 1.35 + row * 1.95;

    addCard(s, cx, cy, 2.9, 1.8, { accentColor: p.color });

    // Status badge
    addBadge(s, cx + 1.66, cy + 0.1, p.status, p.status === "LIVE" ? C.green : C.yellow);

    s.addText(p.name, {
      x: cx + 0.2, y: cy + 0.1, w: 1.6, h: 0.32,
      fontSize: 11, bold: true, color: p.color, fontFace: F.title, margin: 0
    });
    s.addText(p.where, {
      x: cx + 0.2, y: cy + 0.42, w: 2.55, h: 0.22,
      fontSize: 8.5, color: C.dim, fontFace: F.mono, margin: 0, italic: true
    });
    s.addText(p.desc, {
      x: cx + 0.2, y: cy + 0.68, w: 2.6, h: 1.0,
      fontSize: 9, color: C.muted, fontFace: F.body, margin: 0
    });
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 5 — Risk Agent Safety Gates
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "Risk Agent");

  s.addText("Risk Agent — 4 Safety Gates", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });
  s.addText("Every trade proposal passes through all 4 rules in sequence before execution", {
    x: 0.5, y: 1.18, w: 9, h: 0.3,
    fontSize: 12, color: C.muted, fontFace: F.body, margin: 0
  });

  const rules = [
    {
      num: "01", title: "Daily Loss Circuit Breaker",
      threshold: "RISK_DAILY_LOSS_HALT = -2%",
      desc: "Halts ALL trading for the day if portfolio is down more than 2%. Protects against runaway losses in volatile markets.",
      verdict: "BLOCK", color: C.red
    },
    {
      num: "02", title: "Position Size Limit",
      threshold: "RISK_MAX_POSITION_PCT = 5%",
      desc: "No single position may exceed 5% of total equity. If proposed qty is too large, auto-resizes to the maximum allowed.",
      verdict: "RESIZE", color: C.yellow
    },
    {
      num: "03", title: "Sector Concentration",
      threshold: "RISK_MAX_SECTOR_CONC_PCT = 25%",
      desc: "No single GICS sector may exceed 25% of equity. Prevents over-exposure to tech, energy, or any single sector.",
      verdict: "ESCALATE", color: C.mono
    },
    {
      num: "04", title: "Correlation Guard",
      threshold: "Known pairs: NVDA↔AMD, etc.",
      desc: "Escalates if the proposed ticker is in a known correlated pair with a currently held position. Avoids doubling correlated risk.",
      verdict: "ESCALATE", color: C.mono
    },
  ];

  rules.forEach((r, i) => {
    const cx = 0.4 + (i % 2) * 4.8;
    const cy = 1.7 + Math.floor(i / 2) * 1.85;
    addCard(s, cx, cy, 4.55, 1.65, { accentColor: r.color });

    s.addText(r.num, {
      x: cx + 0.2, y: cy + 0.12, w: 0.5, h: 0.45,
      fontSize: 22, bold: true, color: r.color, fontFace: F.mono,
      opacity: 0.4, margin: 0
    });
    s.addText(r.title, {
      x: cx + 0.72, y: cy + 0.12, w: 2.8, h: 0.34,
      fontSize: 13, bold: true, color: C.white, fontFace: F.title, margin: 0
    });
    addBadge(s, cx + 3.3, cy + 0.14, r.verdict, r.color);
    s.addText(r.threshold, {
      x: cx + 0.72, y: cy + 0.46, w: 3.6, h: 0.22,
      fontSize: 9, color: r.color, fontFace: F.mono, margin: 0
    });
    s.addText(r.desc, {
      x: cx + 0.2, y: cy + 0.74, w: 4.22, h: 0.8,
      fontSize: 9.5, color: C.muted, fontFace: F.body, margin: 0
    });
  });

  // Verdict legend
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 5.12, w: 9.2, h: 0.32,
    fill: { color: C.surface }, line: { color: C.border, width: 0.5 }
  });
  const verdicts = [
    { v: "APPROVED", c: C.green },
    { v: "RESIZE",   c: C.yellow },
    { v: "BLOCK",    c: C.red },
    { v: "ESCALATE", c: C.mono },
  ];
  s.addText("Verdicts: ", {
    x: 0.6, y: 5.12, w: 1.0, h: 0.32,
    fontSize: 9, bold: true, color: C.muted, valign: "middle", margin: 0
  });
  verdicts.forEach((v, i) => {
    addBadge(s, 1.5 + i * 1.35, 5.18, v.v, v.c);
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 6 — Three Interface Channels
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "Interface Channels");

  s.addText("Three Interface Channels", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });
  s.addText("All channels share the same Python API, Alpaca account, and risk gate", {
    x: 0.5, y: 1.18, w: 9, h: 0.28,
    fontSize: 12, color: C.muted, fontFace: F.body, margin: 0
  });

  const channels = [
    {
      title: "Microsoft Teams Bot",
      color: C.accent,
      deploy: "Azure Container Apps",
      framework: "Azure Bot Service + TypeScript",
      features: [
        "Natural language commands",
        "Adaptive Cards for trade approvals",
        "Proactive alerts (signals, earnings)",
        "Inline rebalance approval flow",
      ],
      commands: "Analyze · News · Portfolio · Optimize · Digest"
    },
    {
      title: "Claude Desktop (MCP)",
      color: C.green,
      deploy: "Local MCP server",
      framework: "Model Context Protocol",
      features: [
        "7 MCP tools in Claude Desktop",
        "Natural language on desktop + mobile",
        "target_allocation, optimize_portfolio",
        "earnings_analysis, mtf_analysis",
      ],
      commands: "Accessible from Claude chat on any device"
    },
    {
      title: "Stock Copilot Web UI",
      color: C.mono,
      deploy: "Azure Static Web Apps",
      framework: "React + Tailwind + Vite",
      features: [
        "Dashboard with live positions",
        "Chat drawer → agent commands",
        "Trade approval modal",
        "Signals feed, Journal, Settings",
      ],
      commands: "zealous-cliff-099ca950f.6.azurestaticapps.net"
    },
  ];

  channels.forEach((ch, i) => {
    const cx = 0.4 + i * 3.12;
    addCard(s, cx, 1.6, 2.95, 3.75, { accentColor: ch.color });

    s.addText(ch.title, {
      x: cx + 0.2, y: 1.66, w: 2.65, h: 0.38,
      fontSize: 13, bold: true, color: ch.color, fontFace: F.title, margin: 0
    });
    s.addText(ch.deploy, {
      x: cx + 0.2, y: 2.06, w: 2.65, h: 0.24,
      fontSize: 9, color: C.dim, fontFace: F.mono, margin: 0, italic: true
    });
    s.addText(ch.framework, {
      x: cx + 0.2, y: 2.3, w: 2.65, h: 0.24,
      fontSize: 9.5, bold: true, color: C.white, fontFace: F.body, margin: 0
    });

    s.addShape(pres.shapes.LINE, {
      x: cx + 0.2, y: 2.58, w: 2.5, h: 0,
      line: { color: C.border, width: 0.5 }
    });

    ch.features.forEach((f, j) => {
      s.addText([
        { text: "✓ ", options: { color: ch.color, bold: true } },
        { text: f, options: { color: C.muted } }
      ], {
        x: cx + 0.2, y: 2.66 + j * 0.34, w: 2.65, h: 0.3,
        fontSize: 9.5, fontFace: F.body, margin: 0
      });
    });

    s.addShape(pres.shapes.RECTANGLE, {
      x: cx + 0.2, y: 4.9, w: 2.62, h: 0.28,
      fill: { color: C.surface2 }, line: { color: ch.color, width: 0.5 }
    });
    s.addText(ch.commands, {
      x: cx + 0.2, y: 4.9, w: 2.62, h: 0.28,
      fontSize: 7.5, color: ch.color, align: "center", valign: "middle",
      fontFace: F.mono, margin: 0
    });
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 7 — Figma Design Approach
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "Design Process");

  s.addText("Figma Design Approach", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  const steps = [
    {
      num: "1", title: "FigJam Flow Diagram",
      color: C.accent,
      desc: "5 user flows mapped as hub-and-spoke from Dashboard center. Each flow labeled with trigger (click, command) and transition type (slide, modal, drawer).",
      detail: "5 flows: Optimize · Analyze · Alerts · Digest · Settings"
    },
    {
      num: "2", title: "Figma AI Screens",
      color: C.green,
      desc: "6 screens designed using Figma Make AI with detailed prompts. Dark theme #0F1117 throughout. Each screen as an independent frame then wired via Prototype mode.",
      detail: "6 screens: Dashboard · Chat · Trade Approval · Signals · Journal · Settings"
    },
    {
      num: "3", title: "Figma REST API",
      color: C.yellow,
      desc: "Custom Python script fetches the design file via Figma REST API. Extracts colors, typography, frame names and dimensions as a JSON spec file.",
      detail: "tools/figma_spec.py → tools/design-spec.json"
    },
    {
      num: "4", title: "React Build from Spec",
      color: C.mono,
      desc: "Claude Code reads design-spec.json + screen screenshots. Generates React + Tailwind components matching exact hex colors, fonts (Inter + Menlo), and spacing.",
      detail: "stock-copilot-web/ → deployed to Azure Static Web Apps"
    },
  ];

  steps.forEach((st, i) => {
    const cx = 0.4 + i * 2.37;
    addCard(s, cx, 1.4, 2.22, 3.85, { accentColor: st.color });

    s.addShape(pres.shapes.OVAL, {
      x: cx + 0.18, y: 1.48, w: 0.38, h: 0.38,
      fill: { color: st.color }, line: { color: st.color, width: 0 }
    });
    s.addText(st.num, {
      x: cx + 0.18, y: 1.48, w: 0.38, h: 0.38,
      fontSize: 14, bold: true, color: C.white,
      align: "center", valign: "middle", margin: 0
    });
    s.addText(st.title, {
      x: cx + 0.18, y: 1.92, w: 1.9, h: 0.4,
      fontSize: 12, bold: true, color: st.color, fontFace: F.title, margin: 0
    });
    s.addText(st.desc, {
      x: cx + 0.18, y: 2.36, w: 1.92, h: 2.1,
      fontSize: 9, color: C.muted, fontFace: F.body, margin: 0
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: cx + 0.18, y: 4.82, w: 1.92, h: 0.28,
      fill: { color: C.surface2 }, line: { color: st.color, width: 0.5 }
    });
    s.addText(st.detail, {
      x: cx + 0.18, y: 4.82, w: 1.92, h: 0.28,
      fontSize: 7.5, color: st.color, align: "center", valign: "middle",
      fontFace: F.mono, margin: 0
    });

    if (i < steps.length - 1) {
      addArrow(s, cx + 2.22 + 0.04, 1.4 + 3.85 / 2, st.color);
    }
  });

  // Note
  s.addText("Design tokens (colors, typography, spacing) extracted from Figma API and baked into Tailwind config — design changes propagate to code via re-export.", {
    x: 0.4, y: 5.32, w: 9.2, h: 0.24,
    fontSize: 9, color: C.dim, fontFace: F.body, italic: true, margin: 0
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 8 — UI: Dashboard + Chat
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "Web UI Screens");

  s.addText("Web UI — Dashboard & Chat", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  // Dashboard
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 1.28, w: 5.1, h: 4.1,
    fill: { color: C.surface }, line: { color: C.border, width: 0.75 },
    shadow: makeShadow()
  });
  s.addImage({ path: SCREENS.dashboard, x: 0.4, y: 1.28, w: 5.1, h: 4.1 });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 5.08, w: 5.1, h: 0.32,
    fill: { color: C.surface2 }, line: { color: C.border, width: 0.5 }
  });
  s.addText("Dashboard  —  Stats · Positions · Alerts · Quick Actions", {
    x: 0.4, y: 5.08, w: 5.1, h: 0.32,
    fontSize: 9, color: C.muted, align: "center", valign: "middle",
    fontFace: F.body, margin: 0
  });

  // Chat
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.7, y: 1.28, w: 3.9, h: 4.1,
    fill: { color: C.surface }, line: { color: C.border, width: 0.75 },
    shadow: makeShadow()
  });
  s.addImage({ path: SCREENS.chat, x: 5.7, y: 1.28, w: 3.9, h: 4.1 });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.7, y: 5.08, w: 3.9, h: 0.32,
    fill: { color: C.surface2 }, line: { color: C.border, width: 0.5 }
  });
  s.addText("Chat Drawer  —  Agent responses · Live Context panel · Risk status", {
    x: 5.7, y: 5.08, w: 3.9, h: 0.32,
    fontSize: 9, color: C.muted, align: "center", valign: "middle",
    fontFace: F.body, margin: 0
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 9 — UI: Trade Approval + Signals
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "Web UI Screens");

  s.addText("Web UI — Trade Approval & Signals Feed", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 1.28, w: 5.1, h: 4.1,
    fill: { color: C.surface }, line: { color: C.border, width: 0.75 },
    shadow: makeShadow()
  });
  s.addImage({ path: SCREENS.approval, x: 0.4, y: 1.28, w: 5.1, h: 4.1 });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 5.08, w: 5.1, h: 0.32,
    fill: { color: C.surface2 }, line: { color: C.border, width: 0.5 }
  });
  s.addText("Trade Approval Modal  —  Plan table · Verdicts · Approve / Reject", {
    x: 0.4, y: 5.08, w: 5.1, h: 0.32,
    fontSize: 9, color: C.muted, align: "center", valign: "middle",
    fontFace: F.body, margin: 0
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.7, y: 1.28, w: 3.9, h: 4.1,
    fill: { color: C.surface }, line: { color: C.border, width: 0.75 },
    shadow: makeShadow()
  });
  s.addImage({ path: SCREENS.signals, x: 5.7, y: 1.28, w: 3.9, h: 4.1 });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.7, y: 5.08, w: 3.9, h: 0.32,
    fill: { color: C.surface2 }, line: { color: C.border, width: 0.5 }
  });
  s.addText("Signals Feed  —  Buy/Sell signals · RSI · Momentum · Confidence", {
    x: 5.7, y: 5.08, w: 3.9, h: 0.32,
    fontSize: 9, color: C.muted, align: "center", valign: "middle",
    fontFace: F.body, margin: 0
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 10 — UI: Journal + Settings
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "Web UI Screens");

  s.addText("Web UI — Journal & Target Allocation", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 1.28, w: 5.1, h: 4.1,
    fill: { color: C.surface }, line: { color: C.border, width: 0.75 },
    shadow: makeShadow()
  });
  s.addImage({ path: SCREENS.journal, x: 0.4, y: 1.28, w: 5.1, h: 4.1 });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 5.08, w: 5.1, h: 0.32,
    fill: { color: C.surface2 }, line: { color: C.border, width: 0.5 }
  });
  s.addText("Trade Journal  —  P&L stats · Weekly reflection · Closed trades", {
    x: 0.4, y: 5.08, w: 5.1, h: 0.32,
    fontSize: 9, color: C.muted, align: "center", valign: "middle",
    fontFace: F.body, margin: 0
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.7, y: 1.28, w: 3.9, h: 4.1,
    fill: { color: C.surface }, line: { color: C.border, width: 0.75 },
    shadow: makeShadow()
  });
  s.addImage({ path: SCREENS.settings, x: 5.7, y: 1.28, w: 3.9, h: 4.1 });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.7, y: 5.08, w: 3.9, h: 0.32,
    fill: { color: C.surface2 }, line: { color: C.border, width: 0.5 }
  });
  s.addText("Target Allocation  —  Donut chart · Per-ticker sliders · Save & Deploy", {
    x: 5.7, y: 5.08, w: 3.9, h: 0.32,
    fontSize: 9, color: C.muted, align: "center", valign: "middle",
    fontFace: F.body, margin: 0
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 11 — GitHub Actions CI/CD
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "CI/CD Pipeline");

  s.addText("GitHub Actions — Automated Deploy", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  // Two pipelines side by side
  const pipelines = [
    {
      title: "Python API  (deploy-python-api.yml)",
      trigger: "stock-analysis-agent/** · orchestrator/**",
      color: C.green,
      steps: [
        { s: "Checkout",       d: "actions/checkout@v4" },
        { s: "Python 3.11",    d: "setup-python + uv install" },
        { s: "Run Tests",      d: "pytest unit/ + functional/" },
        { s: "Azure Login",    d: "azure/login@v2" },
        { s: "Docker Build",   d: "--platform linux/amd64 → ACR" },
        { s: "Deploy",         d: "az containerapp update" },
        { s: "Health Gate",    d: "Poll revision for 3 min" },
      ]
    },
    {
      title: "Teams Bot  (deploy-bot.yml)",
      trigger: "stock-copilot-agent/**",
      color: C.accent,
      steps: [
        { s: "Checkout",       d: "actions/checkout@v4" },
        { s: "Node 18",        d: "setup-node@v4 + npm ci" },
        { s: "Run Tests",      d: "npm test" },
        { s: "npm build",      d: "TypeScript → dist/" },
        { s: "Azure Login",    d: "azure/login@v2" },
        { s: "Docker Build",   d: "--platform linux/amd64 → ACR" },
        { s: "Deploy",         d: "az containerapp update" },
      ]
    },
  ];

  pipelines.forEach((pl, pi) => {
    const cx = 0.4 + pi * 4.8;

    addCard(s, cx, 1.3, 4.55, 0.52, { accentColor: pl.color, accent: false });
    s.addShape(pres.shapes.RECTANGLE, {
      x: cx, y: 1.3, w: 4.55, h: 0.52,
      fill: { color: C.surface2 }, line: { color: pl.color, width: 1 }
    });
    s.addText(pl.title, {
      x: cx + 0.14, y: 1.34, w: 4.2, h: 0.26,
      fontSize: 10, bold: true, color: pl.color, fontFace: F.mono, margin: 0
    });
    s.addText("Trigger: " + pl.trigger, {
      x: cx + 0.14, y: 1.6, w: 4.2, h: 0.18,
      fontSize: 8, color: C.dim, fontFace: F.mono, margin: 0
    });

    pl.steps.forEach((st, j) => {
      const sy = 2.0 + j * 0.45;
      s.addShape(pres.shapes.RECTANGLE, {
        x: cx + 0.2, y: sy, w: 4.18, h: 0.36,
        fill: { color: j % 2 === 0 ? C.surface : C.surface2 },
        line: { color: C.border, width: 0.5 }
      });
      s.addShape(pres.shapes.OVAL, {
        x: cx + 0.28, y: sy + 0.09, w: 0.18, h: 0.18,
        fill: { color: pl.color }, line: { color: pl.color, width: 0 }
      });
      s.addText(st.s, {
        x: cx + 0.55, y: sy + 0.04, w: 1.2, h: 0.28,
        fontSize: 9.5, bold: true, color: C.white, fontFace: F.body,
        valign: "middle", margin: 0
      });
      s.addText(st.d, {
        x: cx + 1.78, y: sy + 0.04, w: 2.5, h: 0.28,
        fontSize: 9, color: C.muted, fontFace: F.mono,
        valign: "middle", margin: 0
      });
    });
  });

  // Secrets note
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 5.2, w: 9.2, h: 0.28,
    fill: { color: C.surface }, line: { color: C.border, width: 0.5 }
  });
  s.addText("Secrets: AZURE_CREDENTIALS · ACR_NAME · ACR_LOGIN_SERVER stored in GitHub repository secrets — never in code", {
    x: 0.6, y: 5.2, w: 8.8, h: 0.28,
    fontSize: 9, color: C.dim, fontFace: F.body, valign: "middle", italic: true, margin: 0
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 12 — Unit Test Approach
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "Testing");

  s.addText("Unit Test Approach", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  // Stats
  addStat(s, 0.4,  1.3, "17",  "Test Files",    C.accent);
  addStat(s, 2.65, 1.3, "272", "Tests Total",   C.green);
  addStat(s, 4.9,  1.3, "3",   "Test Layers",   C.yellow);
  addStat(s, 7.15, 1.3, "0",   "Mocked I/O",    C.mono);

  // Test categories
  const categories = [
    {
      title: "Unit Tests",
      color: C.green,
      files: [
        "test_risk_agent.py — 4 rules, all verdict paths",
        "test_portfolio_optimizer.py — proposals, critic, cash refinement",
        "test_signal_scorer.py — RSI/MACD/Bollinger/volume scoring",
        "test_scheduler.py — market hours boundary checks",
        "test_memory.py — trade storage, P&L, deduplication",
      ]
    },
    {
      title: "Integration Tests",
      color: C.yellow,
      files: [
        "test_risk_sequence.py — full trading session flow",
        "test_watchlist_monitor.py — signals → risk gate → alerts",
        "test_earnings_agent.py — calendar → scan → deduplication",
        "test_mtf_agent.py — 15m/daily/weekly alignment logic",
        "test_journal_agent.py — close sync, digest, reflection",
      ]
    },
    {
      title: "Functional / API Tests",
      color: C.accent,
      files: [
        "test_api.py — FastAPI endpoints, health checks",
        "test_scan_endpoints.py — /monitor/watchlist/scan routes",
        "test_alert_manager.py — queue, delivery, user filtering",
        "test_watchlist.py — CRUD with isolated SQLite fixture",
        "test_trading_flow.py — end-to-end (marked @integration)",
      ]
    },
  ];

  categories.forEach((cat, i) => {
    const cx = 0.4 + i * 3.12;
    addCard(s, cx, 2.58, 2.95, 2.85, { accentColor: cat.color });
    s.addText(cat.title, {
      x: cx + 0.2, y: 2.64, w: 2.65, h: 0.32,
      fontSize: 12, bold: true, color: cat.color, fontFace: F.title, margin: 0
    });
    cat.files.forEach((f, j) => {
      const parts = f.split(" — ");
      s.addText([
        { text: parts[0], options: { color: C.white, fontFace: F.mono, fontSize: 8.5 } },
        { text: parts[1] ? "  —  " + parts[1] : "", options: { color: C.muted, fontFace: F.body, fontSize: 8.5 } },
      ], {
        x: cx + 0.2, y: 3.02 + j * 0.36, w: 2.65, h: 0.3,
        margin: 0
      });
    });
  });

  // Philosophy
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 5.58, w: 9.2, h: 0.28, // within bounds
    // Intentionally narrow
    fill: { color: C.surface }, line: { color: C.border, width: 0.5 }
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 13 — Roadmap
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();
  addNav(s, "Roadmap");

  s.addText("Planned Capabilities", {
    x: 0.5, y: 0.65, w: 9, h: 0.5,
    fontSize: 26, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  const roadmap = [
    {
      title: "Watchlist Monitor",
      pattern: "Parallel Fan-out + Evaluator-Optimizer",
      desc: "Polls N tickers concurrently via asyncio.gather(). Filters signals through scoring threshold. Pushes proactive Teams alerts. Cron-triggered.",
      color: C.accent
    },
    {
      title: "Earnings Intelligence",
      pattern: "Sequential Pipeline + Iterative Refinement",
      desc: "Fetches earnings calendar → Brave research per ticker → thesis generation via Sonnet. Pre-earnings briefings delivered to Teams.",
      color: C.green
    },
    {
      title: "Multi-Timeframe Analysis",
      pattern: "Parallel Fan-out + Evaluator-Optimizer",
      desc: "Runs RSI/EMA analysis across 15m, daily, weekly simultaneously. Only signals when 2/3 or 3/3 timeframes aligned.",
      color: C.yellow
    },
    {
      title: "Trade Journal + Learning",
      pattern: "Sequential Pipeline + Coordinator-Dispatcher",
      desc: "Triggered on trade close. SQLite schema for all trade metadata. Weekly pattern analysis with lessons surfaced to Teams every Monday.",
      color: C.mono
    },
    {
      title: "Custom Model / RAG",
      pattern: "RAG on trade journal + signal classifier",
      desc: "Fine-tune signal classifier on historical trade outcomes. RAG layer over journal for 'what worked when RSI < 30 on NVDA?' style queries.",
      color: C.red
    },
  ];

  roadmap.forEach((r, i) => {
    const cy = 1.35 + i * 0.82;
    addCard(s, 0.4, cy, 9.2, 0.72, { accentColor: r.color });
    s.addText(r.title, {
      x: 0.62, y: cy + 0.08, w: 2.4, h: 0.28,
      fontSize: 12, bold: true, color: r.color, fontFace: F.title, margin: 0
    });
    s.addText(r.pattern, {
      x: 0.62, y: cy + 0.38, w: 2.4, h: 0.24,
      fontSize: 8.5, color: C.dim, fontFace: F.mono, italic: true, margin: 0
    });
    s.addShape(pres.shapes.LINE, {
      x: 3.2, y: cy + 0.1, w: 0, h: 0.52,
      line: { color: C.border, width: 0.75 }
    });
    s.addText(r.desc, {
      x: 3.38, y: cy + 0.1, w: 6.0, h: 0.55,
      fontSize: 10, color: C.muted, fontFace: F.body, valign: "middle", margin: 0
    });
  });
}


// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 14 — Closing
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.55, h: 5.625,
    fill: { color: C.accent }, line: { color: C.accent, width: 0 }
  });

  s.addText("Stock Copilot", {
    x: 0.9, y: 1.0, w: 9, h: 1.0,
    fontSize: 52, bold: true, color: C.white, fontFace: F.title, margin: 0
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.9, y: 2.1, w: 4.5, h: 0.055,
    fill: { color: C.accent }, line: { color: C.accent, width: 0 }
  });

  const summary = [
    { label: "3 interfaces live",        color: C.accent },
    { label: "6 agent modules deployed", color: C.green  },
    { label: "4 risk safety gates",      color: C.red    },
    { label: "272 automated tests",      color: C.mono   },
    { label: "2 GitHub Actions pipelines", color: C.yellow },
  ];

  summary.forEach((item, i) => {
    s.addShape(pres.shapes.OVAL, {
      x: 0.9, y: 2.32 + i * 0.46, w: 0.16, h: 0.16,
      fill: { color: item.color }, line: { color: item.color, width: 0 }
    });
    s.addText(item.label, {
      x: 1.18, y: 2.28 + i * 0.46, w: 5, h: 0.28,
      fontSize: 14, color: C.white, fontFace: F.body, valign: "middle", margin: 0
    });
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.27, w: 10, h: 0.355,
    fill: { color: C.surface }, line: { color: C.border, width: 0 }
  });
  s.addText("Built with Anthropic Claude · Alpaca Markets · Azure · GitHub Actions · React · Figma", {
    x: 0.6, y: 5.27, w: 9.0, h: 0.355,
    fontSize: 9.5, color: C.dim, fontFace: F.body, valign: "middle", margin: 0
  });
}


// ── Write file ─────────────────────────────────────────────────────────────────
const outPath = path.resolve(__dirname, "../stock-copilot-deck.pptx");
pres.writeFile({ fileName: outPath }).then(() => {
  console.log("✓ Deck written to", outPath);
}).catch(err => {
  console.error("✗ Error:", err.message);
  process.exit(1);
});
