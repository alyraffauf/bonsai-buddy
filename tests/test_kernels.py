"""Check attribution of asynchronous GPU work and exclusion of warmup."""

import csv
import tempfile
import unittest
from pathlib import Path

from kernels import active_nanoseconds, summarize


class KernelTraceTests(unittest.TestCase):
    def test_async_dispatches_follow_enqueue_ranges_and_context_filter(self):
        markers = [
            ("llama_decode tokens=1 ctx=target", "1", 10, 20),
            ("llama_decode tokens=1 ctx=target", "1", 30, 40),
            ("unrelated nested marker", "1", 31, 39),
            ("llama_decode tokens=1 ctx=draft", "2", 32, 39),
        ]
        api = [
            ("hipGraphLaunch", "1", "warmup", 12, 18),
            ("hipGraphLaunch", "1", "target", 33, 38),
            ("hipGraphLaunch", "2", "draft", 34, 37),
            ("hipMemcpyAsync", "1", "outside", 41, 42),
        ]
        kernels = [
            ("warmup", "warmup", 15, 25, 40),
            ("target", "matrix", 35, 55, 248),
            ("target", "attention", 50, 60, 40),
            ("draft", "draft", 45, 65, 64),
            ("outside", "copy", 60, 70, 16),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            traces = {
                "marker_api_trace": (
                    ["Function", "Thread_Id", "Start_Timestamp", "End_Timestamp"],
                    markers,
                ),
                "hip_api_trace": (
                    [
                        "Function",
                        "Thread_Id",
                        "Correlation_Id",
                        "Start_Timestamp",
                        "End_Timestamp",
                    ],
                    api,
                ),
                "kernel_trace": (
                    [
                        "Correlation_Id",
                        "Kernel_Name",
                        "Start_Timestamp",
                        "End_Timestamp",
                        "VGPR_Count",
                    ],
                    kernels,
                ),
            }
            for kind, (fields, rows) in traces.items():
                with (directory / f"123_{kind}.csv").open("w", newline="") as output:
                    writer = csv.writer(output)
                    writer.writerow(fields)
                    writer.writerows(rows)
            result = summarize(directory, tokens=1, skip_calls=1, context_index=0)
        self.assertEqual(result["decode_calls"], 1)
        self.assertEqual(result["kernel_dispatches"], 2)
        self.assertEqual(result["kernel_sum_ns"], 30)
        self.assertEqual(result["traced_gpu_active_ns"], 25)
        self.assertEqual(result["traced_gpu_span_ns"], 25)
        self.assertEqual(result["hip_api_ns"], {"hipGraphLaunch": 5})

    def test_active_time_does_not_double_count_nested_or_touching_intervals(self):
        self.assertEqual(
            active_nanoseconds([(10, 30), (12, 15), (30, 40), (50, 60)]), 40
        )
        self.assertEqual(active_nanoseconds([]), 0)


if __name__ == "__main__":
    unittest.main()
