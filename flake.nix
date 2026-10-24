{
  description = "Bonsai Buddy profiles for coding agents on the Radeon RX 6700";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      mkRuntime =
        backend:
        let
          isRocm = backend == "rocm";
          archiveBackend = if isRocm then "rocm-7.2" else "vulkan";
        in
        pkgs.stdenv.mkDerivation {
          pname = "prism-llama-${backend}";
          version = "b10787-73bfe6c";
          src = pkgs.fetchurl {
            url = "https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b10787-73bfe6c/llama-prism-b10787-73bfe6c-bin-ubuntu-${archiveBackend}-x64.tar.gz";
            hash =
              if isRocm then
                "sha256-aDktKYBGnyZ7o3f83wzoNuaHgNSpcgbKh98UQq+zJJc="
              else
                "sha256-RAHGZVBpJ/XCrUTE4uE5cV3lvV6StpOgofUVuUQq+bs=";
          };
          nativeBuildInputs = [
            pkgs.autoPatchelfHook
            pkgs.makeWrapper
          ];
          buildInputs = [
            pkgs.stdenv.cc.cc.lib
            pkgs.openssl
            pkgs.curl
          ]
          ++ pkgs.lib.optionals isRocm [
            pkgs.rocmPackages.clr
            pkgs.rocmPackages.hipblas
            pkgs.rocmPackages.rocblas
            pkgs.rocmPackages.hipblaslt
          ]
          ++ pkgs.lib.optional (!isRocm) pkgs.vulkan-loader;
          dontBuild = true;
          dontStrip = true;
          installPhase = ''
            runHook preInstall
            mkdir -p $out/lib/bonsai2 $out/bin
            cp -a . $out/lib/bonsai2/
            wrapper_arguments=(
              ${
                if isRocm then
                  ''
                    --set-default HSA_OVERRIDE_GFX_VERSION 10.3.0
                    --set-default ROCBLAS_TENSILE_LIBPATH ${pkgs.rocmPackages.rocblas}/lib/rocblas/library
                  ''
                else
                  ''
                    --prefix LD_LIBRARY_PATH : ${pkgs.lib.makeLibraryPath [ pkgs.vulkan-loader ]}
                    --prefix XDG_DATA_DIRS : /run/opengl-driver/share
                  ''
              }
            )
            for program in llama-server llama-bench; do
              makeWrapper $out/lib/bonsai2/$program $out/bin/$program \
                "''${wrapper_arguments[@]}"
            done
            runHook postInstall
          '';
        };

      runtime = mkRuntime "vulkan";
      rocmRuntime = mkRuntime "rocm";
      sourceRuntime = import ./runtime-source.nix { inherit pkgs rocmRuntime; };
      kernelMarkers =
        pkgs.runCommand "bonsai-buddy-kernel-markers"
          {
            nativeBuildInputs = [ pkgs.stdenv.cc ];
            buildInputs = [
              sourceRuntime.dev
              pkgs.rocmPackages.rocprofiler-sdk
            ];
          }
          ''
            mkdir -p $out/lib
            c++ -shared -fPIC -O2 -Wall -Wextra -Werror \
              ${./benchmarks/kernel-markers.cpp} \
              -lrocprofiler-sdk-roctx -ldl -o $out/lib/libbonsai-kernel-markers.so
          '';
      vramHelper = pkgs.runCommand "bonsai-buddy-vram" { nativeBuildInputs = [ pkgs.stdenv.cc ]; } ''
        mkdir -p $out/bin
        c++ -O2 -std=c++17 ${./vram.cpp} -ldl -o $out/bin/bonsai-buddy-vram
      '';

      profiles = import ./profiles.nix;
      renderScript =
        script: substitutions:
        builtins.replaceStrings (map (key: "@${key}@") (
          builtins.attrNames substitutions
        )) (builtins.attrValues substitutions) (builtins.readFile script);
      mkBonsaiBuddy =
        name: profile:
        let
          substitutions = (builtins.removeAttrs profile [ "extraArgs" ]) // {
            llamaServer = "${if profile.backend == "vulkan" then runtime else sourceRuntime}/bin/llama-server";
            vramHelper = "${vramHelper}/bin/bonsai-buddy-vram";
            hipLibrary = "${pkgs.rocmPackages.clr}/lib/libamdhip64.so.7";
            extraArgs = pkgs.lib.escapeShellArgs profile.extraArgs;
          };
        in
        pkgs.writeShellApplication {
          name = "bonsai-buddy-${name}";
          runtimeInputs = [
            pkgs.curl
            pkgs.coreutils
          ];
          text = renderScript ./bonsai-buddy.sh substitutions;
        };

      modelPackages = builtins.mapAttrs mkBonsaiBuddy profiles;
      mkClient =
        size:
        let
          profile = profiles.${size};
          clientPackage = pkgs.opencode;
          opencodeConfig = pkgs.writeText "bonsai-buddy-opencode-${size}.json" (
            builtins.toJSON {
              "$schema" = "https://opencode.ai/config.json";
              model = "bonsai-buddy/bonsai2:${size}";
              agents.title.model = "bonsai-buddy/bonsai2:${size}";
              compaction.auto = true;
              providers.bonsai-buddy = {
                package = "@opencode/ai/providers/openai-compatible";
                name = "Bonsai Buddy";
                settings.baseURL = "http://127.0.0.1:8080/v1";
                models."bonsai2:${size}" = {
                  name = "Bonsai 2 ${size}";
                  capabilities = {
                    tools = true;
                    input = [ "text" ];
                    output = [ "text" ];
                    reasoning.supported = true;
                  };
                  compatibility.reasoningField = "reasoning_content";
                  settings.reasoningEffort = "medium";
                };
              };
            }
          );
        in
        pkgs.writeShellApplication {
          name = "bonsai-buddy-opencode-${size}";
          runtimeInputs = [
            pkgs.coreutils
            pkgs.curl
            pkgs.jq
            clientPackage
          ];
          text = renderScript ./client.sh {
            clientProgram = pkgs.lib.getExe clientPackage;
            serverProgram = pkgs.lib.getExe modelPackages.${size};
            modelSize = size;
            inherit (profile) contextTokens maxTokens thinkingTokens;
            reserveTokens = if size == "27b" then "4096" else "8192";
            opencodeConfig = "${opencodeConfig}";
          };
        };
      clientPackages = builtins.listToAttrs (
        map
          (size: {
            name = "opencode-${size}";
            value = mkClient size;
          })
          [
            "9b"
            "27b"
          ]
      );
      mkApp = package: {
        type = "app";
        program = pkgs.lib.getExe package;
      };
    in
    {
      packages.${system} =
        modelPackages
        // clientPackages
        // {
          default = modelPackages."9b";
          bonsai-buddy = modelPackages."9b";
          inherit runtime;
          runtime-rocm = rocmRuntime;
          runtime-source = sourceRuntime;
          kernel-markers = kernelMarkers;
        };
      apps.${system} = builtins.mapAttrs (_: mkApp) (modelPackages // clientPackages) // {
        default = mkApp modelPackages."9b";
        bench = {
          type = "app";
          program = "${sourceRuntime}/bin/llama-bench";
        };
        bench-rocm = {
          type = "app";
          program = "${sourceRuntime}/bin/llama-bench";
        };
        bench-rocm-release = {
          type = "app";
          program = "${rocmRuntime}/bin/llama-bench";
        };
        bench-vulkan = {
          type = "app";
          program = "${runtime}/bin/llama-bench";
        };
      };
      formatter.${system} = pkgs.nixfmt;
      checks.${system}.python =
        pkgs.runCommand "bonsai-buddy-python-checks"
          {
            nativeBuildInputs = [
              pkgs.python3
              pkgs.ruff
              pkgs.ty
              pkgs.bash
              pkgs.curl
              pkgs.jq
            ];
          }
          ''
            cp -r ${./benchmarks} benchmarks
            cp -r ${./tests} tests
            cp ${./pyproject.toml} pyproject.toml
            cp ${./client.sh} client.sh
            cp ${./bonsai-buddy.sh} bonsai-buddy.sh
            ruff format --check benchmarks tests
            ruff check benchmarks tests
            ty check --extra-search-path benchmarks benchmarks tests
            PYTHONPATH=benchmarks python3 -B -m unittest discover -s tests -v
            touch $out
          '';
      devShells.${system} = {
        default = pkgs.mkShell {
          packages = [
            pkgs.python3
            pkgs.stdenv.cc
            pkgs.ruff
            pkgs.ty
            pkgs.bash
            pkgs.curl
            pkgs.jq
          ];
          BONSAI_BUDDY_INCLUDE = "${sourceRuntime.dev}/include";
          BONSAI_BUDDY_RELEASE_LIB = "${rocmRuntime}/lib/bonsai2";
          BONSAI_BUDDY_SOURCE_LIB = "${sourceRuntime}/lib";
        };
        profiling = pkgs.mkShell {
          packages = [
            pkgs.python3
            pkgs.rocmPackages.rocprofiler-sdk
          ];
          BONSAI_BUDDY_BENCH = "${sourceRuntime}/bin/llama-bench";
          BONSAI_BUDDY_SERVER = "${sourceRuntime}/bin/llama-server";
          BONSAI_BUDDY_KERNEL_MARKERS = "${kernelMarkers}/lib/libbonsai-kernel-markers.so";
        };
      };
    };
}
