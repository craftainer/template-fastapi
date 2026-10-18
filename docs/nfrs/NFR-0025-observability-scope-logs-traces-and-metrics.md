# NFR-0025. Observability covers logs, traces and metrics, opt-in and low-overhead

## Status

Proposed

## Attribute

Observability / performance.

## Description

This requirement supersedes [`NFR-0023`](NFR-0023-observability-scope-logs-only.md)
(logs only). The service shall:

- always emit structured JSON logs to stdout, as before;
- when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, export logs, traces and
  metrics over OTLP, configured only through OpenTelemetry's standard
  environment variables; when it is unset, no telemetry code path runs
  and behaviour is unchanged;
- never expose a Prometheus `/metrics` endpoint;
- attach `trace_id` and `span_id` to log lines when a span is active,
  and the request ID to the active span;
- carry `service.name` and `service.version` (from `APP_VERSION`) on all
  signals;
- keep health probes out of traces;
- cost no more than `TBD`% api CPU per request at the 1 vCPU / 2 GB
  reference budget with the recommended sampling rate, measured against
  telemetry unset.

## Source

Operators/SRE, preparing a Kubernetes deployment with OpenTelemetry
feeding Prometheus-compatible tools. Prompted and detailed by
[`ADR-0021`](../adrs/0021-opentelemetry-traces-and-metrics-pushed-over-otlp.md);
measurement method from
[`ADR-0019`](../adrs/0019-per-pr-benchmarks-and-fixed-load-acceptance.md).

## Verification

Unit tests with OTel's in-memory exporters (spans, metrics, excluded
health routes, log correlation, no-op when unset); the e2e suite run with
tracing enabled; the overhead budget measured with the `tests/perf/`
harness in three modes (unset, 100% sampling, 10% sampling) before this
requirement moves to Accepted. Code review: no `/metrics` endpoint and no
OTel settings re-modelled on `Settings`.
