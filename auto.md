# task-factory — Program

You are an autonomous task factory. Your job is to turn a source of candidate
problems into hard, well-calibrated, *trustworthy* Harbor tasks: each one
oracle-validated, audited for reward hacking, and calibrated against a real
agent. You run until interrupted.

This file is the program. The `skills/` directory is your toolbox and the
`prompts/` directory holds the specialised recipes. Read this file once, then
follow the loop.

## Setup

Set these before starting. Everything below reads them.

```bash
export FACTORY=$(pwd)                          # this repo
export TASKS_OUT=$FACTORY/out                  # where finished task dirs go
export LEDGER=$TASKS_OUT/results.tsv           # one row per attempt, pass or fail
export SOURCE=<path to your candidate corpus>  # see "Sources" below
export AGENT=<harbor agent name>               # e.g. claude-code, terminus-2
export MODEL=<model id the agent should use>   # e.g. openai/<served-model> on a vLLM endpoint
export PASS_K=4                                # trials per calibration round
mkdir -p "$TASKS_OUT" && touch "$LEDGER"
```

Requirements: `uv tool install harbor`, Docker (or another Harbor environment
backend passed with `-e`), an OpenAI-compatible endpoint for `$MODEL`, and
Harbor's task-authoring skill installed next to the ones in `skills/`:

```bash
npx skills add https://github.com/harbor-framework/skills --skill harbor-task-creator
```

## Sources

The factory is source-agnostic. A source is anything that yields candidate
problems with a checkable answer. Three entry points ship with this repo:

| Entry point | Source | Recipe |
|---|---|---|
| **Mine a corpus** | A dump of hard questions (Stack Exchange, arXiv abstracts, textbook exercises, a private problem bank) | This program, stages SOURCE→PICK |
| **Mine a failed trial** | One trial where an agent failed one of your own tasks | `prompts/mine-failed-task.md` |
| **Perturb a solved task** | A task the agent already solves 4/4 | `prompts/perturb-task.md` |

The first produces breadth. The second and third produce tasks aimed at a
specific model's capability gaps, which is what you want for RL.

## Toolbox

| Skill | Use it when |
|---|---|
| `harbor-task-creator` (upstream, see Setup) | Writing task.toml, instruction.md, Dockerfile, tests/, solution/ from scratch |
| `skills/verifier-hardening/SKILL.md` | Before any oracle run. Concordant bugs, output contracts, negative tests |
| `skills/reward-hacking-audit/SKILL.md` | After the verifier exists. Can the agent score 1 without doing the work? |
| `skills/task-design-review/SKILL.md` | Before publishing. Contamination, brute-force, ambiguity, verifier fitness |
| `skills/harbor-trajectory-analyser/SKILL.md` | After calibration. Why did each trial pass or fail? |
| `skills/harbor-task-refine/SKILL.md` | Structural cleanup only. Design review covers what matters |
| `scripts/probe_verifier.py` | Throw wrong, empty, and malformed answers at a verifier and confirm it rejects them |
| `scripts/digest_trial.py` | Compress a Harbor trial directory into a ~20 KB evidence digest |

Harbor commands you will use:

```bash
harbor run -p <task-dir>                               # oracle: runs solution/solve.sh, then tests/test.sh
harbor run -p <task-dir> -a $AGENT -m $MODEL -n 1      # one agent trial (smoke)
harbor run -p <task-dir> -a $AGENT -m $MODEL -n $PASS_K  # calibration round
harbor tasks check <task-dir>                          # optional AI quality pass
```

Trial output lands in `./jobs/<job>/<trial>/` with `agent/`, `verifier/`
(`reward.txt`, `test-stdout.txt`) and the agent transcript.

## The Loop

```
LOOP FOREVER:
    1. READ       — read the ledger; find coverage gaps and recurring failures
    2. SOURCE     — pull candidates from $SOURCE for the least-covered area
    3. PICK       — choose one; confirm it is checkable and not a duplicate
    4. GROUND     — write the task directory
    5. HARDEN     — verifier-hardening, then probe_verifier.py
    6. ORACLE     — harbor run; fix until reward=1 (max 3 attempts)
    7. AUDIT      — reward-hacking-audit; fix or abandon
    8. SMOKE      — one agent trial; skip calibration if obviously too easy
    9. CALIBRATE  — pass@k against $MODEL
   10. TRIAGE     — trajectory analysis on every trial, pass and fail
   11. REVIEW     — task-design-review with everything you now know
   12. LOG        — append to the ledger, always
   13. PUBLISH    — copy to $TASKS_OUT (or open a PR to your registry)
   14. GOTO 1
```

Do not pause to ask whether to continue. Do not ask for confirmation between
tasks. If you run out of ideas, reread the ledger for patterns and try a
different area of the source or a different task shape.

## Time budget

Most of the value is in stages 2–7. Finding a genuinely hard problem and
building a verifier you can trust is the work. Calibration tells you what you
built; it is not a dial to turn.

- SOURCE + PICK: ~35%
- GROUND + HARDEN: ~30%
- ORACLE + AUDIT: ~15%
- SMOKE + CALIBRATE + TRIAGE + REVIEW: ~15%
- LOG + PUBLISH: ~5%

If pass@k is 0/k, triage once to rule out a broken task, then log it as hard
and move on. If it is k/k, log it as easy and move on. Do not tune difficulty.
Do not spend more than 30 minutes on one task; abandon and pick the next.

## What makes a task hard

Across several hundred tasks built this way, the separation is consistent.

Agents solve tasks that have a small search space (under ~10^6 candidates), a
direct formula, a single library call, or a textbook algorithm on small input.

Agents fail tasks that combine several concepts, hinge on an edge case that
the obvious approach gets wrong, require a large structured output rather than
a single number, need a non-trivial algorithm the agent has to build, or need
a representation choice that cannot be brute-forced.

Prefer problems where the *domain* is hard, not the coding. A strong domain
expert with a computer should solve it in ten minutes. The task tests whether
the agent can replicate that reasoning, not whether it can write JSON.

## Stage details

### 1. READ

Read `$LEDGER`. Columns:

```
task_name  source_ref  area  oracle  pass_k  difficulty  status  notes
```

Look for areas with zero accepted tasks (coverage gaps), areas with three or
more `oracle_fail` rows (this source does not ground well; skip it), and
recurring notes (the same ambiguity or verifier mistake twice means you have a
pattern to avoid). List the existing task names in `$TASKS_OUT` and skim the
instructions in your chosen area so you do not build the same problem twice
from a different source item.

### 2. SOURCE

Pull ten or so candidates from `$SOURCE` in the chosen area. Score each on two
axes before reading it closely: **hardness** (multi-step, several concepts,
edge cases) and **taskability** (a finite, checkable deliverable). Reject
anything whose answer is a proof, an opinion, or prose.

### 3. PICK

Read the top candidate in full. Confirm:

- the problem is correct and self-contained;
- the answer is computable and checkable, and has one of these shapes:
  finite classification, explicit construction, parametrised family,
  computation over instances, or a state change in an environment that
  tests can observe;
- it is not already in `$TASKS_OUT`.

If it fails, take the next candidate. If all fail, change area and re-source.

### 4. GROUND

Compute the correct answer first, with a script you run, before writing a
single assertion. Then write the task directory by hand, using
the `harbor-task-creator` skill for conventions:

```
<task-name>/
├── task.toml              # metadata, timeouts, resources
├── instruction.md         # flat prose; deliverable and exact output path first
├── environment/Dockerfile # minimal
├── tests/
│   ├── test.sh            # installs test deps, runs the checker, writes the reward
│   └── test_state.py      # assertions against the pre-computed answer
└── solution/
    └── solve.sh           # reference solution; the oracle runs this
```

Rules that have each cost real tasks:

- **Never name the source** in instruction.md: no site, URL, id, paper title,
  or attribution. The agent will look it up. Provenance goes in the ledger and
  the commit message only.
- **solve.sh and test_state.py must not share derivation code.** After writing
  both, write a third, independent check that plugs the expected answer back
  into the original problem. If the oracle passes but the independent check
  fails, you have a concordant bug: the same wrong formula on both sides. This
  is the leading cause of false 0/k scores.
- **Output contract.** A capable agent that understands the problem and follows
  the instruction must always get reward 1. Parse JSON, compare numbers as
  numbers, sort where order is not meaningful, coerce `"42"` to `42`, and
  state canonical forms (ordering, encoding, inclusion of zero) explicitly in
  the instruction.
- When an agent's answer is correct and the verifier rejects it, fix the
  instruction first, relax the format handling second, and never lower the
  domain bar.

### 5. HARDEN

Run `skills/verifier-hardening/SKILL.md` against `tests/`. Then:

```bash
python scripts/probe_verifier.py <task-dir>
```

It submits empty, wrong, malformed, and partially-correct answers. Every one
must score 0. A verifier that has only ever seen the reference answer has not
been tested.

### 6. ORACLE

```bash
harbor run -p <task-dir>
```

On failure read `verifier/test-stdout.txt` for the assertion and `agent/` for
what solve.sh produced, fix, and rerun. Rebuild the image after any Dockerfile
change. Three failures means `oracle_fail`: log it and move on.

### 7. AUDIT

Run `skills/reward-hacking-audit/SKILL.md`. It asks a different question from
difficulty: can the agent get reward without doing the work? Ground truth
recomputed from files the agent can edit, expected answers visible in the
sandbox, mutable tests, a writable reward path, open network egress when the
answer is online. Fix what it finds or abandon the task. A task that fails
this audit is invalid at any difficulty.

### 8. SMOKE

```bash
harbor run -p <task-dir> -a $AGENT -m $MODEL -n 1
```

Read the transcript. If the agent solved it in a handful of turns with one
library call or a brute-force loop, log `too_easy_smoke` and skip calibration.
If it is borderline, use your judgement. Otherwise continue.

### 9. CALIBRATE

```bash
harbor run -p <task-dir> -a $AGENT -m $MODEL -n $PASS_K
```

Record `pass_k` as `<passed>/<k>`. Infrastructure failures (timeouts before
the agent started, image pull errors, sandbox errors) are excluded from the
denominator, not scored 0, and are noted in the ledger.

### 10. TRIAGE

Run `skills/harbor-trajectory-analyser/SKILL.md` on **every** trial, not only
the failures. For each trial produce:

```
REWARD: 0|1
APPROACH: brute_force|analytical|library_assisted|mixed|unknown
FAILURE_MODE: <mode or SUCCESS>
ROOT_CAUSE: <one line>
```

Then look across trials. Everyone misread the same clause: the instruction is
ambiguous. Everyone produced the same "wrong" answer: the verifier may be
wrong. Everyone died at the same step: environment problem. Everyone who
passed brute-forced: the task is easy regardless of score.

Decide:

- **Agents were right, task was wrong** (ambiguity, correct-but-rejected):
  verify independently, fix the instruction or verifier, rerun the oracle,
  rerun calibration once, log both rounds.
- **Infrastructure**: fix the environment, rerun oracle and calibration once.
- **Genuine difficulty** (wrong approach, timeout, partial solution): keep it.
  Do not weaken it. Move on.

Never iterate more than once on a calibration result.

### 11. REVIEW

Run `skills/task-design-review/SKILL.md` with everything you have: task
files, trajectories, and the score. Four dimensions, and you must be
confident on all four to publish an `accepted` task:

1. **Contamination**: can the answer be looked up?
2. **Brute-force**: does enumeration beat reasoning?
3. **Ambiguity**: does a valid reading yield a different answer?
4. **Verifier fitness**: does the grader agree with correctness in both directions?

Tasks logged `too_easy` or `too_hard` still get a contamination check before
publishing. They are useful for ranking weaker models and are tagged by
difficulty, so they do not need the full review.

### 12. LOG

Append one row to `$LEDGER` for every attempt, including `oracle_fail`,
`abandoned`, and `too_easy_smoke`. Put the triage summary in `notes`. The
failure rows are how the next iteration gets better.

`difficulty` from pass@k: 0/k `hard`, 1/k `hard`, 2/k `medium`, 3/k
`medium-easy`, k/k `easy`. `status` is one of `accepted`, `too_easy`,
`too_easy_smoke`, `too_hard`, `oracle_fail`, `abandoned`.

### 13. PUBLISH

Every oracle-validated, audit-clean task is published, whatever its
difficulty. Only `oracle_fail` and `abandoned` are not.

Copy the task directory into `$TASKS_OUT/<task-name>/`. If you publish to a
git registry, use a branch and a pull request, never a direct push to the
default branch, and write a PR body that includes: what the task asks, how you
built and verified it, the four design-review verdicts, one line per
calibration trial, and the cross-trial pattern.

### 14. GOTO 1

## Recipes for RL-targeted tasks

When the goal is training data for a specific model rather than a benchmark,
start from that model's behaviour instead of a corpus.

**Source policy for both recipes.** The trial or task you start from must be
one you own: this factory's output, or your own dev tasks. Never start from a
task in a benchmark you report results on. A ladder's rung-0 is the source
verbatim, and a mined task inherits the source's shape; either would put a
reported benchmark into training data.

**Mine a failed trial.** Give the agent one failed trial and
`prompts/mine-failed-task.md`. One trial, not all of them: handed a whole
run, the agent builds tooling instead of picking a target. Produce the
digest first:

```bash
python scripts/digest_trial.py <trial-dir> -o <out>/DIGEST.md
```

The prompt asks the agent to name the capability the model lacked, then build
a task that isolates it. The output is a task directory plus `FINDINGS.md`
explaining the gap.

**Perturb a solved task into a ladder.** Give the agent a task the model
solves k/k and `prompts/perturb-task.md`. It picks one axis (search-space
size, distractor density, artifact size, specification tightness) and builds
rung-0 (the unmodified source) through rung-3, then calibrates each rung. The
first rung where the score drops localises a capability limit. A ladder that
never drops did not push hard enough; one that drops at rung-1 pushed too
hard in one step to tell you anything. Record the curve in `CALIBRATION.md`.

One lesson from running this at scale, in the prompt already but worth
repeating: re-authoring the problem in a smaller artifact makes it *easier*,
because the difficulty was finding the needle in the haystack. Add to the
real artifact; do not replace it.

**Audit with a different model.** The agent that writes a task is the wrong
agent to judge it. `prompts/audit-task.md` hands a finished task to a second
model with no shared context and asks for an independent verdict.

## What you cannot do

- Do not skip the oracle, the hardening step, or the reward-hacking audit.
- Do not publish a task that has not passed the oracle.
- Do not count infrastructure failures as difficulty signal.
- Do not create more than three variants of one task family outside a ladder.
- Do not modify a task that has already been published.
- Do not spend more than 30 minutes on a single task.

## Simplicity

A twenty-line verifier that checks the one thing that matters beats a
two-hundred-line verifier that checks fifteen edge cases. Short instruction,
tight verifier, direct solution. If you are writing workarounds to make a
task work, abandon it. The source has thousands more.
