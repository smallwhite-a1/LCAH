# SWE-bench Lite Evaluation

LCAH currently supports a small, reproducible preparation layer for SWE-bench
Lite. This phase intentionally stops before the official Docker grader. It
handles deterministic task selection, keeps gold patches out of the agent
manifest, and provides a resumable batch runner.

## 10-task smoke run

The source may be a SWE-bench JSON list, an object with a `tasks` list, or
JSONL. The command below creates a manifest without modifying any repository:

```bash
python scripts/run_swebench_lite.py \
  --tasks-file /path/to/swebench-lite.json \
  --count 10 \
  --seed 42 \
  --manifest-out artifacts/swebench-lite-10.manifest.json
```

## 50-task batch

Use the same seed so the 10-task smoke set is the prefix of the 50-task set:

```bash
python scripts/run_swebench_lite.py \
  --tasks-file /path/to/swebench-lite.json \
  --count 50 \
  --seed 42 \
  --manifest-out artifacts/swebench-lite-50.manifest.json
```

## External runner hook

An optional command is invoked once per manifest task. It receives the public
task object through `LCAH_SWEBENCH_TASK_JSON` and the task ID through
`LCAH_SWEBENCH_INSTANCE_ID`. The command is responsible for provisioning a
workspace and launching the model; completed rows are skipped on later runs.

```bash
python scripts/run_swebench_lite.py \
  --tasks-file /path/to/swebench-lite.json \
  --count 10 \
  --seed 42 \
  --manifest-out artifacts/swebench-lite-10.manifest.json \
  --results-out artifacts/swebench-lite-10.results.json \
  --run-command 'python scripts/run_one_lcah_task.py'
```

The manifest contains only `instance_id`, `repo`, `base_commit`,
`problem_statement`, and optional `version`. Gold patches, test patches, and
grader-only fields are discarded during loading.

## 100-task representative batch

Use the same deterministic selection interface for the larger representative
sample:

```bash
python scripts/run_swebench_lite.py \
  --tasks-file /path/to/swebench-lite.json \
  --count 100 \
  --seed 42 \
  --manifest-out artifacts/swebench-lite-100.manifest.json
```

## Compression A/B

Before connecting a real model, run the deterministic local harness ablation:

```bash
python scripts/run_compression_ablation.py
```

It runs the same 32 fixed tasks twice in fresh workspaces. The local benchmark
contains 20 context-pressure tasks that naturally exceed the configured prompt
budget and trigger automatic compaction in the treatment group. The control
group disables both budget reduction and automatic history compaction. Both
groups use outcome-only final verifiers that do not inspect compaction events.
The artifact reports paired pass rates, prompt sizes, estimated tokens,
compaction counts, budget reductions, and prompt Verifier results. This is a
mechanism regression test, not a SWE-bench score.

Read the compression metrics at three levels:

- `avg_*` covers every task and shows the overall cost change.
- `triggered_*` covers only tasks that actually reduced a budget or compacted
  history, so it measures the effect when compression was needed.
- `p95_*` shows the high-pressure tail instead of hiding it in an average.

`actual_input_token_coverage` reports how many task runs returned provider-side
input token usage. Scripted local runs intentionally report `0.0`; use a real
provider run before making claims about billed-token savings. The compaction
Verifier also checks that critical paths, commands, and test outcomes survive
the summary contract, and records a bounded repair attempt when evidence is
missing.
