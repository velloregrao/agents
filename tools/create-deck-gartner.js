// create-deck-gartner.js — Stock Copilot Slide Deck (Gartner Template)
// Run: node tools/create-deck-gartner.js

const pptxgen = require("pptxgenjs");
const path    = require("path");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33" x 7.50"
pres.title  = "Stock Copilot — AI-Powered Multi-Agent Trading System";

// ── Gartner Brand Colors (2026 Palette) ───────────────────────────────────
const G = {
  navy:     "002869",  // Gartner Blue — primary
  cobalt:   "0057AF",  // Cobalt
  opal:     "1F96FF",  // Opal — bright accent
  moonstone:"B8DEFF",  // Moonstone — light blue
  crystal:  "E0F1FF",  // Crystal — background tint
  sunstone: "E36135",  // Sunstone — orange highlight
  border:   "707996",  // Border Gray
  onyx:     "00002D",  // Onyx — body text
  white:    "FFFFFF",
  success:  "00A76D",  // Success Green
  error:    "DE0A01",  // Error Red
  warn:     "F5AB23",  // Warning Yellow
  lightbg:  "F0F4FA",  // Light card background
  rule:     "D1D8E8",  // Subtle rule/border
  fogblue:  "E8EEF8",  // Very light navy tint
  navy2:    "003580",  // Slightly lighter navy for variety
};

// Gartner Sans substitutes (system fonts)
const F = { h: "Arial", b: "Arial" };

// ── Layout Constants ──────────────────────────────────────────────────────
const W  = 13.33;
const H  = 7.50;
const ML = 0.45;   // margin left
const MR = 0.45;   // margin right
const CW = W - ML - MR; // 12.43" content width

// ── Asset Paths ───────────────────────────────────────────────────────────
const LOGO_NAVY  = path.resolve(__dirname, "gartner-logo-navy.png");
const LOGO_WHITE = path.resolve(__dirname, "gartner-logo-white.png");

const SCR = {
  dashboard: path.resolve(__dirname, "screens/dashboard.png"),
  chat:      path.resolve(__dirname, "screens/chat.png"),
  approval:  path.resolve(__dirname, "screens/trade-approval.png"),
  signals:   path.resolve(__dirname, "screens/signals.png"),
  journal:   path.resolve(__dirname, "screens/journal.png"),
  settings:  path.resolve(__dirname, "screens/settings.png"),
};

// ── Shared Helpers ────────────────────────────────────────────────────────

function addFooter(s, dark) {
  const col = dark ? "7A9BC4" : G.border;
  s.addText(
    "© 2026 Gartner, Inc. All rights reserved. For internal use only.",
    { x: ML, y: H - 0.27, w: CW - 0.70, h: 0.20,
      fontSize: 6.5, color: col, fontFace: F.b, valign: "middle" }
  );
}

// ── Dark Slide (Navy Background) ──────────────────────────────────────────
function darkSlide() {
  const s = pres.addSlide();
  s.background = { color: G.navy };
  // White Gartner logo — white PNG on dark bg
  s.addImage({ path: LOGO_WHITE, x: ML, y: 0.20, w: 1.50, h: 0.34 });
  addFooter(s, true);
  return s;
}

// ── Light Slide (White Background) ────────────────────────────────────────
function lightSlide(title, subtitle) {
  const s = pres.addSlide();
  s.background = { color: G.white };
  // Navy Gartner logo
  s.addImage({ path: LOGO_NAVY, x: ML, y: 0.16, w: 1.20, h: 0.27 });
  // Title
  if (title) {
    s.addText(title, {
      x: ML, y: 0.55, w: CW, h: 0.52,
      fontSize: 26, bold: true, color: G.navy, fontFace: F.h, valign: "middle",
    });
  }
  if (subtitle) {
    s.addText(subtitle, {
      x: ML, y: 1.04, w: CW, h: 0.28,
      fontSize: 12, color: G.border, fontFace: F.b, italic: true, valign: "middle",
    });
  }
  // Thin cobalt rule spanning full width below title area
  s.addShape(pres.ShapeType.rect, {
    x: ML, y: 1.06, w: CW, h: 0.025,
    fill: { color: G.cobalt }, line: { color: G.cobalt, width: 0 },
  });
  addFooter(s, false);
  return s;
}

// ── Stat Box ─────────────────────────────────────────────────────────────
function statBox(s, x, y, w, h, num, label, accent) {
  s.addShape(pres.ShapeType.rect, {
    x, y, w, h,
    fill: { color: G.fogblue },
    line: { color: G.rule, width: 0.75 },
  });
  // Top accent bar
  s.addShape(pres.ShapeType.rect, {
    x, y, w: w, h: 0.07,
    fill: { color: accent || G.opal }, line: { color: accent || G.opal, width: 0 },
  });
  s.addText(num, {
    x: x + 0.12, y: y + 0.15, w: w - 0.24, h: 0.55,
    fontSize: 36, bold: true, color: G.navy, fontFace: F.h, align: "center",
  });
  s.addText(label, {
    x: x + 0.10, y: y + 0.68, w: w - 0.20, h: 0.36,
    fontSize: 11, color: G.border, fontFace: F.b, align: "center", valign: "top",
  });
}

// ── Content Card (white bg, navy top bar) ─────────────────────────────────
function contentCard(s, x, y, w, h, title, body, badge, badgeColor) {
  // Card background
  s.addShape(pres.ShapeType.rect, {
    x, y, w, h,
    fill: { color: G.white },
    line: { color: G.rule, width: 0.75 },
  });
  // Left accent stripe
  s.addShape(pres.ShapeType.rect, {
    x, y, w: 0.055, h,
    fill: { color: G.cobalt }, line: { color: G.cobalt, width: 0 },
  });
  const tx = x + 0.12;
  const tw = w - 0.22;
  let ty = y + 0.10;
  if (badge) {
    s.addText(badge, {
      x: tx, y: ty, w: tw, h: 0.18,
      fontSize: 7.5, bold: true, color: badgeColor || G.opal, fontFace: F.b,
    });
    ty += 0.20;
  }
  s.addText(title, {
    x: tx, y: ty, w: tw, h: 0.25,
    fontSize: 13, bold: true, color: G.navy, fontFace: F.h,
  });
  ty += 0.26;
  s.addText(body, {
    x: tx, y: ty, w: tw, h: h - (ty - y) - 0.08,
    fontSize: 10.5, color: G.onyx, fontFace: F.b, valign: "top",
  });
}

// ── Numbered Row (for risk gates, process steps) ──────────────────────────
function numberedRow(s, x, y, w, h, num, title, body, verdict, verdictColor) {
  // Background
  s.addShape(pres.ShapeType.rect, {
    x, y, w, h,
    fill: { color: G.fogblue },
    line: { color: G.rule, width: 0.75 },
  });
  // Number circle
  s.addShape(pres.ShapeType.ellipse, {
    x: x + 0.12, y: y + (h - 0.44) / 2, w: 0.44, h: 0.44,
    fill: { color: G.navy }, line: { color: G.navy, width: 0 },
  });
  s.addText(String(num), {
    x: x + 0.12, y: y + (h - 0.44) / 2, w: 0.44, h: 0.44,
    fontSize: 14, bold: true, color: G.white, fontFace: F.h,
    align: "center", valign: "middle",
  });
  // Title
  s.addText(title, {
    x: x + 0.68, y: y + 0.10, w: w - 0.68 - (verdict ? 1.20 : 0.20), h: 0.26,
    fontSize: 13, bold: true, color: G.navy, fontFace: F.h,
  });
  // Body
  s.addText(body, {
    x: x + 0.68, y: y + 0.34, w: w - 0.68 - (verdict ? 1.20 : 0.20), h: h - 0.44,
    fontSize: 10, color: G.onyx, fontFace: F.b, valign: "top",
  });
  // Verdict pill
  if (verdict) {
    const vx = x + w - 1.12;
    const vy = y + (h - 0.26) / 2;
    s.addShape(pres.ShapeType.rect, {
      x: vx, y: vy, w: 0.95, h: 0.26,
      fill: { color: verdictColor || G.opal },
      line: { color: verdictColor || G.opal, width: 0 },
      rectRadius: 0.04,
    });
    s.addText(verdict, {
      x: vx, y: vy, w: 0.95, h: 0.26,
      fontSize: 9, bold: true, color: G.white, fontFace: F.b,
      align: "center", valign: "middle",
    });
  }
}

// ── Pipeline Step (for architecture flow) ────────────────────────────────
function pipeStep(s, x, y, label, sublabel, accent) {
  const bw = 1.62, bh = 0.60;
  s.addShape(pres.ShapeType.rect, {
    x, y, w: bw, h: bh,
    fill: { color: accent || G.navy },
    line: { color: accent || G.navy, width: 0 },
  });
  s.addText(label, {
    x, y: y + 0.03, w: bw, h: 0.30,
    fontSize: 12, bold: true, color: G.white, fontFace: F.h,
    align: "center", valign: "middle",
  });
  if (sublabel) {
    s.addText(sublabel, {
      x, y: y + 0.32, w: bw, h: 0.24,
      fontSize: 8.5, color: G.moonstone, fontFace: F.b,
      align: "center", valign: "middle",
    });
  }
}

function pipeArrow(s, x, y) {
  s.addShape(pres.ShapeType.rect, {
    x, y: y + 0.26, w: 0.26, h: 0.08,
    fill: { color: G.cobalt }, line: { color: G.cobalt, width: 0 },
  });
  s.addText("▶", {
    x: x + 0.16, y: y + 0.18, w: 0.20, h: 0.22,
    fontSize: 10, color: G.cobalt, fontFace: F.b, align: "center",
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 1 — Title
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();

  // Focus frame box (thin bright blue border, Gartner style)
  s.addShape(pres.ShapeType.rect, {
    x: ML, y: 1.70, w: 9.20, h: 3.60,
    fill: { type: "none" },
    line: { color: G.opal, width: 1.0 },
  });

  // Main title
  s.addText("Stock Copilot", {
    x: ML + 0.22, y: 1.95, w: 8.80, h: 1.10,
    fontSize: 48, bold: true, color: G.white, fontFace: F.h,
  });

  // Subtitle
  s.addText("AI-Powered Multi-Agent Trading System", {
    x: ML + 0.22, y: 3.05, w: 8.80, h: 0.55,
    fontSize: 22, color: G.moonstone, fontFace: F.b,
  });

  // Presenter placeholder
  s.addShape(pres.ShapeType.rect, {
    x: ML + 0.22, y: 3.64, w: 5.60, h: 0.44,
    fill: { type: "none" },
    line: { color: G.cobalt, width: 0.75 },
  });
  s.addText("Presenter Name  |  Date", {
    x: ML + 0.32, y: 3.64, w: 5.40, h: 0.44,
    fontSize: 13, color: G.moonstone, fontFace: F.b, valign: "middle",
  });

  // Right-side tag stack
  const tags = [
    { label: "Anthropic Claude",   color: G.cobalt   },
    { label: "Alpaca Markets",     color: "1A6B3C"   },
    { label: "Azure Container",    color: "0078D4"   },
    { label: "React Web UI",       color: "0EA5E9"   },
  ];
  tags.forEach((t, i) => {
    s.addShape(pres.ShapeType.rect, {
      x: 10.50, y: 2.10 + i * 0.72, w: 2.42, h: 0.54,
      fill: { color: t.color },
      line: { color: t.color, width: 0 },
    });
    s.addText(t.label, {
      x: 10.50, y: 2.10 + i * 0.72, w: 2.42, h: 0.54,
      fontSize: 12, bold: true, color: G.white, fontFace: F.h,
      align: "center", valign: "middle",
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 2 — System Overview
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("System Overview", "Stock Copilot at a glance");

  // Stat boxes — row 1
  const stats = [
    { n: "3",   l: "Interface\nChannels",  c: G.cobalt  },
    { n: "6",   l: "Agent\nModules",       c: G.opal    },
    { n: "4",   l: "Risk Safety\nGates",   c: G.sunstone},
    { n: "272", l: "Automated\nTests",     c: G.success },
  ];
  const sw = 2.68, sh = 1.22, sy = 1.30, sgap = 0.32;
  stats.forEach((st, i) => {
    statBox(s, ML + i * (sw + sgap), sy, sw, sh, st.n, st.l, st.c);
  });

  // Channel cards — row 2
  const channels = [
    {
      icon: "💬", title: "Microsoft Teams Bot",
      sub: "Azure Bot Service",
      body: "Natural language commands · Adaptive Cards for trade approvals · Proactive alerts",
    },
    {
      icon: "🖥️", title: "Claude Desktop (MCP)",
      sub: "Model Context Protocol",
      body: "7 MCP tools · Accessible from any device · Full agent capability via chat",
    },
    {
      icon: "🌐", title: "Stock Copilot Web UI",
      sub: "Azure Static Web Apps",
      body: "React + Tailwind dashboard · Live positions · Trade approvals · Signals feed",
    },
    {
      icon: "⚡", title: "Python API (Shared)",
      sub: "Azure Container Apps",
      body: "FastAPI backend · Single source of truth · All channels hit the same Alpaca account",
    },
  ];
  const cw = 2.80, ch = 1.68, cy = 2.76, cgap = 0.28;
  channels.forEach((c, i) => {
    const cx = ML + i * (cw + cgap);
    s.addShape(pres.ShapeType.rect, {
      x: cx, y: cy, w: cw, h: ch,
      fill: { color: G.fogblue },
      line: { color: G.rule, width: 0.75 },
    });
    s.addShape(pres.ShapeType.rect, {
      x: cx, y: cy, w: cw, h: 0.06,
      fill: { color: G.navy }, line: { color: G.navy, width: 0 },
    });
    s.addText(c.title, {
      x: cx + 0.14, y: cy + 0.12, w: cw - 0.28, h: 0.26,
      fontSize: 11.5, bold: true, color: G.navy, fontFace: F.h,
    });
    s.addText(c.sub, {
      x: cx + 0.14, y: cy + 0.36, w: cw - 0.28, h: 0.18,
      fontSize: 9, color: G.cobalt, fontFace: F.b, bold: true,
    });
    s.addText(c.body, {
      x: cx + 0.14, y: cy + 0.55, w: cw - 0.28, h: ch - 0.65,
      fontSize: 9.5, color: G.onyx, fontFace: F.b, valign: "top",
    });
  });

  // Critical rule callout
  s.addShape(pres.ShapeType.rect, {
    x: ML, y: 4.66, w: CW, h: 0.58,
    fill: { color: "FFF3E0" },
    line: { color: G.sunstone, width: 1.0 },
  });
  s.addShape(pres.ShapeType.rect, {
    x: ML, y: 4.66, w: 0.06, h: 0.58,
    fill: { color: G.sunstone }, line: { color: G.sunstone, width: 0 },
  });
  s.addText("Critical Rule: ", {
    x: ML + 0.18, y: 4.72, w: 1.10, h: 0.22,
    fontSize: 10, bold: true, color: G.sunstone, fontFace: F.h,
  });
  s.addText(
    "Every trade proposal MUST pass through orchestrator/risk_agent.evaluate_proposal() before any order is submitted to Alpaca. Never call trade.py directly.",
    { x: ML + 1.28, y: 4.72, w: CW - 1.40, h: 0.44,
      fontSize: 9.5, color: G.onyx, fontFace: F.b, valign: "middle" }
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 3 — Architecture
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("Multi-Agent Architecture", "Request pipeline from user input to order execution");

  // Pipeline row (left side, centered)
  const steps = [
    { l: "User Channel",   sub: "Teams · MCP · Web"  },
    { l: "Router",         sub: "Haiku model"         },
    { l: "Risk Agent",     sub: "4 rules · Critic"    },
    { l: "Analysis Agent", sub: "Sonnet · RSI/EMA"    },
    { l: "Trade Execution",sub: "Alpaca Markets"      },
  ];

  const stepW = 1.62, stepH = 0.60;
  const arrowW = 0.32;
  const totalW = steps.length * stepW + (steps.length - 1) * arrowW;
  const startX = (W - totalW) / 2;
  const pipeY = 1.40;

  steps.forEach((st, i) => {
    const x = startX + i * (stepW + arrowW);
    const accent = i === 0 ? G.cobalt : i === 2 ? G.sunstone : G.navy;
    pipeStep(s, x, pipeY, st.l, st.sub, accent);
    if (i < steps.length - 1) {
      pipeArrow(s, x + stepW, pipeY);
    }
  });

  // 4 component detail cards below
  const cards = [
    {
      file: "orchestrator/router.py",
      title: "Router / Dispatcher",
      body: "Haiku for routing (fast & cheap) · Regex fallback classification · Returns requires_approval flag · Dispatches to specialist agents",
    },
    {
      file: "orchestrator/risk_agent.py",
      title: "Risk Agent (Critic)",
      body: "APPROVED / RESIZE / BLOCK / ESCALATE · Runs BEFORE every trade · Iterative: RESIZE triggers re-run · Posts Teams card on ESCALATE",
    },
    {
      file: "stock-analysis-agent/",
      title: "Analysis Agent",
      body: "RSI, EMA, VWAP, Momentum scoring · Brave Search for news sentiment · Sonnet for thesis generation · Multi-timeframe support (planned)",
    },
    {
      file: "orchestrator/portfolio_optimizer.py",
      title: "Portfolio Optimizer",
      body: "Iterative refinement pattern · Propose → Critique → Refine · Accounts for pending orders · Requires human approval via Teams",
    },
  ];

  const cdW = 2.85, cdH = 2.28, cdY = 2.26, cdGap = 0.22;
  cards.forEach((c, i) => {
    const cx = ML + i * (cdW + cdGap);
    s.addShape(pres.ShapeType.rect, {
      x: cx, y: cdY, w: cdW, h: cdH,
      fill: { color: G.fogblue },
      line: { color: G.rule, width: 0.75 },
    });
    s.addShape(pres.ShapeType.rect, {
      x: cx, y: cdY, w: cdW, h: 0.055,
      fill: { color: G.navy }, line: { color: G.navy, width: 0 },
    });
    s.addText(c.file, {
      x: cx + 0.12, y: cdY + 0.10, w: cdW - 0.24, h: 0.20,
      fontSize: 8, color: G.cobalt, fontFace: "Courier New", bold: true,
    });
    s.addText(c.title, {
      x: cx + 0.12, y: cdY + 0.28, w: cdW - 0.24, h: 0.30,
      fontSize: 12.5, bold: true, color: G.navy, fontFace: F.h,
    });
    // Bullet points
    c.body.split(" · ").forEach((bullet, bi) => {
      s.addText("› " + bullet, {
        x: cx + 0.12, y: cdY + 0.60 + bi * 0.40, w: cdW - 0.24, h: 0.38,
        fontSize: 9.5, color: G.onyx, fontFace: F.b, valign: "top",
      });
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 4 — Agent Design Patterns
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("Agent Design Patterns", "Patterns in use today, and planned for the next phase");

  const patterns = [
    {
      status: "LIVE", statusColor: G.success,
      title: "Generator + Critic",
      file:  "risk_agent.py",
      body:  "Analysis agent proposes a trade. Risk agent critiques and vetoes or resizes before execution. No trade bypasses this gate.",
    },
    {
      status: "LIVE", statusColor: G.success,
      title: "Sequential Pipeline",
      file:  "router.py",
      body:  "Signal → risk check → execution. Strict ordering enforced. No step can be skipped or short-circuited.",
    },
    {
      status: "LIVE", statusColor: G.success,
      title: "Human-in-the-Loop",
      file:  "Teams Adaptive Cards",
      body:  "ESCALATE and BLOCK verdicts send approval cards. No trade executes without explicit human sign-off in Teams.",
    },
    {
      status: "LIVE", statusColor: G.success,
      title: "Iterative Refinement",
      file:  "portfolio_optimizer.py",
      body:  "Portfolio optimizer proposes → risk critic resizes → re-runs until all positions are within risk limits.",
    },
    {
      status: "LIVE", statusColor: G.success,
      title: "Coordinator / Dispatcher",
      file:  "router.py",
      body:  "Single natural language entry point routes all commands to specialist agents by intent classification.",
    },
    {
      status: "PLANNED", statusColor: G.sunstone,
      title: "Parallel Fan-out",
      file:  "Watchlist monitor",
      body:  "asyncio.gather() scans N tickers concurrently. Signals filtered through scoring threshold before alert.",
    },
  ];

  const cw = 3.82, ch = 1.82, gap = 0.18;
  const rowY = [1.28, 3.20];

  patterns.forEach((p, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const cx = ML + col * (cw + gap);
    const cy = rowY[row];

    s.addShape(pres.ShapeType.rect, {
      x: cx, y: cy, w: cw, h: ch,
      fill: { color: G.white },
      line: { color: G.rule, width: 0.75 },
    });
    // Left accent stripe
    s.addShape(pres.ShapeType.rect, {
      x: cx, y: cy, w: 0.055, h: ch,
      fill: { color: G.cobalt }, line: { color: G.cobalt, width: 0 },
    });

    const tx = cx + 0.16;
    const tw = cw - 0.26;

    // Status badge
    s.addText(p.status, {
      x: tx, y: cy + 0.10, w: 0.72, h: 0.20,
      fontSize: 7.5, bold: true, color: p.statusColor, fontFace: F.b,
    });
    // File/module tag
    s.addText(p.file, {
      x: tx + 0.72, y: cy + 0.10, w: tw - 0.72, h: 0.20,
      fontSize: 8, color: G.border, fontFace: "Courier New",
    });
    // Title
    s.addText(p.title, {
      x: tx, y: cy + 0.30, w: tw, h: 0.28,
      fontSize: 13, bold: true, color: G.navy, fontFace: F.h,
    });
    // Body
    s.addText(p.body, {
      x: tx, y: cy + 0.58, w: tw, h: ch - 0.68,
      fontSize: 10, color: G.onyx, fontFace: F.b, valign: "top",
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 5 — Risk Agent
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("Risk Agent — 4 Safety Gates", "Every trade proposal passes all 4 rules in sequence before execution");

  const gates = [
    {
      num: "01", title: "Daily Loss Circuit Breaker",
      config: "RISK_DAILY_LOSS_HALT = -2%",
      body: "Halts ALL trading for the day if portfolio is down more than 2%. Protects against runaway losses in volatile markets.",
      verdict: "BLOCK", vc: G.error,
    },
    {
      num: "02", title: "Position Size Limit",
      config: "RISK_MAX_POSITION_PCT = 5%",
      body: "No single position may exceed 5% of total equity. If proposed qty is too large, auto-resizes to the maximum allowed.",
      verdict: "RESIZE", vc: G.warn,
    },
    {
      num: "03", title: "Sector Concentration",
      config: "RISK_MAX_SECTOR_CONC_PCT = 25%",
      body: "No single GICS sector may exceed 25% of equity. Prevents over-exposure to tech, energy, or any single sector.",
      verdict: "ESCALATE", vc: G.cobalt,
    },
    {
      num: "04", title: "Correlation Guard",
      config: "Known pairs: NVDA↔AMD, etc.",
      body: "Escalates if the proposed ticker is in a known correlated pair with a currently held position. Avoids doubling correlated risk.",
      verdict: "ESCALATE", vc: G.cobalt,
    },
  ];

  const gh = 1.16, gy0 = 1.26, ggap = 0.14;

  gates.forEach((g, i) => {
    const gy = gy0 + i * (gh + ggap);
    s.addShape(pres.ShapeType.rect, {
      x: ML, y: gy, w: CW, h: gh,
      fill: { color: G.fogblue },
      line: { color: G.rule, width: 0.75 },
    });

    // Number badge
    s.addShape(pres.ShapeType.rect, {
      x: ML, y: gy, w: 0.72, h: gh,
      fill: { color: G.navy }, line: { color: G.navy, width: 0 },
    });
    s.addText(g.num, {
      x: ML, y: gy, w: 0.72, h: gh,
      fontSize: 18, bold: true, color: G.white, fontFace: F.h,
      align: "center", valign: "middle",
    });

    // Config pill
    s.addShape(pres.ShapeType.rect, {
      x: ML + 0.82, y: gy + 0.08, w: 2.40, h: 0.26,
      fill: { color: G.crystal },
      line: { color: G.moonstone, width: 0.5 },
    });
    s.addText(g.config, {
      x: ML + 0.82, y: gy + 0.08, w: 2.40, h: 0.26,
      fontSize: 9, bold: true, color: G.cobalt, fontFace: "Courier New",
      align: "center", valign: "middle",
    });

    // Title
    s.addText(g.title, {
      x: ML + 3.34, y: gy + 0.08, w: 6.80, h: 0.30,
      fontSize: 13, bold: true, color: G.navy, fontFace: F.h,
    });

    // Body
    s.addText(g.body, {
      x: ML + 0.82, y: gy + 0.40, w: 9.32, h: gh - 0.50,
      fontSize: 10, color: G.onyx, fontFace: F.b, valign: "top",
    });

    // Verdict pill
    s.addShape(pres.ShapeType.rect, {
      x: ML + CW - 1.14, y: gy + (gh - 0.30) / 2, w: 1.04, h: 0.30,
      fill: { color: g.vc }, line: { color: g.vc, width: 0 },
    });
    s.addText(g.verdict, {
      x: ML + CW - 1.14, y: gy + (gh - 0.30) / 2, w: 1.04, h: 0.30,
      fontSize: 9, bold: true, color: G.white, fontFace: F.b,
      align: "center", valign: "middle",
    });
  });

  // Verdict legend
  const verdicts = [
    { v: "APPROVED", c: G.success, d: "Execute as proposed"   },
    { v: "RESIZE",   c: G.warn,    d: "Auto-adjust qty, retry"},
    { v: "BLOCK",    c: G.error,   d: "Do not execute"         },
    { v: "ESCALATE", c: G.cobalt,  d: "Require human approval" },
  ];
  const vW = 2.80;
  verdicts.forEach((v, i) => {
    const vx = ML + i * (vW + 0.20);
    s.addShape(pres.ShapeType.rect, {
      x: vx, y: 5.96, w: vW, h: 0.28,
      fill: { color: v.c }, line: { color: v.c, width: 0 },
    });
    s.addText(v.v, {
      x: vx, y: 5.96, w: 0.90, h: 0.28,
      fontSize: 9, bold: true, color: G.white, fontFace: F.b,
      align: "center", valign: "middle",
    });
    s.addText(v.d, {
      x: vx + 0.94, y: 5.96, w: vW - 0.98, h: 0.28,
      fontSize: 9, color: G.white, fontFace: F.b, valign: "middle",
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 6 — Interface Channels
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("Three Interface Channels", "All channels share the same Python API, Alpaca account, and risk gate");

  const channels = [
    {
      title: "Microsoft Teams Bot",
      deploy: "Azure Bot Service + Azure Container Apps",
      bullets: [
        "Natural language trading commands",
        "Adaptive Cards for trade approvals",
        "Proactive alerts (signals, earnings)",
        "Inline rebalance approve/reject flow",
      ],
      commands: "Analyze · News · Portfolio · Optimize · Digest",
      color: G.cobalt,
    },
    {
      title: "Claude Desktop (MCP)",
      deploy: "Local MCP Server · 7 Tools",
      bullets: [
        "Full agent capability via Claude chat",
        "target_allocation, optimize_portfolio",
        "earnings_analysis, mtf_analysis",
        "Accessible from desktop and mobile",
      ],
      commands: "7 registered MCP tools",
      color: "5B4FB5",
    },
    {
      title: "Stock Copilot Web UI",
      deploy: "Azure Static Web Apps · React + Vite",
      bullets: [
        "Live portfolio dashboard",
        "Chat drawer → agent commands",
        "Trade approval modal",
        "Signals, Journal, Settings tabs",
      ],
      commands: "zealous-cliff-099ca950f.6.azurestaticapps.net",
      color: G.navy,
    },
  ];

  const cw = 3.82, ch = 4.62, cy = 1.30, gap = 0.23;

  channels.forEach((ch_, i) => {
    const cx = ML + i * (cw + gap);

    // Card
    s.addShape(pres.ShapeType.rect, {
      x: cx, y: cy, w: cw, h: ch,
      fill: { color: G.white },
      line: { color: G.rule, width: 0.75 },
    });
    // Header bar
    s.addShape(pres.ShapeType.rect, {
      x: cx, y: cy, w: cw, h: 0.72,
      fill: { color: ch_.color }, line: { color: ch_.color, width: 0 },
    });
    s.addText(ch_.title, {
      x: cx + 0.16, y: cy + 0.04, w: cw - 0.32, h: 0.40,
      fontSize: 14, bold: true, color: G.white, fontFace: F.h, valign: "middle",
    });
    s.addText(ch_.deploy, {
      x: cx + 0.16, y: cy + 0.44, w: cw - 0.32, h: 0.22,
      fontSize: 8.5, color: G.moonstone, fontFace: F.b,
    });

    // Bullet points
    ch_.bullets.forEach((b, bi) => {
      const by = cy + 0.84 + bi * 0.60;
      s.addShape(pres.ShapeType.ellipse, {
        x: cx + 0.16, y: by + 0.09, w: 0.10, h: 0.10,
        fill: { color: ch_.color }, line: { color: ch_.color, width: 0 },
      });
      s.addText(b, {
        x: cx + 0.34, y: by, w: cw - 0.50, h: 0.50,
        fontSize: 11, color: G.onyx, fontFace: F.b, valign: "top",
      });
    });

    // Command tag at bottom
    s.addShape(pres.ShapeType.rect, {
      x: cx + 0.16, y: cy + ch - 0.42, w: cw - 0.32, h: 0.30,
      fill: { color: G.crystal },
      line: { color: G.moonstone, width: 0.5 },
    });
    s.addText(ch_.commands, {
      x: cx + 0.16, y: cy + ch - 0.42, w: cw - 0.32, h: 0.30,
      fontSize: 8.5, color: G.cobalt, fontFace: "Courier New",
      align: "center", valign: "middle",
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 7 — Figma Design Process
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("Figma Design Approach", "From user flow diagrams to production React components");

  const steps = [
    {
      num: "1",
      title: "FigJam Flow Diagram",
      sub: "User flows mapped before screens",
      body: "5 user flows mapped as a hub-and-spoke diagram from a central Dashboard. Each flow labeled with trigger (click, command) and transition destination.\n\n5 flows: Optimize · Analyze · Alerts · Digest · Settings",
      icon: "🗺",
    },
    {
      num: "2",
      title: "Figma AI Screens",
      sub: "6 screens via Figma Make AI",
      body: "Screens designed using Figma Make with detailed prompts specifying dark theme (#0F1117), exact hex colors, Inter + Menlo fonts, and Alpaca data shapes.\n\n6 screens: Dashboard · Chat · Trade Approval · Signals · Journal · Settings",
      icon: "🎨",
    },
    {
      num: "3",
      title: "Figma REST API",
      sub: "Design spec extraction",
      body: "Custom Python script (tools/figma_spec.py) fetches the design file via Figma REST API. Extracts colors, typography, frame names, dimensions.\n\nOutput: tools/design-spec.json + 6 screen PNGs",
      icon: "⚙️",
    },
    {
      num: "4",
      title: "React Build from Spec",
      sub: "Code generation from design tokens",
      body: "Claude Code reads design-spec.json + screen screenshots. Generates React + Tailwind components matching exact hex colors and layout.\n\nDeployed to: Azure Static Web Apps",
      icon: "⚛",
    },
  ];

  const sw = 2.76, sh = 4.30, sy = 1.30, sgap = 0.24;

  steps.forEach((st, i) => {
    const sx = ML + i * (sw + sgap);

    // Card
    s.addShape(pres.ShapeType.rect, {
      x: sx, y: sy, w: sw, h: sh,
      fill: { color: G.white },
      line: { color: G.rule, width: 0.75 },
    });

    // Number circle
    s.addShape(pres.ShapeType.ellipse, {
      x: sx + (sw - 0.58) / 2, y: sy + 0.18, w: 0.58, h: 0.58,
      fill: { color: G.navy }, line: { color: G.navy, width: 0 },
    });
    s.addText(st.num, {
      x: sx + (sw - 0.58) / 2, y: sy + 0.18, w: 0.58, h: 0.58,
      fontSize: 20, bold: true, color: G.white, fontFace: F.h,
      align: "center", valign: "middle",
    });

    // Title
    s.addText(st.title, {
      x: sx + 0.14, y: sy + 0.90, w: sw - 0.28, h: 0.36,
      fontSize: 12.5, bold: true, color: G.navy, fontFace: F.h, align: "center",
    });
    s.addText(st.sub, {
      x: sx + 0.14, y: sy + 1.24, w: sw - 0.28, h: 0.22,
      fontSize: 9, color: G.cobalt, fontFace: F.b, align: "center", bold: true,
    });

    // Divider
    s.addShape(pres.ShapeType.rect, {
      x: sx + 0.40, y: sy + 1.50, w: sw - 0.80, h: 0.022,
      fill: { color: G.rule }, line: { color: G.rule, width: 0 },
    });

    // Body
    s.addText(st.body, {
      x: sx + 0.14, y: sy + 1.58, w: sw - 0.28, h: sh - 1.72,
      fontSize: 9.5, color: G.onyx, fontFace: F.b, valign: "top",
    });

    // Connector arrow between steps
    if (i < steps.length - 1) {
      s.addText("→", {
        x: sx + sw + 0.02, y: sy + sh / 2 - 0.14, w: sgap - 0.04, h: 0.28,
        fontSize: 16, color: G.cobalt, fontFace: F.h, align: "center",
      });
    }
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 8 — UI Screens: Dashboard & Chat
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("Web UI — Dashboard & Chat", "Built from Figma design spec using React + Tailwind CSS");

  const imgs = [
    { path: SCR.dashboard, title: "Dashboard", desc: "Portfolio stats · Positions · Alerts · Quick Actions" },
    { path: SCR.chat,      title: "Chat Drawer", desc: "Agent responses · Live Context panel · Risk status" },
  ];

  const imgH = 4.20, imgY = 1.22;
  const w1 = 7.10, w2 = 5.00, gap = 0.28;

  imgs.forEach((img, i) => {
    const iw = i === 0 ? w1 : w2;
    const ix = i === 0 ? ML : ML + w1 + gap;

    s.addShape(pres.ShapeType.rect, {
      x: ix, y: imgY, w: iw, h: imgH,
      fill: { color: "0F1117" },
      line: { color: G.rule, width: 0.75 },
    });
    s.addImage({ path: img.path, x: ix, y: imgY, w: iw, h: imgH });
    s.addText(img.title, {
      x: ix, y: imgY + imgH + 0.06, w: iw, h: 0.24,
      fontSize: 11.5, bold: true, color: G.navy, fontFace: F.h,
    });
    s.addText(img.desc, {
      x: ix, y: imgY + imgH + 0.28, w: iw, h: 0.20,
      fontSize: 9.5, color: G.border, fontFace: F.b,
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 9 — UI Screens: Trade Approval & Signals
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("Web UI — Trade Approval & Signals Feed", "Built from Figma design spec using React + Tailwind CSS");

  const imgs = [
    { path: SCR.approval, title: "Trade Approval Modal", desc: "Rebalance plan table · Risk verdicts · Approve / Reject" },
    { path: SCR.signals,  title: "Signals Feed",         desc: "Buy/Sell signals · RSI · Momentum · Confidence score" },
  ];

  const imgH = 4.20, imgY = 1.22;
  const w1 = 7.10, w2 = 5.00, gap = 0.28;

  imgs.forEach((img, i) => {
    const iw = i === 0 ? w1 : w2;
    const ix = i === 0 ? ML : ML + w1 + gap;

    s.addShape(pres.ShapeType.rect, {
      x: ix, y: imgY, w: iw, h: imgH,
      fill: { color: "0F1117" },
      line: { color: G.rule, width: 0.75 },
    });
    s.addImage({ path: img.path, x: ix, y: imgY, w: iw, h: imgH });
    s.addText(img.title, {
      x: ix, y: imgY + imgH + 0.06, w: iw, h: 0.24,
      fontSize: 11.5, bold: true, color: G.navy, fontFace: F.h,
    });
    s.addText(img.desc, {
      x: ix, y: imgY + imgH + 0.28, w: iw, h: 0.20,
      fontSize: 9.5, color: G.border, fontFace: F.b,
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 10 — UI Screens: Journal & Settings
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("Web UI — Trade Journal & Target Allocation", "Built from Figma design spec using React + Tailwind CSS");

  const imgs = [
    { path: SCR.journal,  title: "Trade Journal",       desc: "P&L stats · Weekly AI reflection · Closed trade history" },
    { path: SCR.settings, title: "Target Allocation",   desc: "Donut chart · Per-ticker sliders · Save & Deploy" },
  ];

  const imgH = 4.20, imgY = 1.22;
  const w1 = 7.10, w2 = 5.00, gap = 0.28;

  imgs.forEach((img, i) => {
    const iw = i === 0 ? w1 : w2;
    const ix = i === 0 ? ML : ML + w1 + gap;

    s.addShape(pres.ShapeType.rect, {
      x: ix, y: imgY, w: iw, h: imgH,
      fill: { color: "0F1117" },
      line: { color: G.rule, width: 0.75 },
    });
    s.addImage({ path: img.path, x: ix, y: imgY, w: iw, h: imgH });
    s.addText(img.title, {
      x: ix, y: imgY + imgH + 0.06, w: iw, h: 0.24,
      fontSize: 11.5, bold: true, color: G.navy, fontFace: F.h,
    });
    s.addText(img.desc, {
      x: ix, y: imgY + imgH + 0.28, w: iw, h: 0.20,
      fontSize: 9.5, color: G.border, fontFace: F.b,
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 11 — GitHub Actions CI/CD
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("GitHub Actions — Automated Deploy", "Path-filtered triggers: each component deploys independently on change");

  const pipelines = [
    {
      title: "Python API  (deploy-python-api.yml)",
      trigger: "Trigger: stock-analysis-agent/**  ·  orchestrator/**",
      steps: [
        { label: "Checkout",     sub: "actions/checkout@v4" },
        { label: "Python 3.11",  sub: "setup-python + uv"   },
        { label: "Run Tests",    sub: "pytest unit/ + func/" },
        { label: "Azure Login",  sub: "azure/login@v2"       },
        { label: "Docker Build", sub: "→ ACR linux/amd64"    },
        { label: "Deploy",       sub: "az containerapp update"},
        { label: "Health Gate",  sub: "Poll 3 min"           },
      ],
    },
    {
      title: "Teams Bot  (deploy-bot.yml)",
      trigger: "Trigger: stock-copilot-agent/**",
      steps: [
        { label: "Checkout",     sub: "actions/checkout@v4" },
        { label: "Node 18",      sub: "setup-node + npm ci" },
        { label: "Run Tests",    sub: "npm test"            },
        { label: "npm build",    sub: "TypeScript → dist/"  },
        { label: "Azure Login",  sub: "azure/login@v2"      },
        { label: "Docker Build", sub: "→ ACR linux/amd64"   },
        { label: "Deploy",       sub: "az containerapp update"},
      ],
    },
  ];

  const pH = 4.76, pW = 5.82, pgap = 0.76;

  pipelines.forEach((pipe, pi) => {
    const px = ML + pi * (pW + pgap);
    const py = 1.28;

    // Pipeline container
    s.addShape(pres.ShapeType.rect, {
      x: px, y: py, w: pW, h: pH,
      fill: { color: G.fogblue },
      line: { color: G.rule, width: 0.75 },
    });
    s.addShape(pres.ShapeType.rect, {
      x: px, y: py, w: pW, h: 0.055,
      fill: { color: G.navy }, line: { color: G.navy, width: 0 },
    });

    // Title
    s.addText(pipe.title, {
      x: px + 0.16, y: py + 0.10, w: pW - 0.32, h: 0.28,
      fontSize: 11.5, bold: true, color: G.navy, fontFace: F.h,
    });
    s.addText(pipe.trigger, {
      x: px + 0.16, y: py + 0.36, w: pW - 0.32, h: 0.20,
      fontSize: 8.5, color: G.cobalt, fontFace: "Courier New",
    });

    // Steps
    const stepH = 0.46, stepY0 = py + 0.66, stepGap = 0.06;
    const stepW = (pW - 0.40 - (pipe.steps.length - 1) * (0.22 + 0.16)) / pipe.steps.length;

    pipe.steps.forEach((st, si) => {
      const sx = px + 0.20 + si * (stepW + 0.22 + 0.16);
      s.addShape(pres.ShapeType.rect, {
        x: sx, y: stepY0, w: stepW, h: stepH,
        fill: { color: G.navy }, line: { color: G.navy, width: 0 },
      });
      s.addText(st.label, {
        x: sx, y: stepY0 + 0.02, w: stepW, h: 0.22,
        fontSize: 8, bold: true, color: G.white, fontFace: F.h,
        align: "center", valign: "middle",
      });
      s.addText(st.sub, {
        x: sx, y: stepY0 + 0.23, w: stepW, h: 0.20,
        fontSize: 6.5, color: G.moonstone, fontFace: F.b,
        align: "center", valign: "middle",
      });
      // Connector arrow
      if (si < pipe.steps.length - 1) {
        s.addText("›", {
          x: sx + stepW + 0.02, y: stepY0 + 0.10, w: 0.18, h: 0.28,
          fontSize: 12, color: G.cobalt, fontFace: F.h, align: "center",
        });
      }
    });

    // Second-row details
    s.addText("Model Tiering:", {
      x: px + 0.16, y: py + 1.30, w: 1.20, h: 0.22,
      fontSize: 9.5, bold: true, color: G.navy, fontFace: F.h,
    });
    s.addText(pi === 0
      ? "Haiku (routing/classification)  ·  Sonnet (analysis, thesis, narrative)"
      : "TypeScript bot  ·  Adaptive Cards for trade approvals and alerts",
      { x: px + 1.38, y: py + 1.30, w: pW - 1.54, h: 0.22,
        fontSize: 9.5, color: G.onyx, fontFace: F.b }
    );

    // Secrets note
    s.addShape(pres.ShapeType.rect, {
      x: px + 0.16, y: py + 1.60, w: pW - 0.32, h: pi === 0 ? 2.86 : 2.86,
      fill: { color: G.white },
      line: { color: G.rule, width: 0.5 },
    });

    const detailLines = pi === 0 ? [
      "pytest covers: risk_agent · portfolio_optimizer · signal_scorer",
      "pytest covers: scheduler · memory · watchlist · API endpoints",
      "",
      "Secrets stored in GitHub repository secrets:",
      "AZURE_CREDENTIALS  ·  ACR_NAME  ·  ACR_LOGIN_SERVER",
      "ALPACA_API_KEY  ·  ALPACA_API_SECRET  ·  ANTHROPIC_API_KEY",
    ] : [
      "npm test covers: bot routing · card rendering · intent mapping",
      "",
      "Web UI (deploy-web.yml):",
      "Trigger: stock-copilot-web/**",
      "Steps: npm ci → npm build → az staticwebapp deploy",
      "Auto-configured VITE_API_URL + VITE_API_KEY from secrets",
    ];

    detailLines.forEach((line, li) => {
      if (!line) return;
      s.addText(line, {
        x: px + 0.28, y: py + 1.72 + li * 0.40, w: pW - 0.56, h: 0.36,
        fontSize: 9, color: G.onyx, fontFace: line.includes(":") && !line.includes("·") ? F.h : F.b,
        bold: line.endsWith(":"),
      });
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 12 — Unit Test Approach
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("Unit Test Approach", "Three test layers — zero mocked I/O; all tests hit real code paths");

  // Stat row
  const stats = [
    { n: "17",  l: "Test\nFiles",  c: G.cobalt   },
    { n: "272", l: "Tests\nTotal", c: G.navy      },
    { n: "3",   l: "Test\nLayers", c: G.opal      },
    { n: "0",   l: "Mocked\nI/O",  c: G.success   },
  ];
  const sw = 2.68, sh = 1.20, sy = 1.28, sgap = 0.34;
  stats.forEach((st, i) => statBox(s, ML + i * (sw + sgap), sy, sw, sh, st.n, st.l, st.c));

  // Three test layer columns
  const layers = [
    {
      title: "Unit Tests",
      color: G.cobalt,
      tests: [
        "test_risk_agent.py — 4 rules, all verdict paths",
        "test_portfolio_optimizer.py — proposals, critic",
        "test_signal_scorer.py — RSI/MACD/Bollinger",
        "test_scheduler.py — market hours boundaries",
        "test_memory.py — trade storage, P&L, dedup",
      ],
    },
    {
      title: "Integration Tests",
      color: G.navy,
      tests: [
        "test_risk_sequence.py — full session flow",
        "test_watchlist_monitor.py — signals → risk → alerts",
        "test_earnings_agent.py — calendar → scan → dedup",
        "test_mtf_agent.py — 15m/daily/weekly alignment",
        "test_journal_agent.py — close sync, digest",
      ],
    },
    {
      title: "Functional / API Tests",
      color: G.opal,
      tests: [
        "test_api.py — FastAPI endpoints, health checks",
        "test_scan_endpoints.py — /monitor/watchlist/scan",
        "test_alert_manager.py — queue, delivery, filter",
        "test_watchlist.py — CRUD + isolated SQLite fixture",
        "test_trading_flow.py — E2E (@integration marked)",
      ],
    },
  ];

  const lw = 3.82, lh = 3.12, ly = 2.62, lgap = 0.23;

  layers.forEach((layer, i) => {
    const lx = ML + i * (lw + lgap);

    s.addShape(pres.ShapeType.rect, {
      x: lx, y: ly, w: lw, h: lh,
      fill: { color: G.white },
      line: { color: G.rule, width: 0.75 },
    });
    s.addShape(pres.ShapeType.rect, {
      x: lx, y: ly, w: lw, h: 0.40,
      fill: { color: layer.color }, line: { color: layer.color, width: 0 },
    });
    s.addText(layer.title, {
      x: lx + 0.14, y: ly, w: lw - 0.28, h: 0.40,
      fontSize: 13, bold: true, color: G.white, fontFace: F.h, valign: "middle",
    });

    layer.tests.forEach((t, ti) => {
      const [fname, ...rest] = t.split(" — ");
      s.addText(fname, {
        x: lx + 0.14, y: ly + 0.48 + ti * 0.50, w: lw - 0.28, h: 0.22,
        fontSize: 9.5, bold: true, color: G.navy, fontFace: "Courier New",
      });
      if (rest.length) {
        s.addText(rest.join(" — "), {
          x: lx + 0.14, y: ly + 0.68 + ti * 0.50, w: lw - 0.28, h: 0.20,
          fontSize: 9, color: G.onyx, fontFace: F.b,
        });
      }
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 13 — Roadmap
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = lightSlide("Planned Capabilities", "Next agent modules — patterns and implementation notes defined in CLAUDE.md");

  const items = [
    {
      title: "Watchlist Monitor Agent",
      pattern: "Parallel Fan-out + Evaluator-Optimizer",
      body: "asyncio.gather() scans N tickers concurrently. Signals filtered through scoring threshold. Pushes proactive Teams alerts when signals clear all gates. Cron/scheduled trigger.",
      color: G.cobalt,
    },
    {
      title: "Earnings Intelligence Agent",
      pattern: "Sequential Pipeline + Iterative Refinement",
      body: "Fetches earnings calendar → Brave research per ticker → thesis generation via Sonnet. Pre-earnings briefings delivered to Teams the morning before each event.",
      color: G.navy,
    },
    {
      title: "Multi-Timeframe Analysis Agent",
      pattern: "Parallel Fan-out + Evaluator-Optimizer",
      body: "Runs RSI/EMA analysis across 15m, daily, weekly simultaneously. Only signals when 2/3 or 3/3 timeframes aligned. Uses TimeFrame.Minute with 15-unit intervals.",
      color: G.opal,
    },
    {
      title: "Trade Journal + Learning Agent",
      pattern: "Sequential Pipeline + Coordinator-Dispatcher",
      body: "Triggered on every trade close. SQLite schema for all trade metadata including thesis and outcome P&L. Weekly pattern analysis surfaced to Teams digest.",
      color: "5A798C",
    },
    {
      title: "Custom Signal Classifier + RAG",
      pattern: "RAG over trade journal",
      body: "Fine-tune signal classifier on historical outcomes. RAG layer answers 'what worked when RSI < 30 on NVDA?' Feeds back into analysis agent prompts.",
      color: "9673BE",
    },
  ];

  const rh = 0.96, ry0 = 1.30, rgap = 0.10;

  items.forEach((item, i) => {
    const ry = ry0 + i * (rh + rgap);

    s.addShape(pres.ShapeType.rect, {
      x: ML, y: ry, w: CW, h: rh,
      fill: { color: G.white },
      line: { color: G.rule, width: 0.75 },
    });
    // Left color bar
    s.addShape(pres.ShapeType.rect, {
      x: ML, y: ry, w: 0.30, h: rh,
      fill: { color: item.color }, line: { color: item.color, width: 0 },
    });

    // Index number
    s.addText(String(i + 1), {
      x: ML, y: ry, w: 0.30, h: rh,
      fontSize: 12, bold: true, color: G.white, fontFace: F.h,
      align: "center", valign: "middle",
    });

    // Title + pattern
    s.addText(item.title, {
      x: ML + 0.42, y: ry + 0.10, w: 3.20, h: 0.30,
      fontSize: 12.5, bold: true, color: G.navy, fontFace: F.h,
    });
    s.addText(item.pattern, {
      x: ML + 0.42, y: ry + 0.40, w: 3.20, h: 0.44,
      fontSize: 9, color: G.cobalt, fontFace: F.b, bold: true,
    });

    // Divider
    s.addShape(pres.ShapeType.rect, {
      x: ML + 3.70, y: ry + 0.16, w: 0.022, h: rh - 0.32,
      fill: { color: G.rule }, line: { color: G.rule, width: 0 },
    });

    // Description
    s.addText(item.body, {
      x: ML + 3.84, y: ry + 0.08, w: CW - 4.0, h: rh - 0.16,
      fontSize: 10, color: G.onyx, fontFace: F.b, valign: "middle",
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SLIDE 14 — Closing
// ═══════════════════════════════════════════════════════════════════════════
{
  const s = darkSlide();

  // Focus frame
  s.addShape(pres.ShapeType.rect, {
    x: ML, y: 1.28, w: CW, h: 4.72,
    fill: { type: "none" },
    line: { color: G.opal, width: 0.75 },
  });

  // Header line inside frame
  s.addText("Stock Copilot — By the Numbers", {
    x: ML + 0.38, y: 1.48, w: CW - 0.76, h: 0.52,
    fontSize: 28, bold: true, color: G.white, fontFace: F.h,
  });

  // 2×3 stat grid
  const closing = [
    { n: "3",   l: "interfaces live\n(Teams · MCP · Web)" },
    { n: "6",   l: "agent modules\ndeployed to Azure"     },
    { n: "4",   l: "risk safety gates\non every trade"    },
    { n: "272", l: "automated tests\nacross 3 layers"     },
    { n: "2",   l: "GitHub Actions\npipelines"            },
    { n: "0",   l: "orders placed\nwithout risk check"    },
  ];
  const gW = 3.58, gH = 1.28, gY0 = 2.20, gGap = 0.26;
  const row2Y = 3.60;

  closing.forEach((c, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const cx = ML + 0.38 + col * (gW + gGap);
    const cy = row === 0 ? gY0 : row2Y;

    s.addText(c.n, {
      x: cx, y: cy, w: gW, h: 0.72,
      fontSize: 44, bold: true, color: G.opal, fontFace: F.h,
      align: "center",
    });
    s.addText(c.l, {
      x: cx, y: cy + 0.70, w: gW, h: 0.50,
      fontSize: 10.5, color: G.moonstone, fontFace: F.b,
      align: "center", valign: "top",
    });
  });

  // Built with line
  s.addText("Built with  Anthropic Claude  ·  Alpaca Markets  ·  Azure  ·  GitHub Actions  ·  React  ·  Figma", {
    x: ML + 0.38, y: 5.60, w: CW - 0.76, h: 0.28,
    fontSize: 10, color: G.border, fontFace: F.b, align: "center",
  });
}

// ── Write output ──────────────────────────────────────────────────────────
const OUT = path.resolve(__dirname, "..", "stock-copilot-deck-gartner.pptx");
pres.writeFile({ fileName: OUT })
  .then(() => console.log("✓ Deck written to", OUT))
  .catch(e => { console.error("✗", e.message); process.exit(1); });
