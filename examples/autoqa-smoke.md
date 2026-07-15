# Fagun AutoQA Smoke Prompt

Use this to verify the no-model-key AutoQA flow inside any MCP-capable AI client.

Target:

```text
https://example.com
```

Prompt:

```text
fagun https://example.com: verify the page loads, the title contains "Example Domain", the body shows "Example Domain", and the page links to https://iana.org/domains/example.
```

Expected flow:

1. Call `autoqa_prompt("https://example.com", "verify the page loads, the title contains Example Domain, the body shows Example Domain, and the page links to https://iana.org/domains/example")`.
2. Fill a compact plan from `autoqa_plan_template(...)`.
3. Execute through Chrome DevTools MCP/default Chrome first. Use Fagun browser tools such as `navigate`, `evaluate_js`, `screenshot`, `get_console`, and `get_network` only as needed or if Chrome MCP is unavailable.
4. Use supporting MCPs as needed while Fagun remains the main report owner: Jam for per-step screenshot/screen recording evidence, Playwright for isolated repeatable automation, MCP Fetch for static/API/header checks, Context7 for current library docs, and VirusTotal/Shodan only for authorized security intelligence when keys are configured.
5. Capture per-step evidence. For reproducible bugs, use Jam MCP when available and attach `jam_url`, screenshot, or screen-recording evidence.
6. Generate the final HTML report with `autoqa_write_html_report`, then open the returned Report URL with Chrome DevTools MCP/default Chrome.
7. Return a verdict with evidence and the report path. No Groq, OpenAI, Anthropic, Gemini, or other model API key should be requested.

Expected result:

```text
PASS
HTML report path under ./reports/
```
