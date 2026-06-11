# Metrics

Metric implementations are colocated with the deterministic evaluators:

- `evaluator/retention_evaluator.py`: text, clean voice, cabin voice, retention, degradation,
  and critical-slot metrics.
- `evaluator/fdrc_evaluator.py`: repair uptake, old-intent suppression, forbidden-call,
  cancellation, yield-latency, and FDRC pass metrics.
