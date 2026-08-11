# Phase-two module capability evaluation report

Run date: 2026-08-11

Evaluated implementation: `b105835`

Runner: `scripts/run_module_capability_evals.py`

Command: `uv run python scripts/run_module_capability_evals.py --output-dir evaluation-results/phase-two-v1 --repetitions 3`

Seed: `20260810`

Grading: strict task-level pass/fail

## Scope and interpretation

This run evaluates three LCAH modules directly: context compression, durable
memory, and checkpoint recovery. Every module has 16 tasks (4 basic, 6
composite, and 6 adversarial), and every task is repeated three times for each
production, control, and mutation variant.

These are deterministic module-capability results. They demonstrate that the
module benchmark is calibrated and regression-sensitive. They do **not** mean
that the complete coding agent succeeds on 75%–81.25% of real repository tasks;
that claim requires the later end-to-end task-quality benchmark.

## Production results

| Module | Production variant | Passed tasks | Strict pass rate | Basic | Composite | Adversarial | 95% task-bootstrap CI |
|---|---|---:|---:|---:|---:|---:|---:|
| Context compression | `lcah_compression` | 12/16 | 75.00% | 100% | 100% | 33.33% | 56.25%–93.75% |
| Memory | `memory_on` | 12/16 | 75.00% | 100% | 100% | 33.33% | 56.25%–93.75% |
| Checkpoint recovery | `checkpoint_resume` | 13/16 | 81.25% | 100% | 100% | 50.00% | 62.50%–100% |

All three production scores are inside the intended 60%–85% calibration band.
The three repetitions agree for every task, as expected from the deterministic
module-direct runner.

## Production failures

### Context compression

- `c13-conflicting-decisions`: retained a stale decision.
- `c14-resolved-blocker`: retained a resolved failure.
- `c15-revoked-constraint`: retained a revoked constraint.
- `c16-repeated-compaction`: lost critical state after summary-of-summary compression.

### Memory

- `m13-implicit`: lexical retrieval did not resolve an implicit query.
- `m14-joint4`: the retrieval limit omitted one of four required memories.
- `m15-malicious`: instruction-shaped content was persisted.
- `m16-repo-scope`: repository scope was not represented during retrieval.

### Checkpoint recovery

- `r13-event-gap`: durable event continuity was missing.
- `r14-result-gap`: post-checkpoint tool-result evidence was missing.
- `r16-partial-damage`: a partially damaged checkpoint was not safely rejected.

`r15-compatible-change` passes in the actual production run; the manifest's
`expected_current_result` field is audit metadata only and does not affect
grading.

## Control comparisons

| Module | Production | Weak control | Production rate | Control rate | Paired delta |
|---|---|---|---:|---:|---:|
| Context compression | `lcah_compression` | `tail_truncation` | 75.00% | 0.00% | -75.00 pp |
| Memory | `memory_on` | `memory_disabled` | 75.00% | 31.25% | -43.75 pp |
| Checkpoint recovery | `checkpoint_resume` | `lossy_resume` | 81.25% | 31.25% | -50.00 pp |

The expected direction is detected for all three paired comparisons.

## Mutation sensitivity

| Module | Mutation | Flipped production passes | Mutated rate | Delta |
|---|---|---|---:|---:|
| Compression | `drop_commands` | `c04-command`, `c09-joint-state` | 62.50% | -12.50 pp |
| Compression | `latest_decision_only_bug` | `c03-path`, `c07-decision` | 62.50% | -12.50 pp |
| Compression | `reduce_recent_turns` | `c02-constraint` | 68.75% | -6.25 pp |
| Compression | `skip_stale_cleanup` | `c05-outcome`, `c06-blocker` | 62.50% | -12.50 pp |
| Memory | `disable_conflict_replacement` | `m05-update`, `m11-update-preference` | 62.50% | -12.50 pp |
| Memory | `retrieval_limit_one` | `m10-joint2` | 68.75% | -6.25 pp |
| Memory | `similar_distractor_injection` | `m07-distractor`, `m09-scale10` | 62.50% | -12.50 pp |
| Memory | `skip_forbidden_filter` | `m03-secret`, `m06-transient` | 62.50% | -12.50 pp |
| Recovery | `drop_todos` | `r03-todo` | 75.00% | -6.25 pp |
| Recovery | `ignore_schema_mismatch` | `r07-schema` | 75.00% | -6.25 pp |
| Recovery | `replay_committed_operation` | `r08-exactly-once` | 75.00% | -6.25 pp |
| Recovery | `skip_freshness_check` | `r06-freshness`, `r12-consecutive-stale` | 68.75% | -12.50 pp |

All 12 small mutations are detected. Each flips one or two production passes
and changes the strict score by 6.25–12.50 percentage points.

## Machine-readable evidence

- `module-capability-summary.json`: consolidated scores, confidence intervals,
  controls, difficulty slices, module metrics, and mutation checks.
- `compression-capability.json`: 336 attempt records with inputs, outputs,
  diagnostics, grader evidence, seeds, timings, and failure categories.
- `memory-capability.json`: 336 attempt records in the same schema.
- `recovery-capability.json`: 336 attempt records in the same schema.

Temporary isolated workspaces are deliberately excluded. They are execution
scratch data, not evaluation evidence, and can be regenerated from the task
manifests, seeds, runner, and recorded configuration.

## Phase-two completion decision

Phase two is complete for the agreed module-evaluation scope because the
benchmark definitions, strict grader, repeatable runner, per-attempt evidence,
aggregate analysis, control comparisons, calibrated production scores, and
mutation-sensitivity proof are all present and internally consistent.

End-to-end coding-task quality remains a separate next phase.
