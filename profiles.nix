let
  nine = {
    modelSize = "9b";
    modelFile = "Ternary-Bonsai-2-9B-PQ2_0.gguf";
    modelSha256 = "7a89ab48f5038c704480f60781f9b8d4035351f5f6beb7d11fad80001fde23f9";
    backend = "rocm";
    contextTokens = "65536";
    kvType = "f16";
    batchSize = "2048";
    ubatchSize = "512";
    maxTokens = "8192";
    gpuReserveMb = "512";
    extraArgs = [ ];
    draftFile = "";
    draftSha256 = "";
  };
  nineMtp = nine // {
    modelFile = "Ternary-Bonsai-2-9B-PQ2_0-MTP-Q8_0.gguf";
    modelSha256 = "c79fcdfaf6b7bf47089b50dadcfd11f9ce7d3e96adf3bbefde7912e5ef69e22b";
    extraArgs = [
      "--spec-type"
      "draft-mtp"
      "--spec-draft-n-max"
      "1"
      "--spec-draft-n-min"
      "0"
      "--spec-draft-p-min"
      "0"
    ];
  };
  twentySeven = {
    modelSize = "27b";
    modelFile = "Ternary-Bonsai-2-27B-PQ2_0.gguf";
    modelSha256 = "3907dc1658db1f78a9826bf8d5bcb8dc65db0d466388937af57f2294fae62ec1";
    backend = "rocm";
    contextTokens = "16384";
    kvType = "q8_0";
    batchSize = "1024";
    ubatchSize = "256";
    maxTokens = "8192";
    gpuReserveMb = "256";
    extraArgs = [ ];
    draftFile = "";
    draftSha256 = "";
  };
in
{
  "9b" = nineMtp;
  "9b-plain" = nine;
  "9b-rewrite" = nine // {
    contextTokens = "8192";
    maxTokens = "4096";
    batchSize = "1024";
    ubatchSize = "256";
    draftFile = "Ternary-Bonsai-2-9B-DFlash2-Q8_0.gguf";
    draftSha256 = "95149abdd584f7a69ea5ead38790d5481454428d2c1616527ff0d45422a762b4";
    extraArgs = [
      "--spec-type"
      "draft-dflash"
      "--spec-draft-n-max"
      "16"
    ];
  };
  "9b-vulkan" = nine // {
    backend = "vulkan";
    contextTokens = "32768";
  };
  "27b" = twentySeven;
  "27b-vulkan" = twentySeven // {
    modelFile = "Ternary-Bonsai-2-27B-PTQ1_0.gguf";
    modelSha256 = "53107f530aa52eb00912263ab1ee29bd199261c87cd7b4ad4ca1318c1fe33ee3";
    backend = "vulkan";
    contextTokens = "8192";
    kvType = "f16";
    maxTokens = "4096";
  };
}
