{ repository }:
let
  flake = builtins.getFlake repository;
  pkgs = flake.inputs.nixpkgs.legacyPackages.x86_64-linux;
  runtime = flake.packages.x86_64-linux.runtime-source;
in
pkgs.runCommand "bonsai-logits" { nativeBuildInputs = [ pkgs.stdenv.cc ]; } ''
  mkdir -p $out/bin
  c++ -O2 -Wall -Wextra -Werror -std=c++17 ${./logits.cpp} -I${runtime.dev}/include \
    -L${runtime}/lib -Wl,-rpath,${runtime}/lib \
    -lllama -lggml-base -lggml -o $out/bin/bonsai-logits
''
