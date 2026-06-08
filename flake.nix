{
  description = "OpenTimestamps server development environment";

  inputs = {
    # Last updated: 2026-09-29. Same nixos-unstable rev as ~/git/my_flakes, so it can `follows` it.
    nixpkgs.url = "github:NixOS/nixpkgs/b4fd65b198c599cbe814fcb9f42d25d021595ec9";
  };

  outputs = { self, nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      forAllSystems = nixpkgs.lib.genAttrs systems;

      mkPkgs = system: import nixpkgs { inherit system; };

      mkPython = pkgs: pkgs.python3.withPackages (python-pkgs: [
        python-pkgs.opentimestamps
        python-pkgs.plyvel
        python-pkgs.pystache
        python-pkgs.requests
        python-pkgs.qrcode
        python-pkgs.simplejson
        python-pkgs.python-bitcoinlib
      ] ++ python-pkgs.qrcode.optional-dependencies.pil);
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = mkPkgs system;
          python = mkPython pkgs;
        in
        {
          default = pkgs.writeShellApplication {
            name = "otsd";
            runtimeInputs = [
              python
              pkgs.bitcoind
            ];
            text = ''
              export PYTHONPATH="${self}''${PYTHONPATH:+:$PYTHONPATH}"
              exec ${python}/bin/python ${self}/otsd "$@"
            '';
          };
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/otsd";
          meta.description = "Run the OpenTimestamps server daemon";
        };
      });

      devShells = forAllSystems (system:
        let
          pkgs = mkPkgs system;
          python = mkPython pkgs;
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.bitcoind
            ];

            shellHook = ''
              export PYTHONPATH="$PWD''${PYTHONPATH:+:$PYTHONPATH}"
            '';
          };
        });
    };
}
