---
name: verifier-hardening
description: "Make a task verifier trustworthy before it is used as reward signal. Covers concordant bugs (reference solution and verifier sharing a wrong derivation), independent answer verification, output contracts that prevent correct answers from being rejected on formatting, and negative tests that stop empty or wrong answers scoring 1. Use when writing or reviewing tests/, when a task scores 0/k and you suspect the verifier, when agents keep producing the same rejected answer, or before publishing any task whose reward will train or rank a model."
---

# Verifier Hardening

The verifier *is* the task. Everything else is presentation. A verifier that
scores a wrong answer 1, or a right answer 0, produces reward noise — and in RL
that noise is trained on, not just reported.

Two independent failure directions, addressed in that order below:

| Direction | Symptom | Cost |
|---|---|---|
| **False negative** — correct answer rejected | fake difficulty; 0/k that looks impressive | wastes the task, poisons difficulty labels |
| **False positive** — wrong answer accepted | fake competence | poisons reward signal directly |

---

## 1. The concordant bug — the defect that survives oracle validation

**The single largest source of false 0/k scores where the agent is right and the
verifier is wrong.**

It happens when the reference solution and the verifier share a derivation. If
both apply the same wrong formula, the oracle passes — the two agree with each
other — and the task ships with a wrong expected answer. Every agent that solves
it correctly is then marked wrong. Oracle validation cannot detect this, because
oracle validation *is* the two halves agreeing.

**Rule: the reference solution and the verifier must not share derivation code.**
No shared helper module, no copied function, no importing one from the other.

### The independent check protocol

After writing both halves, write a **third** script that neither imports. It must
verify the expected answer against the *original problem statement*, by a
different route than the one that produced it:

- Substitute the answer back into the defining equations and check they hold.
- Verify claimed properties directly (if the answer is "the ring of integers",
  check it is closed under multiplication and integrally closed).
- Recompute by a structurally different method (closed form vs simulation;
  symbolic vs numeric).
- Check invariants that must hold regardless of method (counts, sums,
  determinants, conservation laws, dimensional consistency).

If the oracle passes but this check fails, you have a concordant bug. Trust the
independent check.

```python
# check_independent.py — imports NEITHER solve.sh's logic NOR the verifier's
import json
expected = json.load(open("expected.json"))

# Do not recompute the same way. Verify the defining property.
for root in expected["roots"]:
    assert abs(polynomial_at(root)) < 1e-12, f"{root} does not satisfy the equation"
assert len(set(expected["roots"])) == expected["count"], "count disagrees with the list"
```

**Symmetric warning:** a reference solution that hardcodes the answer instead of
deriving it defeats oracle validation entirely — the oracle then proves only
that the constant matches itself. The reference solution must perform the real
computation.

**Do not "fix" this by recomputing at verify time.** Independence means an
independent route to a **pinned** value — not deriving ground truth during
verification from inputs the agent can modify. A verifier that recomputes from
the agent's own working files is trivially gamed: edit the inputs until the
answer is true. That trades a concordant bug for a reward hack, and every
answer-side negative test still passes. **If your verifier recomputes anything,
check where its inputs live — see `reward-hacking-audit`, surface 5.**

## 2. Output contracts — stop rejecting correct answers

**Principle: if a capable agent understands the problem and follows the
instruction carefully, it should always score 1.** A task must never fail on the
output contract. Every rejection should mean the agent got the domain wrong.

Agents reliably produce these harmless variants — absorb them in the verifier,
do not punish them:

| Agent writes | Verifier must |
|---|---|
| `"42"` instead of `42` | coerce numeric strings |
| `1` where you expect `1.0` | compare numerically, not by type |
| a list in a different order | sort before comparing, when order is not meaningful |
| trailing whitespace / newline | strip |
| `2.9999999996` | compare with a tolerance appropriate to the domain |
| a single value instead of a 1-element list | normalize shape |

```python
def coerce_value(v):
    """Coerce numeric strings so "42" == 42. Use at every comparison point."""
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return s
    return v
```

Parse structured output with `json.loads` — never string-compare serialized
forms. Key order, whitespace, and float formatting all differ harmlessly.

**Anything the verifier will not absorb must be stated in the instruction.**
Sort order, encoding, coefficient order, whether zero is included, how many
digits — if the verifier is strict about it, the instruction must pin it down.
Strictness that is not announced is a trap.

**The asymmetry that matters:** when an agent's answer is domain-correct but
rejected, fix the instruction first, loosen the verifier second, and **never
lower the domain bar.** Making the task easier to *satisfy* is right; making it
easier to *solve* is not.

## 3. Negative tests — stop accepting wrong answers

The other direction, routinely skipped. Before shipping, confirm the verifier
scores **0** on each of these:

- the answer file missing entirely
- an empty file, `{}`, `[]`, or `null`
- the input echoed back unchanged
- a plausible wrong answer — off by one, wrong sign, wrong unit, right shape
- a partially correct answer, if partial credit is not intended
- the right values under the wrong keys

Run these as a checklist against the actual verifier, not by reading it. A
verifier that reads a key which is absent and compares `None == None` scores
empty output as correct — this is common and invisible on inspection.

**Do not hand-roll this harness.** `scripts/probe_verifier.py` runs the whole
battery — reference, missing, empty, garbage, unchanged, degenerate — against a
task's real verifier in a scratch tree, needs no container, and exits non-zero if
any expectation is violated:

```bash
python3 scripts/probe_verifier.py <task-dir>
```

It certifies verifier *logic* against degenerate answers. It does not test
sandbox defences (privilege drops, fixture permissions), which no-op outside a
container — see `reward-hacking-audit`.

## 4. The container the verifier runs in

A verifier can be logically perfect and still score 1 for a candidate that did
nothing, because of *where* it runs. Established by reading the harness, not
assumed:

- The agent and `tests/test.sh` run in the **same container**. Nothing is reset
  between them — every binary, PATH entry and background process the agent left
  is still there when the verifier starts.
- `/logs/{agent,verifier,artifacts}` are **never cleared** between phases. On
  the `docker`, `gke`, `e2b`, `modal`, `daytona` and `apple_container` backends
  the harness `chmod 777`s `/logs/agent` and `/logs/verifier` at container
  start, so the agent can write `reward.txt` during its own phase; if
  verification later dies or times out, that stale value is what gets reported.
- **Some remote backends are the exception, and it changes what you must do.**
  A backend with no `chmod 777` step leaves `/logs/{agent,verifier,artifacts}`
  as plain root-owned `0755` directories on the image overlay (not mounts — the
  harness copies them out of the container at teardown). The reward channel is
  therefore already closed to a demoted agent — but so is `/logs/agent`, which
  the agent phase *must* be able to write. See "Opening /logs/agent" below.
- The reward is read **on the host, after the container is torn down** — not
  when `test.sh` returns. A detached process the agent left running has a wide
  window to overwrite the file after the verdict is in.
- By default both phases run as the image's `USER`, i.e. **root**. `test.sh`'s
  exit code and stdout are ignored; only the file counts.
- The container's own processes are **siblings** of the verifier's exec session,
  not ancestors of it. On a Kubernetes-style backend the container is
  typically `/bin/sh -c sleep infinity` (pid 1) with the real `sleep infinity`
  and a readiness loop as low-numbered children, while `test.sh` is an exec
  session whose ppid is 0. This is why the reap below is scoped by **uid**, never by ancestry.

**The single control that makes any of this fixable is `[agent] user`.** Against
a root agent there is no sound in-container defence: it can replace the shell
that runs `test.sh`, the interpreter, or the reward file, at any time — pinning
an absolute interpreter path does not help, because root can overwrite the file
at that path. Demote the agent and the rest becomes enforceable; leave it root
and every measure below is decoration.

```toml
# task.toml
[agent]
timeout_sec = 900.0
user = "agent"      # the agent, and the oracle running solve.sh, are unprivileged

[verifier]
timeout_sec = 120.0
# `user` deliberately unset: the verifier runs as the image USER (root), which
# it needs in order to seal the reward channel and demote the candidate.

# Opening /logs/agent -- REQUIRED whenever `[agent] user` is set.
# trial.py runs the healthcheck BEFORE it applies the demotion:
#     await self._environment.run_healthcheck()
#     self._environment.default_user = self._task.config.agent.user
# so this is the one hook that still executes as root on every backend. Without
# it, on backends that leave /logs root-owned the agent phase dies at harbor's own redirect
# (`solve.sh > /logs/agent/oracle.txt`) with "Permission denied": exec exit
# code 1, empty oracle.txt, and — for the oracle — no answer to verify.
# /logs/verifier is deliberately NOT widened.
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
    # Kill leftovers owned by the agent uid, and NOTHING else.
    #
    # Never reap by ancestry ("kill every pid outside my own chain"). The
    # sandbox's own processes are siblings of this exec session, not ancestors
    # of it: on a Kubernetes-style backend that reaps the `sleep infinity`
    # keeping pid 1 alive, and the container dies mid-verification — exec returns 137, every
    # volume pull afterwards 404s, and no reward file is ever produced. This
    # was measured, not theorised.
    #
    # Defence in depth only: once the agent is demoted and reward.txt is
    # root-written into a root-owned 0755 directory, a surviving agent daemon
    # cannot revise the verdict anyway. Drop this if the task legitimately runs
    # in-container services as the agent user.
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

# Destroy any reward the agent pre-wrote; the channel was 777 all through its phase.
rm -f "$REWARD_DIR/reward.txt" "$REWARD_DIR/reward.json"

if [ "$(id -u)" -ne 0 ]; then
    # The real verifier is always root. Reaching here means offline probing --
    # say so, rather than pretending the defences ran.
    # Fail closed: a reward computed with the defences inert is not
    # trustworthy. probe_verifier.py opts in and labels its results.
    [ "${HARBOR_OFFLINE_PROBE:-}" = "1" ] \
        || _harden_fail "uid $(id -u), not 0 -- defences cannot engage"
    echo "[test.sh] OFFLINE PROBE: defences inert, not production-valid." >&2
else
    # Seal the reward channel first: root-owned, not group/other writable.
    chown 0:0 "$REWARD_DIR" && chmod 0755 "$REWARD_DIR" || fail_closed "cannot seal $REWARD_DIR"
    chmod 0700 /tests || fail_closed "cannot seal /tests"
    # Refuse to score if the agent was root -- it could undo all of the above.
    id -u "$AGENT_USER" >/dev/null 2>&1 || fail_closed "no '$AGENT_USER': [agent] user did not take effect"
    reap_strays
    [ -e "$ANSWER" ] && [ -O "$ANSWER" ] && fail_closed "$ANSWER is root-owned: the agent ran as root"
    # Smoke alarm, not a lock: catches the usual shell-script interpreter shim.
    [ -f "$PY" ] || fail_closed "$PY is missing"
    [ "$(head -c 4 "$PY" | od -An -tx1 | tr -d ' \n')" = "7f454c46" ] \
        || fail_closed "$PY is not the image's ELF interpreter"
fi

# -I -S: isolated, no site module, so a planted sitecustomize.py cannot run here.
"$PY" -I -S /tests/verify.py > "$REWARD_DIR/verify.log" 2>&1
rc=$?
[ "$(id -u)" -eq 0 ] && reap_strays

# The reward is written last, into a directory only root can write.
if [ "$rc" -eq 0 ]; then echo 1 > "$REWARD_DIR/reward.txt"; else echo 0 > "$REWARD_DIR/reward.txt"; fi
exit 0
```

**If `verify.py` executes the agent's code**, that code must not run with the
verifier's privileges — otherwise it reads the pinned answers out of
`/tests/verify.py` via `/proc/<ppid>/cmdline` and emits them. Drop to the agent
user, and prove the drop works before trusting it:

```python
def demotion_target():
    if os.geteuid() != 0:
        return None                     # off-container only; preflight warns
    import pwd
    ent = pwd.getpwnam("agent")
    return ent.pw_uid, ent.pw_gid

def _demote_to(uid, gid):
    os.setgid(gid); os.setgroups([]); os.setuid(uid)
    if os.getuid() != uid:
        os._exit(93)

def preflight(target):
    """Refuse to score if the drop cannot happen. Never fall back to root."""
    if target is None:
        sys.stderr.write("WARNING: not root -- candidate NOT demoted. Probing only.\n")
        return
    uid, gid = target
    probe = subprocess.run([sys.executable, "-I", "-S", "-c",
                            "import os,sys; sys.stdout.write(str(os.getuid()))"],
                           preexec_fn=lambda: _demote_to(uid, gid),
                           capture_output=True, timeout=15)
    if probe.stdout.decode().strip() != str(uid):
        raise SystemExit("HARDENING FAILURE: cannot drop privileges to uid %d" % uid)

# then: subprocess.run([...], preexec_fn=lambda: _demote_to(*target))
```

Exit codes are truncated to 8 bits, so the probe reports the uid on **stdout** —
comparing `returncode` to a uid above 255 silently succeeds for the wrong reason.

`probe_verifier.py` runs off-container as an ordinary user, so it takes the
non-root branch and reports the inert-defences warning. That is expected; it
certifies verifier *logic*, and cannot certify any of this section.

## 5. Keep it tight

A 200-line verifier checking fifteen edge cases is worse than a 20-line verifier
checking the one thing that matters. Every additional assertion is another
chance to reject a correct answer. Check the substance of the task, absorb the
formatting, and stop.

If making a task work requires an elaborate verifier, that is evidence the task
is badly shaped. Reshaping it, or abandoning it for a cleaner candidate, beats
hardening a bad one.

## Checklist

Before a verifier is trusted as reward:

- [ ] Reference solution and verifier share no derivation code
- [ ] An independent third check confirms the expected answer against the problem statement
- [ ] The reference solution computes, rather than hardcodes, the answer
- [ ] Structured output parsed, not string-compared
- [ ] Numeric strings coerced; ints and floats compared numerically
- [ ] Order-insensitive comparisons sorted; tolerances chosen for the domain
- [ ] Every strictness the verifier enforces is stated in the instruction
- [ ] Missing / empty / null / echoed input all score 0 — verified by running them
- [ ] A plausible wrong answer scores 0 — verified by running it
- [ ] The verifier checks the thing the task is actually about
- [ ] `[agent] user` is set to an unprivileged user the Dockerfile creates, and `test.sh` refuses to score if it did not take effect
- [ ] `[environment.healthcheck]` opens `/logs/agent` (and `/logs/artifacts`) so the demoted agent can write its log — without it the agent phase fails on backends that leave /logs root-owned
- [ ] `test.sh` deletes any pre-existing reward file, seals `/logs/verifier`, reaps **by uid** (never by ancestry), and writes the reward last
- [ ] The hardening was proved by a real oracle run on the real backend, not only by `probe_verifier.py` or a host-side emulation — the emulation cannot see the sandbox's own process tree or the backend's log-dir permissions
- [ ] Agent code the verifier executes runs demoted, and a failed drop refuses to score rather than falling back to root

## Related

- `task-design-review` — dimension 4 asks whether the verifier is fit; this skill makes it fit
- `reward-hacking-audit` — whether reward can be obtained without producing an answer at all
- `rewardkit` — Reward Kit mechanics for expressing verifiers and graders
