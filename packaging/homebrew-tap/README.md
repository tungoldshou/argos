# tungoldshou/argos Homebrew Tap

Personal tap for [Argos](https://github.com/tungoldshou/argos) — the terminal super-agent.

## Install

```bash
brew tap tungoldshou/argos
brew install argos           # Linux/CLI (Formula, runs the AppImage)
brew install --cask argos    # macOS GUI (Cask, installs Argos.app)
```

## What lives here

- `Formula/argos.rb` — Linux/CLI install via the published AppImage (built by
  `packaging/build_linux.sh` on the `ubuntu-24.04` GitHub Actions runner).
- `Casks/argos.rb` — macOS GUI install of `Argos.app` (built by
  `packaging/build_arm64.sh` on the `macos-14` runner).

Both formulas are auto-bumped on every `v*` release by
`.github/workflows/bump-homebrew-formula.yml` in the main repo.
