---
name: reward-hacking-audit
description: "Audit a task's reward channel for ways an agent can score 1 without doing the work: a verifier that recomputes ground truth from files the agent can edit, a grader or expected answer visible inside the sandbox, open network egress, a directly writable reward file, mutable tests, or artifacts leaked into the task directory. Use after writing or modifying any verifier, and before declaring any task finished — including scratch, test, and throwaway tasks, not just published ones. Also use when a pass rate looks implausibly high, when trajectories show success without domain work, or when standing up a new execution platform. Complements difficulty review — this asks whether the task is valid, not whether it is hard."
---

# Reward Hacking Audit

Difficulty review asks *is this hard?* This asks *is reward evidence of having
done the work?* They are independent, and only the second one is a validity
question.

**Why this matters more for RL than for benchmarks.** A leaderboard reports a
gameable task as one bad row. A training loop *optimizes into it*: gradient
descent will find the shortcut and the policy will learn the shortcut instead of
the capability. A task scoring 0/4 that could have been gamed is not a hard
task — it is a broken task whose exploit the probe model happened to miss, and a
stronger policy will not miss it.

**This is a pre-publish audit.** Trajectory analysis catches some gaming after
the fact — approach classification will flag an agent that enumerated or took a
shortcut — but only after spending the trials, and only if the exploit happened
to occur in them. Absence of gaming in k trials is not evidence of a sound
reward channel.

---

## Structural vs per-task

Most of these questions are answered **once per execution platform**, not once
per task. Determine the platform's behavior first, write it down, and then only
re-check the per-task items.

- **Structural** — sandbox isolation, network policy, whether the verifier runs
  in the agent's container or outside it, whether the reward file is writable
  from the agent's filesystem. Fixed by the harness.
- **Per-task** — what the task's own files expose: answers embedded in fixtures,
  test names that reveal expected values, artifacts committed by accident.

If a structural question turns out to be a genuine hole, that is a harness
finding, not a task finding — escalate it rather than patching one task.

## The audit

### 1. Is the grader visible to the agent?

- Does the agent's working directory contain the verifier, its assertions, or
  fixtures holding expected values?
- Does the instruction quote the rubric or the test names?
- Can the agent read the reference solution?

An agent that can read the assertions does not need to solve the task. This is
the most direct exploit and the easiest to introduce accidentally.

### 2. Is the expected answer reachable inside the sandbox?

Beyond the verifier itself: precomputed fixtures, cached outputs from an earlier
run, a `.pytest_cache` carrying node IDs, editor backups, notebook checkpoints,
or anything the answer was derived in. Search the environment the agent actually
receives for the answer's distinctive values.

### 3. Is network egress closed?

Contamination control is only real if the sandbox cannot reach the network. If
egress is open, treat every contamination verdict as provisional — the agent can
retrieve a source you assumed was unreachable, or query a stronger model.

Establish this once for the platform, and record it. If egress is open by
design, contamination review must be correspondingly stricter: perturbing
constants stops mattering less, and never naming the source matters more.

**Some remote sandbox backends cannot close egress at all.** Check your
environment class's `can_disable_internet`; where it returns `False`, Harbor
raises for `allow_internet = false`, so a task that tries to close egress does
not merely fail to isolate, it fails to run. Two consequences hold permanently
on such a backend:

- **Contamination verdicts are always provisional.** The agent can reach the
  network. Perturb published constants and never name a source; do not rely on
  a source being obscure.
- **Surface 6 cannot be closed by closing egress.** "Do not install X" stays one
  `apt-get` away no matter what the instruction says. The only durable fix is a
  task where the forbidden route does not produce a correct answer, or a
  verifier that detects the route in the artifact.

Check the backend before assuming either remedy is available to you.

### 4. Can reward be written directly?

- Is the reward or result file inside the agent's writable filesystem?
- Can the agent write the output file in a form that satisfies the verifier
  without computing anything — for example, by reading a schema and emitting
  well-formed values?
- Can the agent modify, delete, or monkey-patch the tests, or install a shim
  that intercepts the comparison?
- Does the verifier import anything from a path the agent can write to?

**A defence that can silently no-op is not a defence.** Verifiers often guard
themselves — chmod the fixtures, drop privileges before running agent code,
sandbox the execution. Check what happens when the guard *cannot* engage: not
running as root, the unprivileged user missing, the chmod failing. If the code
returns quietly and continues, the task still reports a reward, and every
exploit the guard existed to stop now scores 1 with no signal that anything
changed.

```python
if os.geteuid() != 0:
    return None          # guard skipped, verification proceeds anyway
```

Make the failure loud: refuse to score, or emit an unmistakable warning. Then
test the guard in its *engaged* state — confirming the exploit fails when the
defence is inert proves nothing about the defence.

### 5. Does the verifier derive ground truth from agent-mutable state?

The subtlest hole, and the one that survives every other check. A verifier that
**recomputes** the expected answer at test time — rather than comparing against
a value fixed when the task was authored — is only sound if its inputs are
beyond the agent's reach.

If the verifier reads the same files the agent can write, the agent does not
need to solve anything; it edits the inputs until its answer is true.

```python
# Looks exemplary: no hardcoded answer, no shared derivation with solve.sh.
# Completely gameable — /app/input.log is in the agent's workspace.
def expected_total(path="/app/input.log"): ...
actual == expected_total()
```

The exploit is one line: empty the input, submit the answer for empty input.

Recomputation is otherwise good practice — it is how you avoid concordant bugs.
Keep it, and close the hole one of these ways:

- keep the authoritative copy outside the agent's writable tree and read *that*
- checksum the inputs at task build time and fail the verifier if they changed
- pin the expected value at authoring time, having verified it independently

Ask of every recomputing verifier: **which of its inputs could the agent have
edited?** If the answer is "any", the task measures nothing.

### 6. Is every stated constraint actually enforced?

A rule written in the instruction is a request. The verifier is the only thing
that makes it a rule. Whenever the instruction forbids an approach — "don't use
a parser", "implement it yourself", "no external libraries", "do not install X" —
ask what happens if the agent simply does it anyway.

Watch for a guard that fires at the wrong time. A Dockerfile check like

```dockerfile
RUN if command -v ar >/dev/null 2>&1; then exit 1; fi
```

runs at **build** time. It guarantees the base image ships without the tool; it
does nothing about an agent that installs the tool at run time. The task then
reads as protected while the prohibited shortcut stays one `apt-get` away.

Close it by making the constraint checkable rather than merely stated:

- have the verifier detect the forbidden route in the artifact where it leaves a
  trace (tool-specific defaults, formatting fingerprints, metadata)
- assert at verify time that the tool is still absent
- close network egress, so installing it is not possible in the first place
- or drop the prohibition and design a task where the shortcut does not produce
  a correct answer — much the strongest option, since it needs no enforcement

If none of those hold, the instruction's prohibition is decoration. Either the
task does not actually require the capability it claims to, or it does and you
cannot tell the difference from the reward.

### 7. Does the task reward the wrong thing?

- Does partial or structural credit accrue for output shape alone?
- Would an empty or degenerate answer satisfy some assertions?
- Is there a trivial answer that is technically correct but misses the point
  (the empty set, the identity, zero)? If so, the instruction must exclude it
  and the verifier must reject it.

### 8. What actually ships?

Audit the published task directory, not your working copy. Build artifacts,
caches, and scratch files get committed routinely and can leak expected values
or test structure.

```bash
# What is actually in the task directory?
find <task-dir> -type f | sort

# Anything that should not be there?
find <task-dir> \( -name '.pytest_cache' -o -name '__pycache__' -o -name '*.ipynb_checkpoints' \
  -o -name '*.orig' -o -name '*.bak' -o -name '.DS_Store' \) -print
```

This is not hypothetical: published tasks in this registry carry committed
`.pytest_cache/` directories including `v/cache/nodeids` and `lastfailed`, which
contain test names. Nothing currently audits task contents before publish.

## Running the audit empirically

Reading files is not sufficient — check what the agent actually receives.

1. **Inventory the sandbox.** Run the task with a no-op agent and list the
   filesystem the agent sees. Compare against what you intended to ship.
2. **Probe with a null solution.** Submit an empty or degenerate answer and
   confirm reward is 0. (This overlaps `verifier-hardening`'s negative tests —
   run them here too if they have not been run.)
3. **Probe egress.** From inside the sandbox, attempt one outbound request and
   record whether it succeeds.
4. **Attempt the obvious exploit.** If step 1 revealed the assertions, write the
   answer straight from them and confirm it scores 1 — that converts a suspicion
   into a finding.

Steps 1 and 3 are platform-level and need doing only once per platform.

## Reading trajectories for gaming

When trajectories exist, look for success without domain work:

- reward 1 with no substantive computation in the transcript
- the agent reading test files, fixtures, or the solution directory
- output written before any derivation
- an answer matching the expected values exactly, on a task where independent
  derivation would plausibly differ in formatting
- outbound network calls
- all successes sharing a shortcut that does not generalize

## Output format

```
SURFACE                  STATUS    NOTE
grader visible           CLOSED    tests/ not mounted into agent container
answer in sandbox        OPEN      fixtures/expected.json shipped in task dir
network egress           CLOSED    verified by probe; platform-level
reward writable          CLOSED    reward written outside agent filesystem
trivial answer accepted   CLOSED    empty JSON scores 0 (verified)
shipped artifacts        OPEN      .pytest_cache/ committed

DECISION: FIX  (blocking: answer in sandbox, shipped artifacts)
SCOPE: per-task
```

`DECISION` is `PUBLISH`, `FIX`, or `ESCALATE` (structural hole in the harness).
Never mark a surface `CLOSED` on inspection alone when a probe was available.

## Related

- `task-design-review` — the four difficulty/validity dimensions; contamination there assumes egress is closed here
- `verifier-hardening` — false positives from within a well-formed answer
- `harbor-trajectory-analyser` — produces the trajectories this audit reads
