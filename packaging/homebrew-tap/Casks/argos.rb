cask "argos" do
  version "0.1.0"   # 由 .github/workflows/bump-homebrew-formula.yml 注入
  sha256 "PLACEHOLDER_FROM_BUMP"

  url "https://github.com/tungoldshou/argos/releases/download/v#{version}/Argos-#{version}-arm64-mac.tar.gz"
  name "Argos"
  desc "The hundred-eyed agent: CodeAct loop + verify hard-gate + OS sandbox (Seatbelt)"
  homepage "https://github.com/tungoldshou/argos"

  livecheck do
    url :url
    strategy :github_latest_release
  end

  app "Argos.app"

  zap trash: [
    "~/.argos",
    "~/Library/Application Support/argos-agent",
    "~/Library/Logs/argos-agent",
    "~/Library/Caches/argos-agent",
  ]
end
