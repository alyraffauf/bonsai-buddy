{
  description = "Run Bonsai 2 27B in the foreground with Prism's Vulkan runtime";

  inputs.nixpkgs.url = "https://flakehub.com/f/DeterminateSystems/nixpkgs-weekly/0.1";

  outputs = { nixpkgs, ... }: let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};

    runtime = pkgs.stdenv.mkDerivation {
      pname = "prism-llama-vulkan";
      version = "b10787-73bfe6c";
      src = pkgs.fetchurl {
        url = "https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b10787-73bfe6c/llama-prism-b10787-73bfe6c-bin-ubuntu-vulkan-x64.tar.gz";
        hash = "sha256-RAHGZVBpJ/XCrUTE4uE5cV3lvV6StpOgofUVuUQq+bs=";
      };
      nativeBuildInputs = [ pkgs.autoPatchelfHook pkgs.makeWrapper ];
      buildInputs = [ pkgs.stdenv.cc.cc.lib pkgs.vulkan-loader pkgs.openssl pkgs.curl ];
      dontBuild = true;
      dontStrip = true;
      installPhase = ''
        runHook preInstall
        mkdir -p $out/lib/bonsai2 $out/bin
        cp -a . $out/lib/bonsai2/
        makeWrapper $out/lib/bonsai2/llama-server $out/bin/llama-server \
          --prefix LD_LIBRARY_PATH : ${pkgs.lib.makeLibraryPath [ pkgs.vulkan-loader ]} \
          --prefix XDG_DATA_DIRS : /run/opengl-driver/share
        runHook postInstall
      '';
    };

    bonsaid = pkgs.writeShellApplication {
      name = "bonsaid";
      runtimeInputs = [ pkgs.curl pkgs.coreutils ];
      text = builtins.readFile (pkgs.replaceVars ./bonsaid.sh {
        llamaServer = "${runtime}/bin/llama-server";
      });
    };
  in {
    packages.${system} = {
      default = bonsaid;
      inherit bonsaid runtime;
    };
    apps.${system}.default = {
      type = "app";
      program = "${bonsaid}/bin/bonsaid";
    };
  };
}
