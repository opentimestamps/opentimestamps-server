# shell.nix
let
  # We pin to a specific nixpkgs commit for reproducibility.
  # Last updated: 2024-04-29. Check for new commits at https://status.nixos.org.
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/cf8cc1201be8bc71b7cbbbdaf349b22f4f99c7ae.tar.gz") {};
in pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (python-pkgs: [
      python-pkgs.opentimestamps
      python-pkgs.leveldb
      python-pkgs.pystache
      python-pkgs.requests
      python-pkgs.qrcode
      python-pkgs.simplejson
      python-pkgs.bitcoinlib
    ]))
  ];
}
