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
3. Execute with Fagun browser tools: `navigate`, `evaluate_js`, `screenshot`, `get_console`, and `get_network`.
4. Return a verdict with evidence. No Groq, OpenAI, Anthropic, Gemini, or other model API key should be requested.

Expected result:

```text
PASS
```
