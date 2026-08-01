# Context Quality Verifier Design

## Goal

Protect task continuity when LCAH compacts history or reduces prompt sections. The system must preserve the current request and checkpoint state, expose evidence for intermediate progress, and distinguish unfinished work from failed work.

## Scope

- Add deterministic checks for compaction continuity, prompt continuity, and checkpoint structure.
- Store quality status and evidence with task state and checkpoints.
- Render checkpoints in a dedicated prompt section that ordinary history reduction cannot clip.
- Record quality results in compaction summaries, traces, reports, and task state.
- Add focused regression tests and a deterministic context-quality test matrix.

## Design

### Quality states

Task quality uses `in_progress`, `blocked`, `no_progress`, `completed`, and `failed`. A quality verifier returns a separate `passed` or `repair_required` result; it does not confuse an unfinished task with a failed verification.

### Verification layers

1. `verify_compaction_continuity` compares the pre-compaction history with the preserved suffix and checks that the structured summary contains the required fields.
2. `verify_prompt_continuity` checks that the exact current request and full checkpoint text are present in the final prompt.
3. `verify_checkpoint` checks required checkpoint fields, actionable recovery information, and evidence shape.
4. `classify_progress` derives the intermediate quality state from the task state, checkpoint trigger, and new evidence.

All checks are deterministic. Model-based judging is deliberately outside this control path; final task quality remains validated by executable tests and benchmark verifiers.

### Context layout

The checkpoint becomes its own prompt section between the stable prefix and ordinary memory. It is rendered in full and is excluded from the normal reduction order. Ordinary memory, relevant memory, skills, and history remain eligible for budget reduction. The current request remains the final untrimmed section.

### Evidence

Each checkpoint records quality status, changed paths, last tool, tool and model attempt counts, and the latest quality verification. Existing checkpoint fields remain compatible; the added fields are additive.

### Failure handling

Compaction is verified before its replacement history is persisted. If the verifier fails, the original history remains intact and the result is recorded as `repair_required`. Prompt verification is recorded in metadata and trace so a failing case is observable and testable.

## Acceptance criteria

- A compressed session preserves the latest turns byte-for-byte and reports a passing compaction verification.
- A prompt with an active checkpoint contains the full checkpoint and exact current request even when ordinary memory is reduced.
- Checkpoints expose quality status and actionable evidence in session, task-state, and report artifacts.
- Intermediate runs can be classified as in progress, blocked, or no progress without being marked completed.
- Existing tests and the deterministic benchmark suite remain green.
