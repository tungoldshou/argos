# Setup Wizard — `argos setup`

`argos setup` is an interactive wizard that writes `~/.argos/config.json` and
`~/.argos/.env`. It probes the connection and the CodeAct format so you know
the configuration is correct before your first run.

Run it once after installing:

```bash
uv run argos setup
```

It asks you to:

1. Pick a provider protocol (`anthropic` or `openai`).
2. Enter the API endpoint base URL.
3. Enter the model name (e.g. `claude-sonnet-4-5`, `gpt-4o`, `MiniMax-M2`).
4. Enter the API key (written to `~/.argos/.env`, mode 0600 — never to
   `config.json`).
5. Optionally enter the context window size and price information.

After you confirm, the wizard runs a real request against the endpoint to
verify the key and the CodeAct format.

---

## Config schema — `~/.argos/config.json`

```json
{
  "active": "default",
  "models": {
    "default": {
      "protocol":        "anthropic",
      "base_url":        "https://api.anthropic.com",
      "model":           "claude-sonnet-4-5",
      "api_key_env":     "ANTHROPIC_API_KEY",
      "max_tokens":      8096,
      "context_window":  200000,
      "price_in":        0.000003,
      "price_out":       0.000015,
      "embedding_model": "text-embedding-3-small"
    }
  }
}
```

### Field reference

| Field | Required | Description |
|---|---|---|
| `protocol` | Yes | `"anthropic"` or `"openai"` — selects the wire format |
| `base_url` | Yes | API endpoint root (no trailing slash) |
| `model` | Yes | Model identifier passed to the API |
| `api_key_env` | Yes | Name of the environment variable that holds the key |
| `max_tokens` | No | Max tokens per completion (default: 8096) |
| `context_window` | No | Model's total context window in tokens (used by context viz) |
| `price_in` | No | Cost per input token in USD (used by `/cost` and `argos exec`) |
| `price_out` | No | Cost per output token in USD |
| `embedding_model` | No | Embedding model for memory recall (falls back to FTS5 if omitted) |

### `active` and `models`

`config.json` holds a `models` map of named profiles plus an `active` key that
names the default profile. `argos --model <name>` overrides `active` for one
run; `argos exec --model <name>` does the same for headless runs.

Multiple profiles let you route tasks to different tiers:

```json
{
  "active": "default",
  "models": {
    "cheap":   { "protocol": "anthropic", "base_url": "...", "model": "claude-haiku-4-5",   "api_key_env": "K" },
    "default": { "protocol": "anthropic", "base_url": "...", "model": "claude-sonnet-4-5",  "api_key_env": "K" },
    "strong":  { "protocol": "anthropic", "base_url": "...", "model": "claude-opus-4-5",    "api_key_env": "K" }
  }
}
```

See [docs/per-task-routing.md](per-task-routing.md) for automatic per-task routing.

---

## Key storage — `~/.argos/.env`

The setup wizard writes API keys to `~/.argos/.env` (Unix permissions 0600),
**never** into `config.json`. The format is standard `KEY=value`:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

You can also export keys as regular environment variables before launching
Argos; they take precedence over `.env`.

---

## Non-TTY / headless setup

When stdin is not a TTY (e.g. inside a Docker container or a CI pipeline),
`argos setup` cannot run the interactive prompts. In that case, write
`~/.argos/config.json` and `~/.argos/.env` directly using the schemas above,
or mount them as secrets.

See this file ([docs/setup-wizard.md](setup-wizard.md)) for the full schema.

---

## Resetting configuration

To start over, remove the config directory and re-run setup:

```bash
rm -rf ~/.argos
uv run argos setup
```
