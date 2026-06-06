class Argos < Formula
  desc "Argos — terminal super-agent (CodeAct loop + verify hard-gate + OS sandbox)"
  homepage "https://github.com/tungoldshou/argos"
  url "https://github.com/tungoldshou/argos/releases/download/v#{version}/Argos-#{version}-x86_64.AppImage"
  sha256 "PLACEHOLDER_FROM_BUMP"   # 由 .github/workflows/bump-homebrew-formula.yml 注入
  license "MIT"
  version "0.1.0"

  livecheck do
    url :url
    strategy :github_latest_release
  end

  # AppImage 需要 fuse 挂载
  depends_on "fuse" => :linux

  def install
    bin.install "Argos-#{version}-x86_64.AppImage" => "argos"
  end

  test do
    assert_match "argos #{version}", shell_output("#{bin}/argos --version")
  end
end
