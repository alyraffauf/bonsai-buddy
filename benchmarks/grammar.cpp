#include "llama.h"

#include <chrono>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>

int main(int argc, char ** argv) {
    if (argc != 3) {
        std::cerr << "Usage: grammar-bench MODEL GRAMMAR\n";
        return 2;
    }
    std::ifstream input(argv[2]);
    if (!input) {
        std::cerr << "Cannot read grammar\n";
        return 2;
    }
    std::string grammar((std::istreambuf_iterator<char>(input)), {});
    llama_log_set([](ggml_log_level, const char *, void *) {}, nullptr);
    auto parameters = llama_model_default_params();
    parameters.vocab_only = true;
    parameters.n_gpu_layers = 0;
    auto * model = llama_model_load_from_file(argv[1], parameters);
    if (!model) {
        std::cerr << "Cannot load model vocabulary\n";
        return 1;
    }
    auto * sampler = llama_sampler_init_grammar(llama_model_get_vocab(model), grammar.c_str(), "root");
    if (!sampler) {
        llama_model_free(model);
        std::cerr << "Cannot create grammar sampler\n";
        return 1;
    }
    for (int repetition = 0; repetition < 10; ++repetition) {
        llama_sampler_free(llama_sampler_clone(sampler));
    }
    constexpr int repetitions = 100;
    auto started = std::chrono::steady_clock::now();
    for (int repetition = 0; repetition < repetitions; ++repetition) {
        llama_sampler_free(llama_sampler_clone(sampler));
    }
    auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
    std::cout << "{\"clones\":" << repetitions << ",\"grammar_bytes\":" << grammar.size()
              << ",\"milliseconds_per_clone\":" << elapsed / repetitions << "}\n";
    llama_sampler_free(sampler);
    llama_model_free(model);
}
