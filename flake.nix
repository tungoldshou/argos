{
  # Argos — terminal super-agent (CodeAct + verify gate + OS sandbox)
  # spec §9 / D11:简化版 buildPythonApplication;ddgs / mlx-embeddings / sqlite-vec /
  # playwright / trafilatura 在 nixpkgs 暂缺,本期只引现成的 smolagents/textual/httpx/numpy。
  # v1.1 走完整 buildPythonPackage / override 处理 nixpkgs 不可得包。
  description = "Argos — terminal super-agent";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  outputs = { self, nixpkgs }: let
    pkgs = nixpkgs.legacyPackages.x86_64-linux;
    pyPkgs = pkgs.python312Packages;
  in {
    packages.x86_64-linux.default = pyPkgs.buildPythonApplication {
      pname = "argos-agent";
      version = "0.1.0";
      src = ./.;
      format = "pyproject";
      propagatedBuildInputs = with pyPkgs; [
        smolagents
        textual
        httpx
        numpy
      ];
      # 注:完整依赖 ddgs / mlx-embeddings / sqlite-vec / playwright / trafilatura
      # 暂不在 nixpkgs,本简化版要求用户用 pip install --break-system-packages
      # 装剩余依赖;v1.1 走 override 完整化。
      doCheck = false;
      meta = with pkgs.lib; {
        description = "Argos — terminal super-agent (CodeAct + verify gate + OS sandbox)";
        homepage = "https://github.com/tungoldshou/argos";
        license = licenses.mit;
        mainProgram = "argos";
        platforms = [ "x86_64-linux" ];
      };
    };
    apps.x86_64-linux.default = {
      type = "app";
      program = "${self.packages.x86_64-linux.default}/bin/argos";
    };
  };
}
