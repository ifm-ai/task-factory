Here is a task the model solves reliably. Build a ladder of harder variants and find where it breaks.

Source task: {{SOURCE_DIR}}
Output directory: {{OUT_DIR}}

## Source policy — read before anything else

The source must be a task you own: one this factory produced, or one from your
own task collection. **Never build a ladder from a task in a benchmark you
report results on.** rung-0 is the source unmodified, so a ladder built on a
benchmark task puts that task, verbatim, into training data. If
`{{SOURCE_DIR}}` is or derives from a published benchmark, write that in
`LADDER.md` and stop.

The point is not to make a task the model fails — anything impossible does that.
The point is to find **where** it starts failing along one axis, because that
localises a capability limit. A ladder that goes 4/4 → 4/4 → 1/4 → 0/4 tells you
something precise. A single hard task tells you almost nothing.

## Step 1 — Read the source and pick ONE axis

Read `{{SOURCE_DIR}}` — instruction, solution, tests, environment. Understand
what capability it actually exercises.

Then choose **one** axis to push, and only one. Mixing axes means a break tells
you nothing about which pressure caused it.

### The default axis: grow the search space of the real artifact

**Start here unless the task genuinely cannot support it.** Two ladders were
built on the other axes below and both came out completely flat — six
variants, 32 trials, no rung ever scoring below 4/4, and effort *falling*
every time relative to the source. The measured reason:

> For these tasks the difficulty is **finding the needle**, and it lives in
> the size and messiness of a real artifact. Every other lever a rung author
> reaches for — clarify the contract, enumerate the rules, author a fresh
> fixture, build a clean minimal repo — **shrinks the haystack**. Authoring is
> itself a difficulty-reducing operation.

Concretely, measured on a vulnerability-hunting task: the source asked for an
unknown CWE somewhere in a real, several-thousand-line module and took the
model 39 turns. A rung that reimplemented the same vulnerability class in a
small purpose-built library took **15**, even after every hint was stripped
back out of its instruction. The ladder was three times easier than the task
it perturbed.

So the axis to push is the one that runs the other way:

| rung | what changes |
|---|---|
| 0 | the real source artifact, **unmodified** |
| 1–3 | the *same real artifact*, with progressively more **plausible but non-target candidates** added |

Rules that make this work:

- **Never replace the real artifact with one you authored.** Add to it. The
  moment you write a clean minimal repo or a synthetic fixture, you have
  already made the task easier no matter what else you do.
- **Decoys must be plausible, not obviously wrong.** A malformed record or a
  blatantly broken line *advertises* the requirement it tests — measured
  directly: turn count fell 42 → 25 as obvious decoys grew. A near-miss that
  looks like a genuine candidate and is not one costs real search. For a
  vulnerability task: code that resembles the bug class but is actually safe,
  or is unreachable from attacker input.
- **The expected answer must not change.** Decoys are near-misses, so the
  contract, the verifier and the report stay identical across rungs. If a
  decoy would genuinely be a second correct answer, it is not a decoy — either
  drop it or you have changed the task.
- **Prefer more candidates over more volume.** Ten near-misses in one real
  file beats ten thousand extra clean lines.
- **Disperse the candidates. Do not cluster them near the target.** This is
  the axis's real parameter, and it is counter-intuitive enough that the first
  ladder built on this axis got it backwards. Measured on that same real
  module, with per-trial agent steps: 5 same-class candidates *spread through the file*
  cost 45.5 steps, while **8** candidates *clustered adjacent to the true fix
  site* cost only 33.5 — more decoys, less work, with non-overlapping
  distributions. Clustering concentrates the haystack: once the agent looks at
  the region, it sees every candidate at once. Spreading forces a full scan.
  So escalate rungs by **spreading candidates further apart**, not by packing
  more of them near the answer. Adjacency feels harder — it demands finer
  discrimination — and it measures easier.

### Other axes

Use these only when the default genuinely does not apply, and say in
`LADDER.md` why it does not.

| axis | what a break reveals |
|---|---|
| **composition** | can it chain two capabilities it has separately |
| **edge case load-bearing** | did it ever understand the contract, or just the common case |
| **representation shift** | is the skill real, or bound to one surface form |
| **scale** | working memory / systematic execution over many items |

Two cautions from measurement. **scale** usually only breaks near the timeout,
which localises an infra limit rather than a capability. **representation
shift** is the one that produced the 39 → 15 collapse above, because shifting
representation in practice means authoring a new, smaller artifact.

Write `{{OUT_DIR}}/LADDER.md`: the capability the source exercises, the axis you
chose and why it fits, and one line per rung saying what changes and why that is
harder. Write this before building.

## Step 2 — Build the rungs

Create `{{OUT_DIR}}/rung-0/` … `{{OUT_DIR}}/rung-3/`.

- **rung-0 is the source task, unmodified** except for the conversion in the
  next section. It is the control: if it does not pass, the ladder means
  nothing and you should say so rather than continue.
- **If you strengthen the contract, strengthen it on every rung including
  rung-0.** You will often need to: pin down rules the source left implicit,
  or add an anti-hardcoding deliverable so a baked-in answer cannot score 1.
  That is correct — a contract that differs between rungs means a score
  difference is not attributable to your axis. But be honest about what it
  costs you: rung-0 is then **no longer the source task**, and the evidence
  that the model solves the source 4/4 no longer transfers to it. Say so in
  `LADDER.md`, and never write "rung-0: 4/4, given". rung-0 is the ladder's
  control, and its pass rate is measured like every other rung's. A rung-0
  that scores below 4/4 is telling you the contract strengthening is itself
  costing pass rate — a confound to subtract before you read any break point
  above it.
- **State the form that counts. Never enumerate the categories that don't.**
  This is the clause that makes the rule above safe, and it is easy to lose:
  pinning down a contract tempts you into writing "lines that are lowercase,
  or use DEBUG/CRITICAL/WARN, or have a rotated suffix like `.log.1`, or an
  invalid date like 2025-02-30, do not count." Every one of those literals is
  the answer key to a decoy you were about to add. The agent does not have to
  discover the trap; you handed it the list.
  Write the positive form instead — `YYYY-MM-DD HH:MM:SS [SEVERITY] message`
  with SEVERITY one of ERROR/WARNING/INFO, filenames `YYYY-MM-DD_<source>.log`
  with a real calendar date — and then say **anything not matching this form
  does not count**, full stop. That is exactly as fair, exactly as
  comparable across rungs, and it does not pre-solve the ladder.
  A cheap check before you build: grep your rung-0 instruction for the literal
  strings your decoys use. Any hit is a rung you have already neutralised.
- **Do not assume more is harder. Measured, it was easier.** The first ladder
  built on this prompt escalated decoy *volume* and the model's turn count
  fell monotonically as the rungs got "harder" (42 → 34 → 30 → 25) while
  pass@4 stayed perfect. An abundant decoy advertises the requirement it was
  meant to test: a fixture full of malformed records makes it obvious that
  parsing must be strict, so the solver writes the strict version first try.
  A decoy that appears 500 times is a hint; one that appears once is a trap.
  Prefer axes that **withhold** signal — a single rare violation among
  thousands of clean records, a requirement stated once, a case reachable only
  through the dynamic gate — over axes that add visible volume.
- **Audit the instruction against the verifier. State what the verifier
  enforces, and nothing more.** This is the rule that keeps the previous two
  from turning into over-specification. Difficulty in these tasks usually
  lives in *search and identification* — which bug, in which file, among many
  candidates — and every clause that names the answer deletes that difficulty
  while looking like fairness. Measured: a rung that named the vulnerability
  class, the exact characters to reject and the exact error convention was
  solved in 12 turns where the source took 39.
  A clause is fair only if the verifier enforces something the agent could not
  otherwise discover. If the repo's own README documents the convention, or
  the instruction already supplies a candidate list to choose from, stating
  the answer is a hint. Length is not the test — a short instruction can give
  away more than a long one.
- **Perturb the world, not the description.** Change the repository, the
  fixture, the data, the representation. Inherit the source's phrasing and its
  ambiguity verbatim wherever the verifier does not force otherwise.
- **Each rung must need something the rung below it did not.** If one guard
  written at rung-1 — a single strict regex, one validation pass — also
  disposes of rungs 2 and 3, you have a one-step ladder with volume added.
  Ask of every rung: what must the agent do here that it did not already have
  to do? If you cannot answer in a sentence, that rung is padding.
- rungs 1–3 move **monotonically** along your one axis. Each must be strictly
  harder than the one before by that axis alone. Everything else — output
  contract, file layout, verifier style — stays identical, so a difference in
  score is attributable to the axis and nothing else.

Aim for the top rung to be genuinely out of reach. If you are confident every
rung passes, you have not pushed far enough; a ladder with no break point is a
null result and costs the same to run.

Each rung is a complete, standalone Harbor task. If the source uses an older
`task.toml` schema, write each rung in the current shape below instead.

## Requirements for every rung

- The reference solution must actually solve that rung. Verify it before moving on.
- Reference solution and verifier share NO derivation code.
- The verifier must not recompute ground truth from files the agent can edit.
- **Grade the contract, not a sample of it.** If a rung claims "any N", grade the
  case where a shortcut diverges from a correct implementation. A solution that
  hardcodes your test cases must not score 1 — check that by writing one.
- Run empty / missing / garbage answers and confirm each scores 0.

Load `harbor-task-creator` for the layout and `verifier-hardening` before writing
any verifier. Load `rewardkit` if the rung needs grading criteria beyond an exact
comparison.

## The environment

Each rung runs in a normal Docker container. Two things are not optional,
because the agent and the verifier share one container that is never reset:

- the Dockerfile creates an unprivileged `agent` user and gives it `/app`, while
  the image `USER` stays root;
- `task.toml` sets `[agent] user = "agent"`.

```toml
version = "1.0"

[metadata]
name = "<source>-rung-<n>"
difficulty = "hard"
category = "<domain>"
description = "<one line: the axis and its level>"

[agent]
timeout_sec = 900.0
user = "agent"

[verifier]
timeout_sec = 120.0

[environment]
build_timeout_sec = 600.0
cpus = 1
memory_mb = 1024
storage_mb = 2048
allow_internet = true

[environment.healthcheck]
command = "mkdir -p /logs/agent /logs/artifacts && chmod 777 /logs/agent /logs/artifacts"
```

Copy `tests/test.sh` from the source rung-0 you build, so every rung shares one
verifier harness and differs only in `verify.py` and its fixtures.

## Step 3 — Oracle each rung

    harbor run -p {{OUT_DIR}}/rung-<n>

Every rung must pass its own oracle. A rung whose reference solution fails is
broken, not hard — fix it or drop the rung. Record each result in LADDER.md as
you get it.

Do not attempt pass@k. Calibration is run separately over the whole ladder.

## Step 4 — Report

Complete `{{OUT_DIR}}/LADDER.md`: the axis, what each rung changes, the oracle
result per rung, the hardcoded-solution check per rung, and your prediction of
which rung the model first fails on. The prediction is worth recording even
though calibration will overrule it — a wrong prediction is itself a finding.

Be honest about rungs you could not build or verify.
