{ pkgs, rocmRuntime }:
let
  revision = "b87ca7225456b06b0975b8239c66b5aecf07e37c";
  source = pkgs.fetchFromGitHub {
    owner = "PrismML-Eng";
    repo = "llama.cpp";
    rev = revision;
    hash = "sha256-qeHj29kr/0JecU/zpwaVYV7u6NY/d3BZffX9+sdp+Hc=";
  };
  rocmLibraries = with pkgs.rocmPackages; [
    clr
    hipblas
    rocblas
    hipblaslt
  ];
  cpuRuntime = pkgs.llama-cpp.override {
    cudaSupport = false;
    rocmSupport = false;
    vulkanSupport = false;
    blasSupport = false;
    cpuArchDynamicDispatch = false;
  };
in
cpuRuntime.overrideAttrs (previous: {
  pname = "prism-llama-rocm-source";
  version = "b10794-b87ca72";
  src = source;
  patches = [ ];
  doCheck = false;
  npmDeps = pkgs.fetchNpmDeps {
    name = "bonsaid-ui-deps";
    src = source;
    preBuild = "pushd tools/ui";
    hash = "sha256-2Q7XhaLAArmviOLdQsNbYTfdyDE5pW9lR26cRHEVl9k=";
  };
  buildInputs = previous.buildInputs ++ rocmLibraries;
  nativeBuildInputs = previous.nativeBuildInputs ++ [
    pkgs.makeWrapper
    pkgs.patchelf
  ];
  preConfigure = ''
    pushd tools/ui
    LLAMA_BUILD_NUMBER=10794 npm run build
    popd
  '';
  cmakeFlags = previous.cmakeFlags ++ [
    "-DGGML_BACKEND_DL=ON"
    "-DGGML_BACKEND_DIR=${placeholder "out"}/bin"
    "-DGGML_AVX=ON"
    "-DGGML_AVX2=ON"
    "-DGGML_FMA=ON"
    "-DGGML_F16C=ON"
    "-DLLAMA_BUILD_NUMBER=10794"
    "-DLLAMA_BUILD_COMMIT=b87ca7225"
    "-DLLAMA_USE_PREBUILT_UI=OFF"
  ];
  postInstall = (previous.postInstall or "") + ''
    # These seven upstream commits change no GPU code or backend ABI.
    # Reuse the release's HIP plugin while rebuilding the server and grammar code.
    cp ${rocmRuntime}/lib/bonsai2/libggml-hip.so $out/bin/libggml-hip.so
    chmod u+w $out/bin/libggml-hip.so
    patchelf --set-rpath "$out/lib:$out/bin:${pkgs.lib.makeLibraryPath rocmLibraries}" $out/bin/libggml-hip.so
    for program in llama-server llama-bench; do
      wrapProgram $out/bin/$program \
        --set-default HSA_OVERRIDE_GFX_VERSION 10.3.0 \
        --set-default ROCBLAS_TENSILE_LIBPATH ${pkgs.rocmPackages.rocblas}/lib/rocblas/library
    done
  '';
  meta = previous.meta // {
    mainProgram = "llama-server";
    description = "Prism Bonsai runtime with agent grammar fixes and ROCm";
  };
})
