"""Summarize rocprofv3 kernels enqueued by selected llama_decode calls."""

import argparse
import bisect
import csv
import json
import re
from collections import Counter
from pathlib import Path

from common import positive_integer


def read_trace(directory, kind):
    paths = list(directory.rglob(f"*_{kind}.csv"))
    if len(paths) != 1:
        raise ValueError(f"Expected one {kind} CSV in {directory}, found {len(paths)}")
    with paths[0].open(newline="") as source:
        return list(csv.DictReader(source))


def active_nanoseconds(intervals):
    """Count overlapping kernel intervals once."""
    ordered = sorted(intervals)
    if not ordered:
        return 0
    active = 0
    start, stop = ordered[0]
    for next_start, next_stop in ordered[1:]:
        if next_start > stop:
            active += stop - start
            start = next_start
        stop = max(stop, next_stop)
    return active + stop - start


def summarize(directory, *, tokens, skip_calls=0, last_calls=None, context_index=None):
    marker_pattern = re.compile(r"llama_decode tokens=(\d+) ctx=(\S+)")
    markers = sorted(
        (
            row
            for row in read_trace(directory, "marker_api_trace")
            if marker_pattern.fullmatch(row["Function"])
        ),
        key=lambda row: int(row["Start_Timestamp"]),
    )
    selected = []
    contexts = []
    for index, marker in enumerate(markers):
        match = marker_pattern.fullmatch(marker["Function"])
        if not match:
            continue
        if match[2] not in contexts:
            contexts.append(match[2])
        if int(match[1]) == tokens and (
            context_index is None or contexts.index(match[2]) == context_index
        ):
            selected.append(index)
    selected = selected[skip_calls:]
    if last_calls is not None:
        selected = selected[-last_calls:]
    if not selected:
        raise ValueError("No matching llama_decode ranges after filtering")

    # GPU work can finish after the host range ends. Match dispatches through
    # their HIP enqueue correlation IDs, rather than clipping GPU timestamps.
    thread_ranges = {}
    for index, marker in enumerate(markers):
        thread_ranges.setdefault(marker["Thread_Id"], []).append(index)
    thread_starts = {
        thread: [int(markers[index]["Start_Timestamp"]) for index in ranges]
        for thread, ranges in thread_ranges.items()
    }
    correlations = set()
    api_durations = Counter()
    selected_set = set(selected)
    for row in read_trace(directory, "hip_api_trace"):
        start = int(row["Start_Timestamp"])
        ranges = thread_ranges.get(row["Thread_Id"], [])
        starts = thread_starts.get(row["Thread_Id"], [])
        position = bisect.bisect_right(starts, start) - 1
        if position < 0:
            continue
        index = ranges[position]
        if index not in selected_set:
            continue
        marker = markers[index]
        if (
            start >= int(marker["End_Timestamp"])
            or row["Thread_Id"] != marker["Thread_Id"]
        ):
            continue
        correlations.add(row["Correlation_Id"])
        api_durations[row["Function"]] += int(row["End_Timestamp"]) - start

    durations = Counter()
    calls = Counter()
    registers = {}
    intervals = []
    for row in read_trace(directory, "kernel_trace"):
        if row["Correlation_Id"] not in correlations:
            continue
        name = row["Kernel_Name"]
        start, stop = int(row["Start_Timestamp"]), int(row["End_Timestamp"])
        durations[name] += stop - start
        calls[name] += 1
        registers[name] = int(row["VGPR_Count"])
        intervals.append((start, stop))
    if not intervals:
        raise ValueError("No kernels correlate with the selected decode calls")

    total = sum(durations.values())
    return {
        "tokens_per_call": tokens,
        "context_index": context_index,
        "decode_calls": len(selected),
        "kernel_dispatches": sum(calls.values()),
        "traced_gpu_span_ns": max(stop for _, stop in intervals)
        - min(start for start, _ in intervals),
        "traced_gpu_active_ns": active_nanoseconds(intervals),
        "kernel_sum_ns": total,
        "kernels": [
            {
                "name": name,
                "calls": calls[name],
                "total_ns": duration,
                "percent_kernel_time": 100 * duration / total,
                "vgpr_count": registers[name],
            }
            for name, duration in durations.most_common()
        ],
        "hip_api_ns": dict(api_durations.most_common()),
    }


def nonnegative_integer(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("Must be nonnegative")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--tokens", type=positive_integer, required=True)
    parser.add_argument("--skip-calls", type=nonnegative_integer, default=0)
    parser.add_argument("--last-calls", type=positive_integer)
    parser.add_argument("--context-index", type=nonnegative_integer)
    options = parser.parse_args()
    try:
        result = summarize(
            options.directory,
            tokens=options.tokens,
            skip_calls=options.skip_calls,
            last_calls=options.last_calls,
            context_index=options.context_index,
        )
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
