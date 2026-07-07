# Argos

Argos is a Python terminal coding agent backend. The repository is intentionally
trimmed to the runtime package and minimal project metadata.

## Run

```bash
uv sync
uv run argos --help
uv run argos setup
uv run argos exec "inspect this project"
uv run argos --selftest
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/install.sh | bash
```

## Layout

- `argos/` contains the runtime package.
- `pyproject.toml` defines package metadata and console scripts.
- `uv.lock` pins the local dependency resolution.
- `install.sh` installs the package from the Git repository with `uv tool`.

## Verification

There is no bundled test suite in this trimmed tree. Use the lightweight runtime
checks instead:

```bash
uv run python -m compileall -q argos
uv run argos --selftest
```
