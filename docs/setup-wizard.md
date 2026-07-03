# Setup Wizard — `argos setup`

`argos setup` is an interactive wizard that writes `config.json` under the
Argos config directory. By default that directory is `~/.argos`; set
`ARGOS_CONFIG_DIR` to move it.

If you paste a key, setup also writes `.env` in that same directory; if you choose an existing
environment variable, it stores only that variable name. It probes the
connection and the CodeAct format so you know the configuration is correct
before your first run.

Run it once after installing:

```bash
uv run argos setup
```

Check what is currently configured without probing the network:

```bash
uv run argos setup status
```

It asks you to:

1. Pick a provider preset, or choose `Custom`.
2. Confirm the model name (for example `claude-sonnet-4-6`, `gpt-4o`,
   `MiniMax-M3`). Custom profiles also ask for protocol and endpoint.
3. Paste the API key, or point Argos at an existing environment variable.
   Pasted keys are written to `.env` in the config directory (mode 0600), never to
   `config.json`; env-var mode stores only the variable name.
4. Optionally run the deeper write-and-verify probe.
5. Choose the profile name and whether it should become the active default.

With `--advanced`, the wizard also asks for `max_tokens`, `context_window`,
an image-input override, and, for OpenAI-compatible providers, an embedding
model. Price fields are manual config fields, not interactive setup prompts.

After you confirm, the wizard runs a real request against the endpoint to
verify the key and the CodeAct format.

`argos setup status` is read-only. It prints the active profile, model,
endpoint, configured key environment variable, whether the key is available
from the environment or the config directory `.env`, the memory embedding mode, the image
input mode, and the config file path. When no `config.json` exists, it may also
label `.env.local` as the development fallback key source; it reports only the
source label, not the key value.

---

## Config schema — `config.json`

```json
{
  "active": "default",
  "models": {
    "default": {
      "protocol":        "anthropic",
      "base_url":        "https://api.anthropic.com",
      "model":           "claude-sonnet-4-6",
      "api_key_env":     "ANTHROPIC_API_KEY",
      "max_tokens":      4096,
      "context_window":  200000,
      "price_in":        3.00,
      "price_out":       15.00,
      "embedding_model": "text-embedding-3-small",
      "multimodal":      true
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
| `max_tokens` | No | Max tokens per completion (default: 4096) |
| `context_window` | No | Model's total context window in tokens (used by context viz) |
| `price_in` | No | USD per 1M input tokens (used by `/cost` and `argos exec`) |
| `price_out` | No | USD per 1M output tokens |
| `embedding_model` | No | Embedding model for memory recall (falls back to FTS5 if omitted) |
| `multimodal` | No | Image input override: `true`/`false`, or omit for first-image auto-detect |

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
    "default": { "protocol": "anthropic", "base_url": "...", "model": "claude-sonnet-4-6",  "api_key_env": "K" },
    "strong":  { "protocol": "anthropic", "base_url": "...", "model": "claude-opus-4-5",    "api_key_env": "K" }
  }
}
```

See [docs/per-task-routing.md](per-task-routing.md) for automatic per-task routing.

---

## Key storage — `.env`

When you paste a key, the setup wizard writes it to `.env` under the config directory (Unix
permissions 0600), **never** into `config.json`. The format is standard
`KEY=value`:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

You can also export keys as regular environment variables before launching
Argos; they take precedence over `.env`.

Shell-style `export KEY=value` lines are also accepted when you hand-write
the config directory `.env`; matching single or double quotes around the value are stripped.

---

## Non-TTY / headless setup

When stdin is not a TTY (e.g. inside a Docker container or a CI pipeline),
`argos setup` cannot run the interactive prompts. In that case, write
`config.json` directly using the schema above, then provide the key through
the config directory `.env`, an existing environment variable, or a mounted secret.

See this file ([docs/setup-wizard.md](setup-wizard.md)) for the full schema.

---

## Resetting configuration

To start over, remove the config directory and re-run setup:

```bash
# default config directory; use "$ARGOS_CONFIG_DIR" if you moved it
rm -rf ~/.argos
uv run argos setup
```
