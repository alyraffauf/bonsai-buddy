// Capture full-vocabulary rows under a fixed one/two/three-token decode schedule.
#include "llama.h"
#include "ggml-backend.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char ** argv) try {
    if (argc != 6) throw std::runtime_error("Usage: logits MODEL BACKENDS TEXT OUTPUT KV_TYPE");
    ggml_backend_load_all_from_path(argv[2]);
    ggml_backend_load_all_from_path((std::string(argv[2]) + "/../lib").c_str());
    llama_backend_init();
    auto model_parameters = llama_model_default_params();
    model_parameters.n_gpu_layers = 99;
    auto model = std::unique_ptr<llama_model, decltype(&llama_model_free)>(
        llama_model_load_from_file(argv[1], model_parameters), llama_model_free);
    if (!model) throw std::runtime_error("Cannot load model");
    auto parameters = llama_context_default_params();
    parameters.n_ctx = 4096;
    parameters.n_batch = parameters.n_ubatch = 256;
    parameters.n_threads = parameters.n_threads_batch = 6;
    parameters.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_ENABLED;
    const std::string cache_type = argv[5];
    if (cache_type != "f16" && cache_type != "q8_0") throw std::runtime_error("KV_TYPE must be f16 or q8_0");
    parameters.type_k = parameters.type_v = cache_type == "f16" ? GGML_TYPE_F16 : GGML_TYPE_Q8_0;
    auto context = std::unique_ptr<llama_context, decltype(&llama_free)>(
        llama_init_from_model(model.get(), parameters), llama_free);
    if (!context) throw std::runtime_error("Cannot allocate context");
    std::ifstream source(argv[3]);
    if (!source) throw std::runtime_error("Cannot read text");
    const std::string text((std::istreambuf_iterator<char>(source)), {});
    const auto * vocabulary = llama_model_get_vocab(model.get());
    int count = llama_tokenize(vocabulary, text.data(), text.size(), nullptr, 0, true, true);
    if (count >= 0) throw std::runtime_error("Expected nonempty tokenization");
    std::vector<llama_token> tokens(-count);
    count = llama_tokenize(vocabulary, text.data(), text.size(), tokens.data(), tokens.size(), true, true);
    if (count < 448) throw std::runtime_error("Text needs at least 448 tokens");
    auto prefix = llama_batch_get_one(tokens.data(), 256);
    if (llama_decode(context.get(), prefix)) throw std::runtime_error("Prefill failed");
    struct Batch {
        llama_batch value = llama_batch_init(3, 0, 1);
        ~Batch() { llama_batch_free(value); }
    } batch;
    std::ofstream output(argv[4], std::ios::binary);
    if (!output) throw std::runtime_error("Cannot open output");
    const int vocabulary_size = llama_vocab_n_tokens(vocabulary);
    int position = 256, rows = 0;
    for (int round = 0; rows < 192; ++round) {
        batch.value.n_tokens = std::min(1 + round % 3, 192 - rows);
        for (int i = 0; i < batch.value.n_tokens; ++i) {
            batch.value.token[i] = tokens[position + i];
            batch.value.pos[i] = position + i;
            batch.value.n_seq_id[i] = 1;
            batch.value.seq_id[i][0] = 0;
            batch.value.logits[i] = 1;
        }
        if (llama_decode(context.get(), batch.value)) throw std::runtime_error("Decode failed");
        for (int i = 0; i < batch.value.n_tokens; ++i) {
            const float * logits = llama_get_logits_ith(context.get(), i);
            if (!logits) throw std::runtime_error("Missing logits row");
            for (int token = 0; token < vocabulary_size; ++token)
                if (!std::isfinite(logits[token])) throw std::runtime_error("Non-finite logits");
            output.write(reinterpret_cast<const char *>(logits), vocabulary_size * sizeof(float));
        }
        position += batch.value.n_tokens;
        rows += batch.value.n_tokens;
    }
    output.close();
    if (!output) throw std::runtime_error("Could not write complete logits");
    std::cout << "{\"rows\":" << rows << ",\"vocabulary\":" << vocabulary_size
              << ",\"bytes\":" << size_t(rows) * vocabulary_size * sizeof(float) << "}\n";
} catch (const std::exception & error) {
    std::cerr << error.what() << '\n';
    return 1;
}
