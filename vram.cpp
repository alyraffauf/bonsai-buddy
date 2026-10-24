#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <dlfcn.h>
#include <fstream>
#include <iostream>

int main(int argc, char ** argv) {
    if (argc != 3) {
        std::cerr << "Usage: bonsai-buddy-vram HIP_LIBRARY SYSFS_VRAM_USED\n";
        return 2;
    }
    void * library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) {
        std::cerr << "Cannot load the ROCm memory API\n";
        return 1;
    }
    auto initialize = reinterpret_cast<int (*)(unsigned int)>(dlsym(library, "hipInit"));
    auto set_device = reinterpret_cast<int (*)(int)>(dlsym(library, "hipSetDevice"));
    auto memory_info = reinterpret_cast<int (*)(std::size_t *, std::size_t *)>(dlsym(library, "hipMemGetInfo"));
    std::size_t free_bytes = 0;
    std::size_t total_bytes = 0;
    if (!initialize || !set_device || !memory_info || initialize(0) || set_device(0)
        || memory_info(&free_bytes, &total_bytes) || free_bytes > total_bytes) {
        std::cerr << "Cannot query ROCm memory\n";
        dlclose(library);
        return 1;
    }
    std::uint64_t used_bytes = 0;
    std::ifstream usage(argv[2]);
    if (!(usage >> used_bytes)) {
        std::cerr << "Cannot read physical VRAM usage\n";
        dlclose(library);
        return 1;
    }
    // Read while this query's HIP context is alive, so its allocation cancels out.
    // HIP allocations are already subtracted from hipMemGetInfo; reserve only the rest.
    const auto hip_bytes = static_cast<std::uint64_t>(total_bytes - free_bytes);
    const auto desktop_bytes = used_bytes > hip_bytes ? used_bytes - hip_bytes : 0;
    constexpr std::uint64_t mib = 1024 * 1024;
    std::cout << (desktop_bytes + mib - 1) / mib << '\n';
    dlclose(library);
}
