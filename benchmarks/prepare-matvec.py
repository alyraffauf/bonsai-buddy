"""Expose the pinned upstream matvec kernel with experimental geometry parameters."""

import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
source = source.split("// Dedicated MoE multi-token kernel.", 1)[0]
changes = {
    "bool y_soa = false>\n__launch_bounds__(calc_nwarps": "bool y_soa = false, int probe_warps = 0, int probe_rows = 0, int probe_unroll = 1>\n__launch_bounds__((probe_warps ? probe_warps : calc_nwarps",
    "small_k, halve_iters)*ggml_cuda_get_physical_warp_size(), 1)": "small_k, halve_iters))*ggml_cuda_get_physical_warp_size(), 1)",
    "constexpr int nwarps = calc_nwarps(type, ncols_dst, table_id, small_k, halve_iters);": "constexpr int nwarps = probe_warps ? probe_warps : calc_nwarps(type, ncols_dst, table_id, small_k, halve_iters);",
    "constexpr int rows_per_cuda_block = calc_rows_per_block(type, ncols_dst, table_id, small_k, nwarps);": "constexpr int rows_per_cuda_block = probe_rows ? probe_rows : calc_rows_per_block(type, ncols_dst, table_id, small_k, nwarps);",
    "    } else {\n        for (int kbx = tid / (qi/vdr);": "    } else {\n#pragma unroll probe_unroll\n        for (int kbx = tid / (qi/vdr);",
}
for original, replacement in changes.items():
    if source.count(original) != 1:
        raise ValueError(f"Expected one upstream match: {original!r}")
    source = source.replace(original, replacement)
Path(sys.argv[2]).write_text(source)
