"""Locust load test against a live, real-stack api -- see tests/perf/README.md.

Not collected by pytest at all (see ../README.md and pyproject.toml's pytest
addopts, which never reference this directory): Locust has its own headless
runner (`uv run locust -f tests/perf/locustfile.py ...`).
"""

from __future__ import annotations

import json
import math
import secrets
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from locust import HttpUser, LoadTestShape, between, events, task
from locust.argument_parser import LocustArgumentParser
from locust.env import Environment
from locust.runners import MasterRunner, WorkerRunner
from locust.stats import StatsEntry, calculate_response_time_percentile

from app.config import get_settings

# NFR-0024's ceilings: p95 latency (ms) per endpoint class, checked at the end of
# the run against environment.stats rather than per-request, since a single slow
# request shouldn't fail a whole load run the way an actual error does
# (--exit-code-on-error, passed on the command line, already covers that).
_P95_LATENCY_MS_CEILING = {"/health/live": 50}
_DEFAULT_P95_LATENCY_MS_CEILING = 200
# NFR-0024 states no p99 ceiling, so capacity mode derives one: this factor times
# the endpoint's p95 ceiling (overridable with --capacity-p99-factor).
_DEFAULT_P99_FACTOR = 2.0
# NFR-0024's error-rate ceiling (0%).
_DEFAULT_MAX_ERROR_RATE = 0.0

_MODE_FIXED = "fixed"
_MODE_CAPACITY = "capacity"
_GENERATOR_CPU_SAMPLE_S = 5.0
_GENERATOR_CPU_WARNING_PERCENT = 90.0

# Peak per-process CPU (percent of one core) of the load generator, sampled while
# the run is live; read by the summary.
_generator_cpu_samples: list[float] = []


def _p95_ceiling(path: str) -> int:
    """Return NFR-0024's p95 ceiling (ms) for an endpoint path."""
    return _P95_LATENCY_MS_CEILING.get(path, _DEFAULT_P95_LATENCY_MS_CEILING)


@events.init_command_line_parser.add_listener  # type: ignore[untyped-decorator] # locust ships no py.typed marker
def _add_arguments(parser: LocustArgumentParser) -> None:
    """Register the perf harness' own command-line arguments (see tests/perf/README.md)."""
    parser.add_argument(
        "--perf-mode",
        choices=[_MODE_FIXED, _MODE_CAPACITY],
        default=_MODE_FIXED,
        env_var="LOCUST_PERF_MODE",
        help=(
            "fixed (default): the NFR-0024 fixed-load check driven by --users/--run-time. "
            "capacity: step users up with a LoadTestShape (--users/--run-time are ignored)."
        ),
    )
    parser.add_argument("--capacity-step-users", type=int, default=10, help="Users added per step")
    parser.add_argument(
        "--capacity-step-duration", type=int, default=120, help="Seconds each step lasts"
    )
    parser.add_argument(
        "--capacity-warmup",
        type=int,
        default=30,
        help="Seconds at the start of each step discarded from that step's numbers",
    )
    parser.add_argument("--capacity-max-users", type=int, default=200, help="Final step's users")
    parser.add_argument(
        "--capacity-spawn-rate", type=float, default=10.0, help="Users spawned per second"
    )
    parser.add_argument(
        "--capacity-p99-factor",
        type=float,
        default=_DEFAULT_P99_FACTOR,
        help="p99 ceiling = this factor x the endpoint's NFR-0024 p95 ceiling",
    )
    parser.add_argument(
        "--capacity-max-error-rate",
        type=float,
        default=_DEFAULT_MAX_ERROR_RATE,
        help="Highest tolerated error rate (0.0-1.0) in a passing step",
    )
    parser.add_argument(
        "--capacity-run-all-steps",
        action="store_true",
        default=False,
        help="Keep stepping after the first failing step instead of stopping there",
    )
    parser.add_argument(
        "--summary-json",
        type=str,
        default="",
        help="Write one JSON summary of the run to this path (default: none)",
    )
    parser.add_argument(
        "--stats-json",
        type=str,
        default="",
        help="API-container resource sampler output (tests/perf/stats.py) to embed in the summary",
    )


def _option[T](environment: Environment, name: str, default: T) -> T:
    """Return a parsed command-line option, or `default` when Locust hasn't parsed any."""
    return getattr(environment.parsed_options, name, default)


_Snapshot = dict[str, tuple[int, int, Counter[int]]]


def _snapshot(environment: Environment) -> _Snapshot:
    """Copy every endpoint's cumulative counters (plus the aggregate under "Aggregated")."""
    snap: _Snapshot = {}
    entries = [(name[0], entry) for name, entry in environment.stats.entries.items()]
    entries.append(("Aggregated", environment.stats.total))
    for path, entry in entries:
        # Several (path, method) entries can share a path; merge them.
        count, failures, times = snap.get(path, (0, 0, Counter()))
        snap[path] = (
            count + entry.num_requests,
            failures + entry.num_failures,
            times + Counter(entry.response_times),
        )
    return snap


def _percentiles(times: Counter[int], count: int) -> tuple[int, int, int]:
    """Return (p50, p95, p99) in ms of a response-time histogram."""
    hist = dict(times)
    return (
        calculate_response_time_percentile(hist, count, 0.5),
        calculate_response_time_percentile(hist, count, 0.95),
        calculate_response_time_percentile(hist, count, 0.99),
    )


def _window(start: _Snapshot, end: _Snapshot, seconds: float) -> dict[str, dict[str, float]]:
    """Per-endpoint stats (plus "Aggregated") for the requests made between two snapshots."""
    result: dict[str, dict[str, float]] = {}
    for path, (count, failures, times) in end.items():
        old_count, old_failures, old_times = start.get(path, (0, 0, Counter[int]()))
        n = count - old_count
        if n <= 0:
            continue
        diff = times - old_times
        p50, p95, p99 = _percentiles(diff, n)
        result[path] = {
            "requests": n,
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "rps": n / seconds if seconds > 0 else 0.0,
            "error_rate": (failures - old_failures) / n,
        }
    return result


def _step_passed(environment: Environment, stats: dict[str, dict[str, float]]) -> bool:
    """Whether a step stayed within NFR-0024's p95, the derived p99 and the error-rate ceilings."""
    if not stats:
        return False
    p99_factor = _option(environment, "capacity_p99_factor", _DEFAULT_P99_FACTOR)
    max_error = _option(environment, "capacity_max_error_rate", _DEFAULT_MAX_ERROR_RATE)
    for path, entry in stats.items():
        if path == "Aggregated":
            continue
        ceiling = _p95_ceiling(path)
        if (
            entry["p95"] > ceiling
            or entry["p99"] > ceiling * p99_factor
            or entry["error_rate"] > max_error
        ):
            return False
    return stats["Aggregated"]["error_rate"] <= max_error


class CapacityShape(LoadTestShape):
    """Step users up, discard each step's warm-up, and record whether each step passed.

    `abstract = True` keeps Locust from auto-picking this class out of the locustfile
    (that would turn on capacity mode for every run); `_enable_capacity_shape` installs
    it on the environment only for `--perf-mode capacity`.
    """

    abstract = True

    def __init__(self, environment: Environment) -> None:
        """Read the step configuration from the parsed command-line options."""
        super().__init__()  # type: ignore[no-untyped-call] # locust ships no py.typed marker
        self.environment = environment
        self.step_users: int = _option(environment, "capacity_step_users", 10)
        self.step_duration: int = _option(environment, "capacity_step_duration", 120)
        self.warmup: int = _option(environment, "capacity_warmup", 30)
        self.max_users: int = _option(environment, "capacity_max_users", 200)
        self.spawn_rate: float = _option(environment, "capacity_spawn_rate", 10.0)
        self.run_all_steps: bool = _option(environment, "capacity_run_all_steps", False)
        if min(self.step_users, self.step_duration, self.max_users) < 1 or not (
            0 <= self.warmup < self.step_duration
        ):
            msg = "capacity mode needs step users/duration/max users >= 1, 0 <= warmup < duration"
            raise ValueError(msg)
        self.n_steps = math.ceil(self.max_users / self.step_users)
        self.steps: list[dict[str, Any]] = []
        self._window_start: tuple[_Snapshot, float] | None = None
        self._failed = False

    def _users(self, step: int) -> int:
        """Return the user count for a 0-based step (the last step is capped at max users)."""
        return min(self.step_users * (step + 1), self.max_users)

    def _finish_step(self, step: int) -> None:
        """Close the step's measurement window and record its result."""
        stats: dict[str, dict[str, float]] = {}
        if self._window_start is not None:
            start, started_at = self._window_start
            stats = _window(start, _snapshot(self.environment), time.perf_counter() - started_at)
        passed = _step_passed(self.environment, stats)
        aggregate = stats.get("Aggregated", {})
        self.steps.append(
            {
                "users": self._users(step),
                "p50": aggregate.get("p50"),
                "p95": aggregate.get("p95"),
                "p99": aggregate.get("p99"),
                "rps": aggregate.get("rps"),
                "error_rate": aggregate.get("error_rate"),
                "passed": passed,
                "endpoints": {k: v for k, v in stats.items() if k != "Aggregated"},
            }
        )
        self._window_start = None
        self._failed = self._failed or not passed

    def tick(self) -> tuple[int, float] | None:
        """Advance the step state machine once per Locust shape tick (about 1 Hz)."""
        elapsed = self.get_run_time()  # type: ignore[no-untyped-call] # locust ships no py.typed marker
        step = int(elapsed // self.step_duration)
        done_steps = len(self.steps)
        if step > done_steps:
            # Ticks are ~1 Hz and steps last longer, so at most one step finishes per tick.
            self._finish_step(done_steps)
            done_steps += 1
        if done_steps >= self.n_steps or (self._failed and not self.run_all_steps):
            return None
        if self._window_start is None and elapsed - done_steps * self.step_duration >= self.warmup:
            self._window_start = (_snapshot(self.environment), time.perf_counter())
        return self._users(done_steps), self.spawn_rate


@events.init.add_listener  # type: ignore[untyped-decorator] # locust ships no py.typed marker
def _enable_capacity_shape(environment: Environment, **_: object) -> None:
    """Install the capacity shape on the master/standalone process for `--perf-mode capacity`."""
    if _option(environment, "perf_mode", _MODE_FIXED) == _MODE_CAPACITY and not isinstance(
        environment.runner, WorkerRunner
    ):
        environment.shape_class = CapacityShape(environment)


def _sample_generator_cpu(environment: Environment) -> None:
    """Record the busiest load-generator process' CPU every few seconds (greenlet body)."""
    while True:
        time.sleep(_GENERATOR_CPU_SAMPLE_S)  # gevent-patched by locust
        runner = environment.runner
        if runner is None:
            continue
        usage = [float(runner.current_cpu_usage)]
        if isinstance(runner, MasterRunner):
            usage += [float(worker.cpu_usage) for worker in runner.clients.values()]
        _generator_cpu_samples.append(max(usage))


@events.test_start.add_listener  # type: ignore[untyped-decorator] # locust ships no py.typed marker
def _start_cpu_sampling(environment: Environment, **_: object) -> None:
    """Start sampling the generator's CPU for the summary (not on workers)."""
    runner = environment.runner
    if runner is not None and not isinstance(runner, WorkerRunner):
        runner.greenlet.spawn(_sample_generator_cpu, environment)


def _generator_cpu_summary(environment: Environment) -> dict[str, Any]:
    """Summarise the load generator's CPU (percent of one core, busiest process per sample)."""
    samples = _generator_cpu_samples
    runner = environment.runner
    return {
        "max": max(samples, default=None),
        "mean": sum(samples) / len(samples) if samples else None,
        "samples": len(samples),
        "workers": len(runner.clients) if isinstance(runner, MasterRunner) else 0,
        "cpu_warning": bool(runner and runner.cpu_warning_emitted)
        or max(samples, default=0.0) > _GENERATOR_CPU_WARNING_PERCENT,
    }


def _endpoint_summary(entry: StatsEntry) -> dict[str, Any]:
    """Return cumulative p50/p95/p99/RPS/error rate for one Locust stats entry."""
    return {
        "requests": entry.num_requests,
        "p50": entry.get_response_time_percentile(0.5),
        "p95": entry.get_response_time_percentile(0.95),
        "p99": entry.get_response_time_percentile(0.99),
        "rps": entry.total_rps,
        "error_rate": entry.fail_ratio,
    }


def _build_summary(environment: Environment) -> dict[str, Any]:
    """Assemble the run's JSON summary (see tests/perf/README.md for the schema)."""
    mode = _option(environment, "perf_mode", _MODE_FIXED)
    endpoints: dict[str, dict[str, Any]] = {}
    for name, entry in environment.stats.entries.items():
        endpoints[f"{name[1]} {name[0]}"] = _endpoint_summary(entry)
    summary: dict[str, Any] = {
        "mode": mode,
        "endpoints": endpoints,
        "aggregate": _endpoint_summary(environment.stats.total),
        "generator_cpu_percent": _generator_cpu_summary(environment),
    }
    shape = environment.shape_class
    if isinstance(shape, CapacityShape):
        summary["steps"] = shape.steps
        passed = [step["users"] for step in shape.steps if step["passed"]]
        summary["max_users_passed"] = max(passed, default=0)
    stats_path = _option(environment, "stats_json", "")
    if stats_path and Path(stats_path).exists():
        try:
            summary["api_resources"] = json.loads(Path(stats_path).read_text())
        except (OSError, ValueError) as exc:
            print(f"Could not embed --stats-json {stats_path}: {exc}")
    return summary


@events.quitting.add_listener  # type: ignore[untyped-decorator] # locust ships no py.typed marker
def _write_summary(environment: Environment, **_: object) -> None:
    """Write --summary-json (if given); in capacity mode, fail if no step passed."""
    if isinstance(environment.runner, WorkerRunner):
        return
    summary = _build_summary(environment)
    if summary["mode"] == _MODE_CAPACITY:
        print(
            f"Capacity: max users within NFR-0024 ceilings = {summary.get('max_users_passed', 0)}"
        )
        if not summary.get("max_users_passed"):
            environment.process_exit_code = 1
    path = _option(environment, "summary_json", "")
    if path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2))


@events.quitting.add_listener  # type: ignore[untyped-decorator] # locust ships no py.typed marker
def _check_latency_thresholds(environment: Environment, **_: object) -> None:
    """Fail the run (NFR-0024) if any endpoint's p95 latency exceeded its ceiling.

    locust's own --exit-code-on-error only covers request errors, not latency, so
    this is the piece that actually enforces NFR-0024's p95 numbers in CI. Skipped
    in capacity mode, where the later steps are expected to breach the ceilings.
    """
    if _option(environment, "perf_mode", _MODE_FIXED) == _MODE_CAPACITY:
        return
    for name, entry in environment.stats.entries.items():
        path = name[0]
        ceiling = _p95_ceiling(path)
        p95 = entry.get_response_time_percentile(0.95)
        if p95 > ceiling:
            print(f"NFR-0024 breach: {name} p95={p95}ms exceeds {ceiling}ms ceiling")
            environment.process_exit_code = 1


# Real Keycloak password-grant login, not POST /mock/token -- this suite targets
# the runner image's MODE=production stack (see docs/adrs/0010-locust-for-load-
# testing.md), and /mock/token is only mounted under MODE=mock (app.controllers.mock).
# Dev-realm password == username, same convention tests/e2e/conftest.py's
# access_token fixture relies on. "maintainer" specifically: each dev-realm user
# carries exactly one client role (realm-export.json), and heroes_v2.py's
# DeleteRoles only grants "maintainer" -- every task below needs read+write+delete.
_LOGIN_USERNAME = "maintainer"

_HERO_LIST_PATH = "/crud/v1/heroes/v2/json"


def _fetch_access_token() -> str:
    """Log in `_LOGIN_USERNAME` against the real dev-realm Keycloak and return their token.

    Duplicates tests/e2e/conftest.py's access_token(dev) branch rather than importing
    it -- tests/e2e/README.md's "Don't" forbids importing across test suites, and this
    suite isn't pytest-collected at all, so it can't share a fixture either way.
    """
    settings = get_settings()
    response = httpx.post(
        settings.oidc_token_url,
        data={
            "grant_type": "password",
            "client_id": settings.oidc_client_id,
            "username": _LOGIN_USERNAME,
            "password": _LOGIN_USERNAME,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["access_token"]  # type: ignore[no-any-return]


class HeroesUser(HttpUser):
    """Simulates one client driving the Hero CRUD resource and the liveness probe."""

    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        """Log in once per simulated user and reuse the resulting bearer token."""
        token = _fetch_access_token()
        self.client.headers["Authorization"] = f"Bearer {token}"

    def _create_hero(self) -> dict[str, Any] | None:
        """Create a throwaway Hero and return its JSON body, or None on failure."""
        payload = {
            "name": f"locust-{uuid.uuid4().hex[:8]}",
            "powers": ["flight"],
        }
        with self.client.post(_HERO_LIST_PATH, json=payload, catch_response=True) as response:
            if response.status_code != 201:
                response.failure(f"unexpected status {response.status_code}")
                return None
            return response.json()  # type: ignore[no-any-return]

    @task(10)
    def list_heroes(self) -> None:
        """List heroes -- the read path most traffic is weighted toward."""
        self.client.get(_HERO_LIST_PATH, name=_HERO_LIST_PATH)

    @task(5)
    def get_hero(self) -> None:
        """Create then fetch a single Hero by id."""
        hero = self._create_hero()
        if hero is None:
            return
        self.client.get(f"{_HERO_LIST_PATH}?id={hero['id']}", name=f"{_HERO_LIST_PATH}?id=")

    @task(3)
    def create_hero(self) -> None:
        """Create a Hero (write path)."""
        self._create_hero()

    @task(2)
    def update_hero(self) -> None:
        """Create then partially update a Hero."""
        hero = self._create_hero()
        if hero is None:
            return
        self.client.patch(
            f"{_HERO_LIST_PATH}?id={hero['id']}",
            json={"powers": [*hero["powers"], secrets.choice(["speed", "strength"])]},
            name=f"{_HERO_LIST_PATH}?id= [PATCH]",
        )

    @task(1)
    def delete_hero(self) -> None:
        """Create then delete a Hero, so load runs don't grow the table unbounded."""
        hero = self._create_hero()
        if hero is None:
            return
        self.client.delete(
            f"{_HERO_LIST_PATH}?id={hero['id']}", name=f"{_HERO_LIST_PATH}?id= [DELETE]"
        )

    @task(8)
    def health_live(self) -> None:
        """Hit the liveness probe -- cheap, unauthenticated, high-frequency traffic."""
        self.client.get("/health/live")
