// Annotate host enqueue ranges without synchronizing or changing model execution.
#include "llama.h"
#include <rocprofiler-sdk-roctx/roctx.h>

#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>

extern "C" int32_t llama_decode(llama_context * ctx, llama_batch batch) {
    static auto decode = reinterpret_cast<decltype(&llama_decode)>(dlsym(RTLD_NEXT, "llama_decode"));
    if (!decode) {
        std::fprintf(stderr, "Cannot resolve llama_decode: %s\n", dlerror());
        std::abort();
    }

    char label[128];
    std::snprintf(label, sizeof(label), "llama_decode tokens=%d ctx=%p", batch.n_tokens, static_cast<void *>(ctx));
    roctxRangePushA(label);
    const auto result = decode(ctx, batch);
    roctxRangePop();
    return result;
}
