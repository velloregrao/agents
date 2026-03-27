import { parseIntent } from "../../teamsBot";

// ── Help ──────────────────────────────────────────────────────────────────────
describe("help intent", () => {
  test.each(["help", "Help", "HELP", "hi", "hello", "hey"])(
    '"%s" → help',
    (input) => {
      expect(parseIntent(input).intent).toBe("help");
    }
  );
});

// ── Analyze ───────────────────────────────────────────────────────────────────
describe("analyze intent", () => {
  test("bare ticker", () => {
    const r = parseIntent("AAPL");
    expect(r.intent).toBe("analyze");
    expect(r.tickers).toContain("AAPL");
  });

  test("analyze AAPL", () => {
    const r = parseIntent("Analyze AAPL");
    expect(r.intent).toBe("analyze");
    expect(r.tickers).toContain("AAPL");
  });

  test("lowercase ticker gets extracted", () => {
    const r = parseIntent("analyze tsla");
    expect(r.tickers).toContain("TSLA");
  });
});

// ── Research ──────────────────────────────────────────────────────────────────
describe("research intent", () => {
  test.each([
    "Research NVDA",
    "deep dive MSFT",
    "full analysis AAPL",
    "recommend TSLA",
  ])('"%s" → research', (input) => {
    expect(parseIntent(input).intent).toBe("research");
  });

  test("research without ticker → not research", () => {
    expect(parseIntent("research").intent).not.toBe("research");
  });
});

// ── Trade ─────────────────────────────────────────────────────────────────────
describe("trade intent", () => {
  test("trade single ticker", () => {
    const r = parseIntent("Trade AAPL");
    expect(r.intent).toBe("trade");
    expect(r.tickers).toContain("AAPL");
  });

  test("trade multiple tickers", () => {
    const r = parseIntent("Trade AAPL MSFT TSLA");
    expect(r.intent).toBe("trade");
    expect(r.tickers).toContain("AAPL");
    expect(r.tickers).toContain("MSFT");
    expect(r.tickers).toContain("TSLA");
  });

  test("buy intent maps to trade", () => {
    expect(parseIntent("buy AAPL").intent).toBe("trade");
  });

  test("sell intent maps to trade", () => {
    expect(parseIntent("sell NVDA").intent).toBe("trade");
  });
});

// ── Portfolio ─────────────────────────────────────────────────────────────────
describe("portfolio intent", () => {
  test.each([
    "portfolio",
    "show my portfolio",
    "my positions",
    "holdings",
    "performance",
    "show stats",
    "pnl",
    "profit",
  ])('"%s" → portfolio', (input) => {
    expect(parseIntent(input).intent).toBe("portfolio");
  });
});

// ── Reflect ───────────────────────────────────────────────────────────────────
describe("reflect intent", () => {
  test.each(["reflect", "reflection", "lessons", "learn from trades"])(
    '"%s" → reflect',
    (input) => {
      expect(parseIntent(input).intent).toBe("reflect");
    }
  );
});

// ── Monitor ───────────────────────────────────────────────────────────────────
describe("monitor intent", () => {
  test.each(["monitor", "check positions", "review positions"])(
    '"%s" → monitor',
    (input) => {
      expect(parseIntent(input).intent).toBe("monitor");
    }
  );
});

// ── Unknown ───────────────────────────────────────────────────────────────────
describe("unknown intent", () => {
  test("gibberish with no extractable ticker returns unknown", () => {
    // All words are either too long (>5 chars) or in skipWords
    expect(parseIntent("what is the performance today").intent).toBe("portfolio");
    expect(parseIntent("please analyze").intent).toBe("unknown");
  });

  test("empty string returns unknown", () => {
    expect(parseIntent("").intent).toBe("unknown");
  });
});

// ── Raw text preserved ────────────────────────────────────────────────────────
describe("raw text", () => {
  test("raw field preserves original text", () => {
    const r = parseIntent("Research NVDA and tell me if I should buy it");
    expect(r.raw).toBe("Research NVDA and tell me if I should buy it");
  });
});
