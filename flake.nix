{
  # Argos — terminal super-agent (CodeAct + verify gate + OS sandbox)
  # spec §9 / D11: simplified buildPythonApplication; ddgs / mlx-embeddings /
  # sqlite-vec / playwright / trafilatura are not all available in nixpkgs yet.
  # v1.1 can move to full buildPythonPackage overrides for missing packages.
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
      # Full dependencies include ddgs / mlx-embeddings / sqlite-vec /
      # playwright / trafilatura. This simplified flake expects users to install
      # the missing packages separately; v1.1 can add proper overrides.
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
