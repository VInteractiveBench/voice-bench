# Benchmark Scope

## Context

Vivi-τVoice-CarBench-VN measures whether Vivi preserves VInteractiveBench task capability
when input becomes Vietnamese speech and whether it safely repairs intent before committing
side effects during full-duplex interaction.

## Problem Statement

ASR quality is not a sufficient product metric: a transcript can be imperfect while the
task succeeds, or appear plausible while causing a wrong call, route, vehicle setting, or
media action. The benchmark therefore makes final state and validated official tool
trajectory the pass criterion.

## Technical Scope

| Dimension | MVP constraint |
|---|---|
| Tracks | Text-to-Voice Retention; Full-Duplex Repair-to-Commit |
| Domains | automotive, navigation, media_phone |
| Logical retention tasks | 30, split 10/10/10 |
| Speech overlays | 60 total: 30 retention and 30 FDRC |
| Official whitelist | 25 Vivi tools |
| In-scope tools | 19 tools; excludes six information/search tools |
| Personas | north/central/south × slow/normal/fast |
| Audio conditions | clean, cabin_noise, interaction_stress |
| Scheduler | deterministic 200 ms ticks |

An official-but-excluded tool is `OUT_OF_SCOPE_TOOL_CALL`; a fabricated tool is
`TOOL_NOT_IN_WHITELIST`. This distinction is mandatory because it separates benchmark
scope failure from product hallucination.

## Pass Criteria

Retention requires correct final state, exact expected tool trajectory, valid official
arguments, preserved critical slots, no prohibited side effect, and user-facing
communication. FDRC additionally requires correction uptake, suppression of all forbidden
old-intent calls, cancellation compliance, and yield latency no greater than 700 ms.

## Strategic Constraints

The evaluator is provider-neutral and consumes episode logs rather than binding the
benchmark to a single realtime API. This reduces model-integration coupling while preserving
the latency and event evidence required for full-duplex evaluation.
