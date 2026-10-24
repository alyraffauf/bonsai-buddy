# Build a standalone probe against the same source and HIP plugin as the runtime.
{
  repository,
  interpose ? false,
}:
let
  flake = builtins.getFlake repository;
  pkgs = flake.inputs.nixpkgs.legacyPackages.x86_64-linux;
  runtime = flake.packages.x86_64-linux.runtime-source;
in
pkgs.stdenv.mkDerivation {
  pname = if interpose then "bonsai-matvec-experiment" else "bonsai-matvec-probe";
  version = "b87ca72";
  src = runtime.src;
  nativeBuildInputs = [
    pkgs.python3
    pkgs.rocmPackages.clr
    pkgs.makeWrapper
  ];
  buildInputs = with pkgs.rocmPackages; [
    clr
    hipblas
    rocblas
  ];
  postPatch = ''
    python3 ${./prepare-matvec.py} ggml/src/ggml-cuda/mmvq.cu probe-mmvq.cuh
    cp ${if interpose then ./matvec-interpose.cpp else ./matvec.cpp} probe.cpp
  '';
  buildPhase = ''
    ${pkgs.lib.optionalString interpose ''
      echo '{ global: _Z*ggml_cuda_mul_mat_vec_q*; local: *; };' > exports.map
    ''}
    hipcc $NIX_CFLAGS_COMPILE -O3 -std=c++17 --offload-arch=gfx1030 \
      ${pkgs.lib.optionalString interpose "-shared -fPIC -Wl,--version-script,exports.map"} \
      -DGGML_USE_HIP -DGGML_HIP_GRAPHS -DGGML_BACKEND_SHARED -DGGML_BACKEND_BUILD \
      -I. -Iggml/include -Iggml/src -Iggml/src/ggml-cuda \
      -I${pkgs.lib.getDev pkgs.rocmPackages.hipblas}/include \
      -I${pkgs.lib.getDev pkgs.rocmPackages.rocblas}/include \
      probe.cpp -L${runtime}/bin -L${runtime}/lib \
      -Wl,-rpath,${runtime}/bin -Wl,-rpath,${runtime}/lib \
      -lggml-hip -lggml-base ${pkgs.lib.optionalString interpose "-ldl"} \
      -o ${if interpose then "libbonsai-matvec.so" else "bonsai-matvec-probe"}
  '';
  installPhase = ''
    mkdir -p $out/${if interpose then "lib" else "bin"}
    cp ${if interpose then "libbonsai-matvec.so $out/lib/" else "bonsai-matvec-probe $out/bin/"}
    ${pkgs.lib.optionalString interpose ''
      mkdir -p $out/bin
      makeWrapper ${runtime}/bin/llama-server $out/bin/bonsai-matvec-server \
        --prefix LD_PRELOAD : $out/lib/libbonsai-matvec.so
    ''}
  '';
}
