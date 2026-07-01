cask "argos" do
  version "0.1.0"   # 由 release script 自动更新(spec §2.2)
  sha256 "PLACEHOLDER_SHA256_AT_RELEASE_TIME"  # 由 release script 自动更新

  url "https://github.com/tungoldshou/argos/releases/download/v#{version}/Argos-#{version}-arm64-mac.tar.gz"
  name "Argos"
  desc "The hundred-eyed agent: CodeAct loop + verify hard-gate + opt-in OS sandbox"
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
