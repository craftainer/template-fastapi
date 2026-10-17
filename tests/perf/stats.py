"""Sample a container's CPU and memory with ``docker stats`` during a load run.

Usage::

    uv run python tests/perf/stats.py --container <name-or-id> \
        --interval 2 --out tests/perf/.results/stats.json [--duration 120]

Runs until SIGINT/SIGTERM (or ``--duration`` seconds), then writes one JSON
file: ``{"container", "interval_s", "samples": [{"t", "cpu_percent",
"mem_bytes"}], "summary": {"cpu_percent": {"mean", "p95", "max"},
"mem_bytes": {"mean", "max"}}}``.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Any

_UNITS: dict[str, int] = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}
_SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([A-Za-z]+)\s*$")


def parse_size(text: str) -> int:
    """Parse docker's human size (e.g. ``512.3MiB``, ``1.5GB``) into bytes."""
    match = _SIZE_RE.match(text)
    if match is None or match.group(2).lower() not in _UNITS:
        raise ValueError(f"unrecognised size: {text!r}")
    return int(float(match.group(1)) * _UNITS[match.group(2).lower()])


def parse_stats_line(line: str, now: float) -> dict[str, float | int]:
    """Turn one ``docker stats --format '{{json .}}'`` object into a sample."""
    row: dict[str, Any] = json.loads(line)
    used = str(row["MemUsage"]).split("/", 1)[0]
    return {
        "t": now,
        "cpu_percent": float(str(row["CPUPerc"]).strip().rstrip("%")),
        "mem_bytes": parse_size(used),
    }


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(samples: list[dict[str, float | int]]) -> dict[str, dict[str, float | int]]:
    """Aggregate samples into the ``summary`` block."""
    cpu = [float(s["cpu_percent"]) for s in samples]
    mem = [int(s["mem_bytes"]) for s in samples]
    return {
        "cpu_percent": {
            "mean": sum(cpu) / len(cpu) if cpu else 0.0,
            "p95": percentile(cpu, 95),
            "max": max(cpu, default=0.0),
        },
        "mem_bytes": {
            "mean": sum(mem) / len(mem) if mem else 0.0,
            "max": max(mem, default=0),
        },
    }


def sample_once(container: str) -> dict[str, float | int]:
    """Take one ``docker stats --no-stream`` reading."""
    out = subprocess.run(  # noqa: S603 -- fixed docker argv, container is the operator's own CLI arg
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", container],  # noqa: S607 -- docker from PATH, as in the devcontainer
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return parse_stats_line(out.strip().splitlines()[0], time.time())


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--container", required=True, help="container name or id")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between samples")
    parser.add_argument("--out", required=True, type=Path, help="output JSON path")
    parser.add_argument("--duration", type=float, default=None, help="stop after N seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Sample until stopped, then write the JSON file; return the exit code."""
    args = build_parser().parse_args(argv)
    stop = False

    def _stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    samples: list[dict[str, float | int]] = []
    started = time.monotonic()
    while not stop:
        # `docker stats --no-stream` itself takes ~1-2 s, so sleep only the rest.
        tick = time.monotonic()
        try:
            samples.append(sample_once(args.container))
        except subprocess.CalledProcessError as exc:
            print(f"docker stats failed: {exc.stderr.strip()}", file=sys.stderr)
            return 1
        if args.duration is not None and time.monotonic() - started >= args.duration:
            break
        deadline = tick + args.interval
        while not stop and time.monotonic() < deadline:
            time.sleep(max(0.0, min(0.2, deadline - time.monotonic())))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "container": args.container,
                "interval_s": args.interval,
                "samples": samples,
                "summary": summarize(samples),
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
