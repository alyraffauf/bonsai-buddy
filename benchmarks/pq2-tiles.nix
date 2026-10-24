# Rebuild only the PQ2 MMQ instantiation for geometry experiments on gfx1030.
# Link to the pinned plugin so LD_PRELOAD can replace its exported instantiation.
{
  repository,
  rows ? 128,
}:
let
  flake = builtins.getFlake repository;
  pkgs = flake.inputs.nixpkgs.legacyPackages.x86_64-linux;
  runtime = flake.packages.x86_64-linux.runtime-source;
in
assert builtins.elem rows [
  64
  128
];
pkgs.stdenv.mkDerivation {
  pname = "bonsai-pq2-tile-experiment";
  version = "b87ca72-i${toString rows}";
  src = runtime.src;
  nativeBuildInputs = [ pkgs.rocmPackages.clr ];
  buildInputs = with pkgs.rocmPackages; [
    clr
    hipblas
    rocblas
  ];
  postPatch = ''
    substituteInPlace ggml/src/ggml-cuda/mmq-config-rdna2.cuh \
      --replace-fail 'CASE(GGML_TYPE_PQ2_0, 256, 2, 128,' \
        'CASE(GGML_TYPE_PQ2_0, 256, 2, ${toString rows},'
    substituteInPlace ggml/src/ggml-cuda/mmq.cuh \
      --replace-fail 'for (int J = 8; J <= 128 && ntiles_J_best > 1; J += 8) {' \
        'const char * tile = getenv("BONSAI_BUDDY_PQ2_TILE");
    const int requested = tile ? atoi(tile) : 64;
    const bool valid = requested >= 8 && requested <= 64 && requested % 8 == 0;
    const int limit = valid && type == GGML_TYPE_PQ2_0 && GGML_CUDA_CC_IS_RDNA2(cc) ? requested : 128;
    for (int J = 8; J <= limit && J <= 128 && ntiles_J_best > 1; J += 8) {'
  '';
  buildPhase = ''
    runHook preBuild
    hipcc $NIX_CFLAGS_COMPILE -shared -fPIC -O3 -std=c++17 --offload-arch=gfx1030 \
      -DGGML_USE_HIP -DGGML_BACKEND_SHARED -DGGML_BACKEND_BUILD \
      -Iggml/include -Iggml/src -Iggml/src/ggml-cuda \
      -I${pkgs.lib.getDev pkgs.rocmPackages.hipblas}/include -I${pkgs.lib.getDev pkgs.rocmPackages.rocblas}/include \
      ggml/src/ggml-cuda/template-instances/mmq-instance-pq2_0.cu \
      -L${runtime}/bin -L${runtime}/lib \
      -Wl,-rpath,${runtime}/bin -Wl,-rpath,${runtime}/lib \
      -lggml-hip -lggml-base -o libbonsai-pq2-experiment.so
    runHook postBuild
  '';
  installPhase = ''
    mkdir -p $out/lib
    cp libbonsai-pq2-experiment.so $out/lib/
  '';
}
