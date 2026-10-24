// Replace only eligible PQ2 matvecs; keep the release plugin for every other call.
#include "probe-mmvq.cuh"

#include <atomic>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>

namespace {
struct Counts {
    std::atomic<unsigned long> columns[3]{};
    ~Counts() {
        std::fprintf(stderr, "Bonsai PQ2 row grouping captured calls: one=%lu two=%lu three=%lu\n",
                     columns[0].load(), columns[1].load(), columns[2].load());
    }
} counts;

template <int Columns, int Rows>
void launch(const void * weights, const void * activations, float * output,
            int width, int height, int row_stride, int input_stride, int output_stride,
            cudaStream_t stream) {
    const uint3 one = init_fastdiv_values(1);
    mul_mat_vec_q<GGML_TYPE_PQ2_0, Columns, false, false, false, false, false, 1, Rows>
        <<<dim3(height / Rows), dim3(32, 1), 0, stream>>>(
            weights, activations, nullptr, {}, output, width, one, row_stride,
            input_stride, output_stride, one, 0, 0, 0, one, 0, 0, 0, 0);
}
}

void ggml_cuda_mul_mat_vec_q(ggml_backend_cuda_context & ctx, const ggml_tensor * weights,
                            const ggml_tensor * input, const ggml_tensor * ids,
                            ggml_tensor * output, const ggml_cuda_mm_fusion_args_host * fusion) {
    static const auto original = reinterpret_cast<decltype(&ggml_cuda_mul_mat_vec_q)>(
        dlsym(RTLD_NEXT, "_Z23ggml_cuda_mul_mat_vec_qR25ggml_backend_cuda_contextPK11ggml_tensorS3_S3_PS1_PK29ggml_cuda_mm_fusion_args_host"));
    if (!original) {
        std::fprintf(stderr, "Cannot resolve released PQ2 dispatcher: %s\n", dlerror());
        std::abort();
    }
    static const bool single = [] {
        const char * mode = std::getenv("BONSAI_BUDDY_MATVEC_SINGLE");
        return mode && std::strcmp(mode, "1") == 0;
    }();
    const int columns = output->ne[1];
    const int width = weights->ne[0], height = weights->ne[1];
    const bool selected = columns == 3 ? height >= 4096 :
                          columns == 2 ? height >= 8192 || width >= 8192 :
                          columns == 1 && single && height <= 1024;
    if (!selected || weights->type != GGML_TYPE_PQ2_0 || input->type != GGML_TYPE_F32 ||
        output->type != GGML_TYPE_F32 || ids || fusion || height % 4 || width % 128 ||
        weights->ne[2] != 1 || weights->ne[3] != 1 || input->ne[2] != 1 || input->ne[3] != 1 ||
        output->ne[2] != 1 || output->ne[3] != 1 ||
        !ggml_is_contiguous(weights) || !ggml_is_contiguous(input) || !ggml_is_contiguous(output) ||
        !GGML_CUDA_CC_IS_RDNA2(ggml_cuda_info().devices[ctx.device].cc)) {
        original(ctx, weights, input, ids, output, fusion);
        return;
    }

    const int padded_width = GGML_PAD(width, MATRIX_ROW_PADDING);
    const auto * prepared = ctx.fwht_q8().find(input);
    if (prepared && (prepared->layout != GGML_CUDA_Q8_1_AOS || prepared->ne0 != padded_width ||
                     prepared->ncols != columns)) {
        original(ctx, weights, input, ids, output, fusion);
        return;
    }
    const auto stream = ctx.stream();
    ggml_cuda_pool_alloc<char> quantized(ctx.pool());
    const void * activations;
    if (prepared) {
        activations = prepared->data;
    } else {
        activations = quantized.alloc(size_t(columns) * padded_width / 32 * sizeof(block_q8_1));
        quantize_row_q8_1_cuda(static_cast<const float *>(input->data), nullptr, quantized.get(),
            GGML_CUDA_Q8_1_AOS, width, width, width * columns, width * columns,
            padded_width, columns, 1, 1, stream);
    }
    const int row_stride = weights->nb[1] / sizeof(block_pq2_0);
    if (columns == 1) launch<1, 2>(weights->data, activations, static_cast<float *>(output->data),
        width, height, row_stride, padded_width / 32, height, stream);
    if (columns == 2) launch<2, 4>(weights->data, activations, static_cast<float *>(output->data),
        width, height, row_stride, padded_width / 32, height, stream);
    if (columns == 3) launch<3, 4>(weights->data, activations, static_cast<float *>(output->data),
        width, height, row_stride, padded_width / 32, height, stream);
    counts.columns[columns - 1].fetch_add(1, std::memory_order_relaxed);
}
