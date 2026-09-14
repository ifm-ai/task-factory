---
name: task-design-review
description: "Adversarially review an RL/benchmark task for the four ways it can be worthless: contamination (the answer is lookup-able), brute-forceability (search beats reasoning), ambiguity (a valid reading yields a different answer), and verifier fitness (the grader disagrees with correctness). Use before publishing any task, after grounding a new task, after trajectory analysis reveals cross-trial patterns, or whenever deciding whether a task is benchmark-worthy. Domain-general: works for math, science, code, or any task with a checkable answer."
---

# Task Design Review

A task can pass its oracle, score a beautiful pass@k, and still be worthless.
This review catches the four failure modes that difficulty metrics cannot see.

**This review is context-adaptive.** Run it with whatever evidence you have:

| Evidence available | What the review can check |
|---|---|
| Task files only (post-grounding) | Contamination, brute-forceability, ambiguity — statically |
| Task files + trajectories (post-calibration) | All four, plus cross-trial patterns and agent-informed ambiguity |

Early passes are cheap and catch the obvious. Late passes see what agents
actually did. Run it as many times as you need — including zero, if you are
genuinely confident. There is no fixed position in the pipeline.

## The hard rule

**Do not publish a task you are not confident on across all four dimensions.**
If there is doubt — about a source leak, a search space, a rejected-but-valid
answer, or whether the task is worth benchmarking at all — fix it and review
again, or abandon the task and move on. Abandoning is cheap. A bad task in a
benchmark is expensive and durable.

---

## Dimension 1 — Contamination

*Can the agent obtain the answer without doing the work?*

- Does the instruction name its source — a paper, a question ID, a URL, a
  dataset entry, a well-known problem name?
- Does a distinctive phrase from the instruction retrieve the source? Try the
  most unusual noun phrase in it.
- Are the specific constants, thresholds, or parameters the ones a published
  source uses? Perturbing them breaks lookup while preserving difficulty.
- Is the answer a famous named result the model likely memorized?

**Never mention the source in `instruction.md`.** Source attribution belongs in
the results ledger and commit message only. The instruction must state the
problem directly and self-containedly.

Note: contamination is only a real gate if the sandbox has no network egress.
Confirm that separately — see `reward-hacking-audit`.

Verdict: `CLEAN` / `LEAK: <what>` / `PERTURB: <what to change>`

## Dimension 2 — Brute-forceability

*Can search substitute for reasoning?*

Estimate the search space explicitly — write the number down. Under ~10^6
candidates, assume a competent agent enumerates it and the task tests coding
throughput, not understanding.

- Can the answer be found by enumerating a small space?
- Does a single library call solve it (`sympy.factorint`, `numpy.linalg.eig`,
  a solver)? If the hard part is knowing which function to call, the task tests
  API recall.
- If trajectories exist: did passing agents actually enumerate? **A 4/4 task
  where all four brute-forced is too easy regardless of score. A 1/4 task where
  the one success brute-forced is a task about to become easy.**

The goal is tasks where the *domain reasoning* is hard, not the coding. An agent
that can write Python but cannot do the domain work should fail. An agent that
can do the domain work but writes sloppy JSON should pass.

Verdict: `RESISTANT` / `MARGINAL: ~10^n space` / `BRUTE-FORCEABLE`

## Dimension 3 — Ambiguity

*Could a careful, correct solver produce a different answer than the verifier expects?*

This is the dimension that silently manufactures false difficulty. Check every
underspecified choice:

- Convention and units — which sign, which normalization, which basis?
- Ordering — is list order meaningful? If not, is that stated?
- Boundaries — inclusive or exclusive? Is zero included? Is the trivial case counted?
- Output shape — nesting, key names, scalar vs single-element list.
- Rounding and tolerance — how many digits, and is exact comparison intended?
- Edge cases the domain treats specially (degenerate inputs, characteristic 2,
  the empty set) — does the instruction say which behavior is wanted?

If trajectories exist, this dimension gets much sharper: **when several agents
independently produce the same "wrong" answer, the task is ambiguous or the
verifier is wrong — not the agents.** Verify the math yourself before assuming
the agents erred.

Fix order: **make the instruction unambiguous first, loosen the verifier
second, and never lower the domain bar.**

Verdict: `UNAMBIGUOUS` / `AMBIGUOUS: <the choice not pinned down>`

## Dimension 4 — Verifier fitness

*Does the grader accept exactly the correct answers?*

Two failure directions, both fatal:

- **False negatives** — a correct answer is rejected on formatting, type,
  ordering, or precision. This is the most common defect and it manufactures
  fake difficulty.
- **False positives** — a wrong or empty answer scores 1. Check: what does the
  verifier do with a missing file, empty JSON, `null`, a partially-correct
  answer, or the input echoed back?

Also confirm the verifier tests the *thing the task is about*. A verifier that
checks a summary statistic when the task asked for a construction is measuring
the wrong quantity.

For the deeper discipline here — concordant bugs, output contracts, coercion —
use the `verifier-hardening` skill. This dimension only asks whether the
verifier is *fit*; that skill is how you make it fit.

Verdict: `TIGHT` / `LOOSE: <what passes that shouldn't>` / `BRITTLE: <what fails that shouldn't>`

---

## Calibrating context: what makes a task genuinely hard

Distilled from several hundred generated tasks. Use it when judging fitness.

**Easy** (agents solve it):
- Small search space — enumeration wins
- Direct formula application — plug into a known identity
- Single-step computation — one library call
- Standard algorithm on small input

**Hard** (agents fail it):
- Multiple interacting concepts that must be composed correctly
- Precise edge-case handling where a special case behaves differently
- Large structured output — a full table, not a single number
- Requires constructing a non-trivial procedure, not calling one
- The obvious approach has a subtle flaw
- Requires choosing the right representation or canonical form

Target shape: **a task a strong domain expert with a computer solves in ten
minutes, that tests whether an agent can reproduce that reasoning autonomously.**

## Review tiers

Match effort to stakes:

- **Tasks headed for the benchmark as calibrated difficulty** — full four-dimension
  review with all available evidence, including trajectories.
- **Tasks logged as too-easy or too-hard but still published** — contamination
  check only. They are labeled by difficulty and will not gate results.

## Output format

```
DIMENSION       VERDICT      NOTE
contamination   CLEAN        no source named; constants perturbed from the source
brute-force     MARGINAL     ~10^7 space; passing agent reasoned, did not enumerate
ambiguity       AMBIGUOUS    ordering of the returned basis not specified
verifier        BRITTLE      exact float compare at 1e-12; correct answers differ at 1e-9

DECISION: FIX  (blocking: ambiguity, verifier)
```

`DECISION` is one of `PUBLISH`, `FIX`, or `ABANDON`. Anything other than
`PUBLISH` names the blocking dimensions.

## Related

- `verifier-hardening` — how to make a verifier fit (dimension 4's remedy)
- `reward-hacking-audit` — the reward channel itself: sandbox isolation, egress, direct writes
- `harbor-trajectory-analyser` — produces the trajectory evidence this review consumes
