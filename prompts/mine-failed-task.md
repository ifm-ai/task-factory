Here is ONE trial where a model attempted a task and failed. Work out what it got wrong, then build a Harbor RL task that trains the missing skill.

Evidence digest: {{DIGEST}}
Output directory: {{OUT_DIR}}

**Source policy.** The trial must come from a task you own: this factory's
output, or your own dev tasks. Never mine a trial from a benchmark you report
results on. The task you build must not restage the source: fresh content, a
distinct instance, a different surface (Step 2 says how), so that nothing
about the source is recoverable from it.

## Step 1 — Work out what went wrong

**Read the digest. It is one file and it is all you need to start.** It already
contains the task instruction the agent was given, the failing assertions with
context, and every step the agent took. The raw trial is at `{{TRIAL_DIR}}` if
you later need one specific detail — but do not go there first, and never print
those files whole; they are ~300 KB.

Read the instruction section before judging the agent. Tasks routinely contain a
constraint or an explicit allowance the agent missed, and the failure is often
there rather than in the agent's reasoning.

Then answer one question: **what capability was the agent missing?**

State it generally, not as "it failed this benchmark task". "Did not check the
exit status of a piped command" is a capability. "Failed test_foo" is not.

Write `{{OUT_DIR}}/FINDINGS.md`: the capability gap, the evidence for it
(quote the failing assertion and the agent's mistaken step), and one sentence
on how you would test that capability in isolation.

## Step 2 — Build a task that trains it

### Preserve the artifact complexity, not just the capability

Measured across this pipeline: mining a solved-by-nobody source into a small
clean task reliably makes it *easier*, and the derived task then gets solved
4/4 while its own source is failed 0/8. Three mechanisms were measured doing
it — abundant decoys advertise the requirement they test, precise
specification names the answer, and anything authored fresh is smaller and
cleaner than the real artifact it replaces.

So the difficulty carrier is part of the deliverable:

- **Keep what made the source hard.** Realistic code, real dependencies,
  multi-step state across components, genuine data volume, and any visual or
  perceptual information the source required. If the source needed three
  interacting databases, a single CSV is not a substitute.
- **Fresh content and a distinct instance are required**; a different domain
  is optional. Do not copy the source's data, names, or numbers — but do not
  shrink its structure either.
- **Do not state the rule the task is testing.** Say what to produce and in
  what format. An instruction must be unambiguous about the contract and
  silent about the method.

### "Unsuitable source" is an allowed outcome

If the evidence does not support a sound task — the failure is a timeout, a
setup or dependency problem, broken or opaque grading, ambiguity in the
original instruction, or missing inputs — **say so and stop.** Write
`RESULTS.md` with the evidence for that judgement and build nothing. A task
forced out of a bad source wastes far more than the session that declined it.


Create ONE Harbor task at `{{OUT_DIR}}/<task-name>/`.

Design it so that an agent possessing the missing capability passes, and an
agent lacking it fails. That is the entire point — everything else is detail.

Guidance:
- **Do not restage the original task.** Different domain, different surface,
  same underlying skill. If the agent mishandled encoding round-trips in HTML,
  your task might use CSV or JSON instead.
- **Make it small.** One clear deliverable, written to one path. A task that
  takes an agent 20 focused steps beats one that takes 200.
- **Make the difficulty be the capability**, not the reading. The instruction
  should be short and unambiguous; the challenge is in doing the thing, not
  decoding what was asked.
- **State the contract; do not enumerate the traps.** Specify the rules the
  output must satisfy, completely and unambiguously — "RFC 4180 CSV; every byte
  not removed is preserved exactly" is a complete contract. Then STOP. Do not
  also list the edge cases that contract implies (embedded newlines, CRLF,
  doubled quotes, quotes appearing mid-field). Let the test cases probe those
  unannounced.

  An itemised trap list turns the task into transcription: the agent implements
  your checklist instead of reasoning about the format. A complete contract is
  still fair — an agent that thinks it through finds the cases itself, which is
  exactly the capability being measured. This does not conflict with pinning
  down ambiguity: every strictness the verifier enforces must follow from the
  stated contract, it just need not be spelled out case by case.
- **Bake in the trap.** The task should be one where the naive approach — the
  one the failing agent took — produces a plausible but wrong result.
- **Grade the contract you stated, not a sample of it.** Every "any X" in your
  instruction is a promise the verifier has to keep. If the instruction says
  "any integer up to 10^18" and the verifier tries 25 values, a program correct
  on those 25 and wrong everywhere else scores 1 — and under RL you train that
  program. For each "any X" you write, name the input where a shortcut or a
  naive implementation diverges from a correct one, and grade that input. If you
  cannot cover the domain you claimed, narrow the claim to what you grade.

  For a task built around one artifact to recover or repair, the graded input is
  the artifact and is necessarily visible. The guarantee there comes from grading
  properties the shortcut cannot satisfy, not from hidden inputs.

  Then attack your own task, twice:
  - Submit a solution deliberately wrong *outside* your graded set — correct on
    the cases you check, wrong past your largest size, wrong on the edge case you
    left out. Scoring 1 means your verifier under-samples its own contract.
  - Run the two or three cheapest routes a competent agent would try first, from
    the agent's starting state. One of these tasks was solved by a stray
    `ORIG_HEAD` left behind by the command that built its fixture.

  Record both probes and their scores in `RESULTS.md`.
- **Prefer a design where the shortcut cannot work, over a prohibition**
  (audit surface 6). A prohibition the verifier cannot check is decoration. A
  task whose shortcut produces a *wrong answer* needs no enforcement at all.

Load skills only when you reach the step that needs them — loading all four up
front spends context before you have written anything:

- Now, to build: `harbor-task-creator` (layout), then `verifier-hardening`
  (read before writing the verifier).
- Only once the task files exist: `reward-hacking-audit`, then
  `task-design-review`. Both are required before you declare the task done.

Hard requirements:
- Reference solution and verifier share NO derivation code.
- The verifier must NOT recompute ground truth from files the agent can edit
  (audit surface 5 — trivially gamed).
- Every constraint the instruction states, the verifier enforces. An instruction
  is a request; the verifier is what makes it a rule. If you cannot check one,
  first ask which it is: decoration you can simply delete, or the capability
  itself. If it is the capability, deleting it leaves a task that trains
  nothing — redesign so the shortcut yields a *wrong* answer, or abandon the
  task. Abandoning is cheap.
- If `verify.py` executes the agent's program, demote it before exec and refuse
  to score if the drop fails — otherwise it reads the pinned answers straight
  out of `/tests/verify.py`. Do not pass expected values on its argv or in its
  environment either. `verifier-hardening` section 4 has the snippet.
- Run empty / missing / garbage answers and confirm each scores 0.

## The environment — do not research this

Your task runs in a **normal Docker container**. Write an ordinary Dockerfile:
`FROM python:3.12-slim`, `apt-get install` whatever you need. Two things are
not optional, because the agent and the verifier share one container that is
never reset between them:

- the Dockerfile creates an unprivileged `agent` user and gives it `/app`, while
  the image `USER` stays root (the verifier needs root);
- `task.toml` sets `[agent] user = "agent"`, so the agent — and the oracle
  running `solve.sh` — cannot replace the interpreter, the shell, or the reward
  file. A root agent can defeat any verifier, so this is what makes yours mean
  anything.

Nothing else about the runtime concerns you.

You are writing into a **fresh, empty task collection**. There are no existing
conventions to match and no sibling tasks to imitate. Do NOT go looking through
other directories for examples — the `harbor-task-creator` skill has the format,
and this is the complete shape:

```
<task-name>/
├── task.toml
├── instruction.md            # what the agent must do
├── environment/Dockerfile    # FROM python:3.12-slim, plus anything you need
├── environment/<fixtures>    # any input files, COPY'd in by the Dockerfile
├── tests/test.sh             # runs the verifier, writes /logs/verifier/reward.txt
├── tests/verify.py           # the verifier
└── solution/solve.sh         # reference solution
```

```toml
version = "1.0"

[metadata]
name = "<task-name>"
difficulty = "hard"
category = "<domain>"
description = "<one line>"

[agent]
timeout_sec = 900.0
user = "agent"

[verifier]
timeout_sec = 120.0
# `user` deliberately unset: the verifier runs as the image USER (root).

# Required because [agent] user is set. Harbor runs the healthcheck as root
# BEFORE it demotes the agent, and on some backends /logs/agent is a root-owned
# 0755 directory -- without this the agent phase dies at harbor's own
# `solve.sh > /logs/agent/oracle.txt` redirect. Do NOT widen /logs/verifier.
[environment.healthcheck]
command = "mkdir -p /logs/agent /logs/artifacts && chmod 777 /logs/agent /logs/artifacts"
```

```dockerfile
FROM python:3.12-slim
RUN useradd --create-home --uid 1000 agent
WORKDIR /app
COPY <fixtures> /app/
RUN chown -R agent:agent /app
# image USER stays root -- only the agent phase is demoted, by task.toml.
```

```bash
#!/bin/bash
# tests/test.sh -- runs as root, from /tests/, after the agent has finished.
set -uo pipefail

AGENT_USER=agent
PY=/usr/local/bin/python3
REWARD_DIR=/logs/verifier
ANSWER=/app/<the deliverable>

mkdir -p "$REWARD_DIR"

reap_strays() {
    # Kill leftovers owned by the agent uid, and NOTHING else. Never reap by
    # ancestry: the sandbox's own processes are siblings of this exec session,
    # not ancestors of it, so "kill everything outside my chain" kills the
    # container's `sleep infinity` and the sandbox dies mid-verification
    # (exec 137, volume pulls 404, RewardFileNotFoundError).
    local uid d pid
    uid=$(id -u "$AGENT_USER" 2>/dev/null) || return 0
    [ -n "$uid" ] || return 0
    for d in /proc/[0-9]*; do
        pid=${d#/proc/}
        [ "$(stat -c %u "$d" 2>/dev/null)" = "$uid" ] || continue
        kill -9 "$pid" 2>/dev/null && echo "[test.sh] reaped stray pid $pid" >&2
    done
}

fail_closed() {
    echo "[test.sh] HARDENING FAILURE: $*" | tee -a "$REWARD_DIR/verify.log" >&2
    rm -f "$REWARD_DIR/reward.json"
    echo 0 > "$REWARD_DIR/reward.txt"
    exit 0
}

# Destroy any reward the agent pre-wrote: the channel was world-writable
# throughout its phase and is never cleared for you.
rm -f "$REWARD_DIR/reward.txt" "$REWARD_DIR/reward.json"

if [ "$(id -u)" -ne 0 ]; then
    # Fail closed: a reward computed with the defences inert is not
    # trustworthy. probe_verifier.py opts in and labels its results.
    [ "${HARBOR_OFFLINE_PROBE:-}" = "1" ] \
        || _harden_fail "uid $(id -u), not 0 -- defences cannot engage"
    echo "[test.sh] OFFLINE PROBE: defences inert, not production-valid." >&2
else
    chown 0:0 "$REWARD_DIR" && chmod 0755 "$REWARD_DIR" || fail_closed "cannot seal $REWARD_DIR"
    chmod 0700 /tests || fail_closed "cannot seal /tests"
    id -u "$AGENT_USER" >/dev/null 2>&1 || fail_closed "no '$AGENT_USER': [agent] user did not take effect"
    reap_strays
    [ -e "$ANSWER" ] && [ -O "$ANSWER" ] && fail_closed "$ANSWER is root-owned: the agent ran as root"
    [ -f "$PY" ] || fail_closed "$PY is missing"
    [ "$(head -c 4 "$PY" | od -An -tx1 | tr -d ' \n')" = "7f454c46" ] \
        || fail_closed "$PY is not the image's ELF interpreter"
fi

"$PY" -I -S /tests/verify.py > "$REWARD_DIR/verify.log" 2>&1
rc=$?
[ "$(id -u)" -eq 0 ] && reap_strays

# The reward is written last, into a directory only root can write.
if [ "$rc" -eq 0 ]; then echo 1 > "$REWARD_DIR/reward.txt"; else echo 0 > "$REWARD_DIR/reward.txt"; fi
exit 0
```

If `verify.py` executes the agent's program, demote it to the `agent` user
before exec and refuse to score if the drop fails — otherwise it reads the
pinned answers straight out of `/tests/verify.py`. `verifier-hardening` section
4 has that snippet.

Size `[agent] timeout_sec` to the task. 900s is a reasonable default; a task
needing exploration or several build-test cycles may want more. Set it too tight
and a capable agent gets killed mid-run and scores 0 for the wrong reason, which
makes the task look harder than it is.

`test.sh` must write `1` or `0` to `/logs/verifier/reward.txt` on **every** code
path, including when the answer file is missing.

Spend your effort on the task and its verifier, not on the scaffolding.

## Step 3 — Validate

### 3a. Oracle first — always, and it needs no model

**Write every file before you run the oracle.** Confirm all four exist:

    ls {{OUT_DIR}}/<task-name>/task.toml \
       {{OUT_DIR}}/<task-name>/instruction.md \
       {{OUT_DIR}}/<task-name>/tests/test.sh \
       {{OUT_DIR}}/<task-name>/solution/solve.sh

A directory holding only `task.toml` is not a task. Harbor rejects it with
`Either datasets or tasks must be provided` — an error about *arguments*, which
looks like you invoked the command wrongly and invites you to retry with
different flags. Retrying cannot work: the missing files are the problem. One
run has already been lost this way, looping on that error until its time expired
instead of writing `tests/` and `solution/`.

If you see that message, stop and check the four paths above.

Then confirm the task is solvable in the real sandbox by running its reference
solution:

    harbor run -p {{OUT_DIR}}/<task-name>

The oracle agent executes `solution/solve.sh`; it never calls an LLM, so this
works even when no model endpoint is available. A task that fails here is broken
regardless of any agent — fix it before going further. Record the oracle result
in `RESULTS.md` as soon as you have it.

### 3b. Difficulty — record it UNCALIBRATED and move on

**There is no model endpoint for this run, and there will not be one.** Do not
look for one, do not curl for one, do not attempt pass@4. This is the expected
state, not a problem to work around.

Record in `RESULTS.md`:

    difficulty: UNCALIBRATED (no model endpoint available)

Then finish everything else — the reward-hacking audit, the design review, the
write-up — and stop. That is a complete, useful result: an oracle-validated,
audited task awaiting calibration. It is not a failure, and it must not be
reported as one.

The oracle in 3a is your gate. A task that passes it and survives the audit and
the design review is done, as far as this run is concerned.

## Write RESULTS.md EARLY and keep updating it

**As soon as the oracle run finishes, write `{{OUT_DIR}}/RESULTS.md`.** Do
not save it for the end.

Sessions get killed — by wall-clock limits, by context exhaustion. A partial
report on disk is worth far more than a complete one you never got to write.
Runs have been lost exactly this way: task built, oracle passed, nothing
recorded.

Write it, then update it as you learn more. If you change the task and re-run,
update the file again. At every moment, the file on disk should reflect
everything you currently know.

## Step 4 — Finish the report

You already created `RESULTS.md` above. Complete it now — the capability gap,
what the task asks, the oracle result, **the two adversarial probes from Step 2
and the score each returned**, the difficulty label, the reward-hacking-audit
verdict, which skills you loaded, and anything you could not verify.

Be honest about what failed or was skipped. Do not claim a check passed unless
you ran it.
