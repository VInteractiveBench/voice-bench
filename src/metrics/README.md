# Metrics

Metric implementations are colocated with the deterministic evaluators:

- `evaluator/policy_gating_evaluator.py`: decision compliance, forbidden-call,
  clarification precision/recall, state-conditioned accuracy, final-state
  correctness, response honesty, and tool-argument accuracy metrics
  (contract in `evaluator/policy_gating_contract.py`).
- `evaluator/fdrc_evaluator.py`: repair uptake, old-intent suppression, forbidden-call,
  cancellation, yield-latency, and FDRC pass metrics.
