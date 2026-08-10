# LCAH Evaluation Methodology

## 1. Why the evaluation system was rebuilt

The original LCAH benchmark contained 32 deterministic tasks driven by
`ScriptedModelClient`. Those tasks are useful for verifying tool plumbing,
workspace isolation, artifacts, stop reasons, and verifier execution. They do
not measure whether a live coding agent can discover and complete a task.

The rebuilt system therefore treats the old suite as
`deterministic_harness_regression` and writes
`capability_claims_allowed: false` into its artifacts. Capability claims must
come from separate module or end-to-end evaluations.

## 2. Evaluation layers

LCAH uses four evaluation layers with different purposes:

| Layer | Purpose | Typical frequency |
| --- | --- | --- |
| L0 deterministic regression | Detect broken harness, artifact, tool, and verifier mechanics | Every pull request |
| L1 module capability | Isolate compression, memory, and recovery behavior | Pull request or nightly |
| L2 end-to-end coding tasks | Measure live model-agent task completion | Weekly or release |
| L3 public benchmark calibration | Compare with external agent systems | Release |

The layers must not be collapsed into one score. A harness regression pass is
not a coding capability result, and a module capability result is not an
end-to-end agent score.

## 3. Phase one: trustworthy evaluation infrastructure

Phase one provides the shared measurement protocol.

### Versioned contracts

`TaskManifest` defines dataset identity, task prompt, fixture, grader, family,
difficulty, capabilities, audit metadata, and mutation targets.

`AttemptRecord` records:

- experiment, dataset, task, variant, attempt index, and seed;
- agent, model, provider, budgets, and feature flags;
- initial and final workspace hashes;
- strict outcome and failure category;
- usage, relative artifact paths, and diagnostics.

Absolute artifact paths are rejected so artifacts remain portable. Workspace
hashes exclude `.lcah` run output and describe agent-visible repository state.

### Repeated and paired execution

Experiments run every `(variant, task, attempt)` combination with deterministic
seed derivation. The same task and attempt receive the same seed across
variants. Completed attempts can be resumed from an atomically written JSON
artifact, while one runner error is isolated instead of aborting the batch.

This permits causal module comparisons such as compression-on versus
compression-off without changing the task, seed, budget, or grader.

### Statistics

The analysis layer reports:

- attempt pass rate;
- pass@1;
- strict repeated reliability (`pass^k`);
- task-level bootstrap 95% confidence intervals;
- cost per successful attempt;
- failure-category counts;
- paired wins, losses, ties, and treatment-minus-baseline delta.

Bootstrap sampling is performed at task level so repeated attempts from the
same task are not incorrectly treated as independent tasks.

### Evaluation sensitivity sanity check

The foundation sanity suite deliberately degrades one variant. The evaluation
passes only when it detects the negative paired delta. This prevents a
non-discriminative evaluator from being considered healthy merely because its
runner completes.

## 4. Phase two: module capability suites

The module suites call production LCAH code directly. They do not ask a
scripted model to return a predetermined answer, and graders do not score final
answer wording.

Each module contains exactly 16 strict binary tasks:

- 4 basic tasks for one core ability;
- 6 composite tasks requiring two or three abilities;
- 6 adversarial tasks involving conflicts, cumulative state, similar
  distractors, or persistence-boundary faults.

The current production implementation is intentionally calibrated to score
between 60% and 85% on every module. The target range is validated after
grading and never changes task outcomes.

### Context compression

The compression suite compares full context, production `build_summary()`,
tail truncation, and named mutations. It checks preservation of goals,
constraints, paths, commands, test outcomes, blockers, decisions, and implicit
references. Adversarial tasks cover conflicting decisions, resolved blockers,
revoked constraints, similar paths, joint state, and repeated compaction.

A task passes only when every required state item is present and every stale or
forbidden item is absent. Compression ratio, recall, and stale leakage are
reported as diagnostics but do not provide partial credit.

Current strict result: **12/16 (75%)**.

### Durable memory

The memory suite calls production `extract_durable_promotions()` and
`DurableMemoryStore`. It covers write, delayed retrieval, conflict replacement,
secret and transient rejection, distractor resistance, action grounding,
abstention, 10–100 memory scale, multi-memory actions, implicit queries,
instruction-shaped malicious memory, and repository scope.

Action tasks require all necessary remembered arguments and forbid incorrect
arguments. Retrieval success alone is insufficient when the retrieved memory
should not be applied.

Current strict result: **12/16 (75%)**.

### Checkpoint recovery

The recovery suite calls production `SessionStore`, checkpoint creation,
session reload, and resume-state evaluation. It injects faults around persisted
goals, completed work, todos, workspace files, freshness, schemas, model/tool
identity, repeated resume, event gaps, tool-result gaps, and partial damage.

The grader inspects persisted state, resume classification, duplicate
operations, lost progress, and workspace outcomes. It does not inspect a model
final answer.

Current strict result: **13/16 (81.25%)**.

## 5. Mutation sensitivity

Each module has four small runner-level mutations. Mutations do not patch
production source files.

Compression mutations:

- drop command evidence;
- select the wrong decision in a conflict;
- reduce retained recent state;
- skip stale-state cleanup.

Memory mutations:

- reduce retrieval limit from three to one;
- disable conflict replacement;
- inject a high-overlap distractor;
- bypass forbidden-memory filtering.

Recovery mutations:

- omit todos from persisted state;
- skip file-freshness validation;
- replay a committed non-idempotent operation;
- accept an incompatible schema.

Every mutation must flip 1–6 production passes, reduce the strict score by at
least 6.25 percentage points, and leave at least one task passing. Reports list
the exact flipped task IDs. The current 12 mutations each flip 1–2 tasks and
reduce scores by 6.25–12.5 points.

## 6. Calibration safeguards

Every task includes `expected_current_result` for baseline auditing, but graders
are forbidden from reading it. Tests invert this field and require an unchanged
grade.

The CLI exits non-zero when:

- any production module score is outside 60%–85%;
- any basic tier scores below 75%;
- any mutation violates its flip-count or score-delta contract.

This makes saturation and loss of sensitivity visible in continuous
integration. Scores are never clipped to the desired range.

## 7. Interpreting the current results

| Module | Overall | Basic | Composite | Adversarial |
| --- | ---: | ---: | ---: | ---: |
| Compression | 75% | 100% | 100% | 33.3% |
| Memory | 75% | 100% | 100% | 33.3% |
| Recovery | 81.25% | 100% | 100% | 50% |

These results mean that the core mechanics work on basic and composed cases,
while adversarial cases expose concrete limitations. They do not imply that a
live coding agent succeeds on 75%–81.25% of real software tasks.

## 8. Public benchmark references

The design borrows evaluation styles rather than mixing unrelated benchmark
scores:

- [RULER](https://arxiv.org/abs/2404.06654): multi-key retrieval, multi-hop
  tracing, aggregation, and configurable context pressure;
- [NoLiMa](https://arxiv.org/abs/2502.05167): retrieval without direct lexical
  overlap;
- [MemoryAgentBench](https://arxiv.org/abs/2507.05257): retrieval, test-time
  learning, long-range understanding, and selective forgetting;
- [Mem2ActBench](https://arxiv.org/abs/2601.19935): memory must ground tool
  actions rather than only answer questions;
- [Inspect checkpointing](https://inspect.aisi.org.uk/checkpointing.html):
  restore agent state, sandbox state, events, and store at explicit persistence
  boundaries;
- [Recovery-Bench](https://www.letta.com/blog/recovery-bench/): recovery from
  corrupted trajectories and failed states;
- [Terminal-Bench](https://www.tbench.ai/news/announcement-2-0): isolated
  terminal environments and automatic outcome graders;
- [SWE-bench Verified](https://www.swebench.com/verified.html): real repository
  issue resolution, used only with task-quality caveats;
- [METR time horizons](https://metr.org/time-horizons/): relate task success to
  human expert task duration.

SWE-style public results should not be the sole headline metric. Public coding
benchmarks can contain contamination, ambiguous prompts, low-coverage tests,
or mismatches between issues and hidden graders. LCAH should treat them as
external calibration alongside curated native tasks and manual audits.

## 9. Next evaluation stage

The next stage is a 20–30 task LCAH-native end-to-end coding suite using live
models, isolated repositories, hidden tests, three to five attempts per task,
fixed budgets, trajectory evidence, and human task-duration estimates.

Recommended task families include bug localization, cross-file changes,
regression tests, repository exploration, configuration, long-horizon tasks,
resolvable ambiguity, and tasks where the agent should clarify or refuse.

Release reporting should keep four primary dimensions separate:

- end-to-end task success;
- compression success retention versus full context;
- memory utility versus memory disabled and full-history oracle;
- recovery reliability versus uninterrupted execution.

No single aggregate score should hide a module that regresses.

## 10. Commands

Run the foundation sensitivity check:

```bash
python scripts/run_evaluation_foundation_sanity.py \
  --output /tmp/lcah-evaluation-foundation-sanity.json
```

Run all module capability suites:

```bash
python scripts/run_module_capability_evals.py \
  --output-dir /tmp/lcah-module-evals \
  --repetitions 3
```

Run the complete test suite:

```bash
uv run pytest tests -q
```
