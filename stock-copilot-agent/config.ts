const config = {
  botId: process.env.BOT_ID,
  botPassword: process.env.BOT_PASSWORD,
  botTenantId: process.env.BOT_TENANT_ID,
  anthropicApiKey: process.env.ANTHROPIC_API_KEY,
  pythonApiUrl: process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000",
};

export default config;
