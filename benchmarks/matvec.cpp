// Untraced, cache-defeating comparisons of pinned PQ2 kernels on real weights.
#include "probe-mmvq.cuh"
#include "gguf.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

static void check(hipError_t status) {
    if (status != hipSuccess) {
        throw std::runtime_error(hipGetErrorString(status));
    }
}

struct DeviceBuffer {
    void * data = nullptr;
    explicit DeviceBuffer(size_t bytes) { check(hipMalloc(&data, bytes)); }
    ~DeviceBuffer() { hipFree(data); }
    DeviceBuffer(const DeviceBuffer &) = delete;
    DeviceBuffer & operator=(const DeviceBuffer &) = delete;
};

struct Timer {
    hipEvent_t start, end;
    Timer() { check(hipEventCreate(&start)); check(hipEventCreate(&end)); }
    ~Timer() { hipEventDestroy(start); hipEventDestroy(end); }
    template <typename Function> double run(Function operation) {
        check(hipEventRecord(start));
        operation();
        check(hipEventRecord(end));
        check(hipEventSynchronize(end));
        float milliseconds;
        check(hipEventElapsedTime(&milliseconds, start, end));
        return milliseconds;
    }
};

__global__ static void stream_read(const float4 * input, size_t count, float * output) {
    float sum = 0;
    for (size_t i = blockIdx.x * blockDim.x + threadIdx.x; i < count; i += gridDim.x * blockDim.x) {
        float4 value = input[i];
        sum += value.x + value.y + value.z + value.w;
    }
    __shared__ float sums[256];
    sums[threadIdx.x] = sum;
    __syncthreads();
    for (int stride = 128; stride; stride /= 2) {
        if (threadIdx.x < stride) sums[threadIdx.x] += sums[threadIdx.x + stride];
        __syncthreads();
    }
    if (threadIdx.x == 0) output[blockIdx.x] = sums[0];
}

template <int Columns, int Warps, int Rows, int Unroll = 1>
static void generic(const void * weights, const void * activations, float * output, int width, int height) {
    const uint3 one = init_fastdiv_values(1);
    mul_mat_vec_q<GGML_TYPE_PQ2_0, Columns, false, false, false, false, false, Warps, Rows, Unroll>
        <<<dim3((height + Rows - 1) / Rows), dim3(32, Warps)>>>(
            weights, activations, nullptr, {}, output, width, one, width / 128, width / 32,
            height, one, 0, 0, 0, one, 0, 0, 0, 0);
}

using Launch = void (*)(const void *, const void *, float *, int, int);
struct Candidate { const char * name; Launch launch; bool planar = false; };
static ggml_backend_cuda_context * release_context;

template <int Columns>
static void planar(const void * weights, const void * activations, float * output, int width, int height) {
    mul_mat_vec_pq2_0_mc_launch<Columns>(weights, activations, output, width, height,
                                      width / 128, width / 32, height, nullptr);
}

template <int Columns>
static void released(const void * weights, const void * activations, float * output, int width, int height) {
    ggml_tensor matrix{}, input{}, result{};
    matrix.type = GGML_TYPE_PQ2_0;
    matrix.ne[0] = width; matrix.ne[1] = height;
    input.type = result.type = GGML_TYPE_F32;
    input.ne[0] = width; input.ne[1] = Columns;
    result.ne[0] = height; result.ne[1] = Columns;
    ggml_cuda_op_mul_mat_vec_q(*release_context, &matrix, &input, &result,
        static_cast<const char *>(weights), nullptr, static_cast<const char *>(activations),
        output, 0, height, Columns, width, nullptr);
}

template <int Columns>
static void measure(const void * weights, const void * activations, const void * planar_activations,
                    int width, int height, size_t weight_bytes, int rotations, int repeats) {
    const Candidate candidates[] = {
        {"release", released<Columns>},
        {"w1-r1", generic<Columns, 1, 1>},
        {"w2-r1", generic<Columns, 2, 1>},
        {"w4-r1", generic<Columns, 4, 1>},
        {"w8-r1", generic<Columns, 8, 1>},
        {"w1-r2", generic<Columns, 1, 2>},
        {"w2-r2", generic<Columns, 2, 2>},
        {"w4-r2", generic<Columns, 4, 2>},
        {"w1-r4", generic<Columns, 1, 4>},
        {"w2-r4", generic<Columns, 2, 4>},
        {"w1-r1-u2", generic<Columns, 1, 1, 2>},
        {"w1-r1-u4", generic<Columns, 1, 1, 4>},
        {"planar-r4", planar<Columns>, true},
    };
    const size_t output_bytes = size_t(Columns) * height * sizeof(float);
    DeviceBuffer output(output_bytes);
    std::vector<float> reference(size_t(Columns) * height), actual(reference.size());
    candidates[0].launch(weights, activations, static_cast<float *>(output.data), width, height);
    check(hipMemcpy(reference.data(), output.data, output_bytes, hipMemcpyDeviceToHost));
    for (int column = 0; column < Columns; ++column) {
        double energy = 0;
        for (int row = 0; row < height; ++row) {
            const float value = reference[size_t(column) * height + row];
            energy += double(value) * value;
        }
        if (!(energy > 1e-20)) throw std::runtime_error("Degenerate reference column");
    }
    Timer timer;
    constexpr int cycles = 4;
    const auto run_bank = [&](const Candidate & candidate) {
        const void * input = candidate.planar ? planar_activations : activations;
        for (int cycle = 0; cycle < cycles; ++cycle) {
            for (int rotation = 0; rotation < rotations; ++rotation) {
                const auto * bank = static_cast<const char *>(weights) + rotation * weight_bytes;
                candidate.launch(bank, input, static_cast<float *>(output.data), width, height);
            }
        }
    };
    for (int warmup = 0; warmup < 8; ++warmup) timer.run([&] { run_bank(candidates[0]); });
    for (const auto & candidate : candidates) {
        const void * input = candidate.planar ? planar_activations : activations;
        check(hipMemset(output.data, 0xff, output_bytes));
        candidate.launch(weights, input, static_cast<float *>(output.data), width, height);
        check(hipMemcpy(actual.data(), output.data, output_bytes, hipMemcpyDeviceToHost));
        size_t different = 0;
        double squared_error = 0, squared_reference = 0, maximum_error = 0;
        for (size_t i = 0; i < actual.size(); ++i) {
            if (!std::isfinite(actual[i]) || !std::isfinite(reference[i])) throw std::runtime_error("Non-finite output");
            different += std::memcmp(&actual[i], &reference[i], sizeof(float)) != 0;
            const double error = double(actual[i]) - reference[i];
            squared_error += error * error;
            squared_reference += double(reference[i]) * reference[i];
            maximum_error = std::max(maximum_error, std::abs(error));
        }
        const double relative_error = std::sqrt(squared_error / std::max(squared_reference, 1e-30));
        if (relative_error > 1e-5) throw std::runtime_error(std::string("Numerical gate failed: ") + candidate.name);
        timer.run([&] { run_bank(candidate); });
        // Every timed arm streams all rotating copies. Reverse candidate/control order each pair.
        double baseline_ms = 0, candidate_ms = 0;
        for (int pair = 0; pair < repeats; ++pair) {
            double times[2];
            for (int arm = 0; arm < 2; ++arm) {
                const bool control = ((arm + pair) % 2) == 0;
                const auto & selected = control ? candidates[0] : candidate;
                times[control ? 0 : 1] = timer.run([&] { run_bank(selected); });
            }
            baseline_ms += times[0]; candidate_ms += times[1];
            std::printf("{\"kind\":\"pair\",\"columns\":%d,\"candidate\":\"%s\",\"pair\":%d,\"baseline_ms\":%.6f,\"candidate_ms\":%.6f}\n",
                        Columns, candidate.name, pair, times[0], times[1]);
        }
        std::printf("{\"kind\":\"summary\",\"columns\":%d,\"candidate\":\"%s\",\"speedup\":%.6f,\"GBps\":%.3f,\"different\":%zu,\"values\":%zu,\"relative_l2\":%.9g,\"max_abs\":%.9g}\n",
                    Columns, candidate.name, baseline_ms / candidate_ms,
                    double(weight_bytes) * rotations * cycles * repeats / candidate_ms / 1e6,
                    different, actual.size(), relative_error, maximum_error);
        std::fflush(stdout);
    }
}

int main(int argc, char ** argv) try {
    if (argc < 2) throw std::runtime_error("Usage: bonsai-matvec-probe MODEL [TENSOR [PAIRS]] | bandwidth");
    check(hipSetDevice(0));
    ggml_cuda_info();
    auto context = std::make_unique<ggml_backend_cuda_context>(0);
    release_context = context.get();
    if (std::string(argv[1]) == "bandwidth") {
        Timer timer;
        for (size_t bytes : {size_t(512) << 20, size_t(1024) << 20, size_t(2048) << 20}) {
            DeviceBuffer input(bytes), output(4096 * sizeof(float));
            check(hipMemset(input.data, 1, bytes));
            for (int repeat = 0; repeat < 7; ++repeat) {
                const double milliseconds = timer.run([&] {
                    stream_read<<<4096, 256>>>(static_cast<const float4 *>(input.data), bytes / sizeof(float4), static_cast<float *>(output.data));
                });
                std::printf("{\"kind\":\"bandwidth\",\"bytes\":%zu,\"repeat\":%d,\"ms\":%.6f,\"GBps\":%.3f}\n",
                            bytes, repeat, milliseconds, bytes / milliseconds / 1e6);
            }
        }
        return 0;
    }
    ggml_context * tensors = nullptr;
    gguf_context * metadata = gguf_init_from_file(argv[1], {true, &tensors});
    if (!metadata) throw std::runtime_error("Cannot read GGUF");
    if (argc == 2) {
        for (int64_t i = 0; i < gguf_get_n_tensors(metadata); ++i) {
            const auto * tensor = ggml_get_tensor(tensors, gguf_get_tensor_name(metadata, i));
            if (tensor->type == GGML_TYPE_PQ2_0 || tensor->type == GGML_TYPE_Q8_0)
                std::printf("%s %s %lld %lld\n", tensor->name, ggml_type_name(tensor->type),
                            (long long) tensor->ne[0], (long long) tensor->ne[1]);
        }
        gguf_free(metadata); ggml_free(tensors);
        return 0;
    }
    const int64_t index = gguf_find_tensor(metadata, argv[2]);
    if (index < 0) throw std::runtime_error("Unknown tensor");
    const auto * tensor = ggml_get_tensor(tensors, argv[2]);
    if (tensor->type != GGML_TYPE_PQ2_0 || ggml_n_dims(tensor) != 2 ||
        tensor->ne[0] % 128 || tensor->ne[1] % 4)
        throw std::runtime_error("Expected a PQ2 matrix with width divisible by 128 and height divisible by 4");
    const size_t bytes = ggml_nbytes(tensor);
    const int rotations = std::max(4, int(((size_t(512) << 20) + bytes - 1) / bytes));
    std::vector<char> host_weights(bytes);
    std::ifstream model(argv[1], std::ios::binary);
    model.seekg(gguf_get_data_offset(metadata) + gguf_get_tensor_offset(metadata, index));
    if (!model.read(host_weights.data(), bytes)) throw std::runtime_error("Truncated tensor");
    DeviceBuffer weights(bytes * rotations);
    for (int i = 0; i < rotations; ++i)
        check(hipMemcpy(static_cast<char *>(weights.data) + i * bytes, host_weights.data(), bytes, hipMemcpyHostToDevice));
    const int width = tensor->ne[0], height = tensor->ne[1];
    std::printf("{\"kind\":\"tensor\",\"name\":\"%s\",\"width\":%d,\"height\":%d,\"bytes\":%zu,\"rotations\":%d,\"working_set\":%zu,\"cycles_per_arm\":4}\n",
                argv[2], width, height, bytes, rotations, bytes * rotations);
    std::vector<float> host_input(size_t(width) * 3);
    std::mt19937 generator(1);
    std::uniform_real_distribution<float> distribution(-1.0f, 1.0f);
    for (size_t i = 0; i < host_input.size(); ++i)
        host_input[i] = distribution(generator);
    DeviceBuffer input(host_input.size() * sizeof(float));
    DeviceBuffer quantized(size_t(width / 32) * 3 * sizeof(block_q8_1));
    DeviceBuffer planar_quantized(size_t(width / 32) * 3 * sizeof(block_q8_1));
    check(hipMemcpy(input.data, host_input.data(), host_input.size() * sizeof(float), hipMemcpyHostToDevice));
    for (auto layout : {GGML_CUDA_Q8_1_AOS, GGML_CUDA_Q8_1_PQ2}) {
        quantize_row_q8_1_cuda(static_cast<float *>(input.data), nullptr,
            layout == GGML_CUDA_Q8_1_PQ2 ? planar_quantized.data : quantized.data,
            layout, width, width, 0, 0, width, 3, 1, 1, nullptr);
    }
    check(hipDeviceSynchronize());
    const int repeats = argc > 3 ? std::stoi(argv[3]) : 6;
    if (repeats < 1 || repeats > 100) throw std::runtime_error("PAIRS must be 1..100");
    measure<1>(weights.data, quantized.data, planar_quantized.data, width, height, bytes, rotations, repeats);
    measure<2>(weights.data, quantized.data, planar_quantized.data, width, height, bytes, rotations, repeats);
    measure<3>(weights.data, quantized.data, planar_quantized.data, width, height, bytes, rotations, repeats);
    gguf_free(metadata); ggml_free(tensors);
} catch (const std::exception & error) {
    std::fprintf(stderr, "%s\n", error.what());
    return 1;
}
