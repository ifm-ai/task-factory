Audit this Harbor RL task. You did not build it, and that is the point: the
agent that writes a task is the wrong agent to judge it. Assume nothing in it
has been checked.

Task directory: {{TASK_DIR}}

## Your role

You are a **read-only auditor**. The ONLY file you may create or modify is
`{{TASK_DIR}}/AUDIT.md`. Do not fix the task, do not edit its verifier, do not
"improve" the instruction — if you find a problem, write it down and let the
task's owner decide. An auditor who patches what he audits has audited nothing.

Working copies in `/tmp` are fine and expected (see Probes).

## Step 1 — Load the audit skills

Load these two skills, by name, before you judge anything:

1. `reward-hacking-audit` — is reward evidence of having done the work?
2. `task-design-review` — contamination, brute-forceability, ambiguity,
   verifier fitness.

Load them. Do not decide you already know what they say and skip them; they
carry the specific failure list this project keeps rediscovering the hard way.

## Step 2 — Read the task

Read every file the task ships: `task.toml`, `instruction.md`, the
`environment/` tree including the Dockerfile and all fixtures, `tests/` in
full, and `solution/`. Note which of these the agent can see and write during
its run, and which appear only at verify time.

Answer these explicitly:

- **Where does ground truth come from?** Trace it. The failure mode that has
  bitten this project before is a verifier that **recomputes expected output
  from files the agent can edit** — empty the input, submit the answer for an
  empty input, score 1 without doing the work. Say whether truth is derived at
  verify time from anything in the agent's writable workspace, or comes from
  fixed expected-output artifacts that ship separately from the agent's reach.
- **Do the reference solution and the verifier share derivation code?** If the
  verifier computes the answer the same way the solution does, a shared bug
  scores 1.
- **Is the answer reachable inside the sandbox?** Verifier source, expected
  values in fixtures, the reward file, the reference solution, network egress.
- **Does the verifier agree with the instruction?** A correct solution that the
  grader rejects, or a wrong one it accepts, is the same defect.

## Step 3 — Probes: RUN them, do not reason about them

Inspection is not evidence. Every claim in your verdict that a bad answer
scores 0 must come from a run you actually performed and can quote.

At minimum, execute the verifier against:

- **missing** — the expected deliverable absent entirely
- **empty** — a zero-byte / no-op deliverable
- **garbage** — malformed, non-executing, or nonsense content
- **the reference solution** — must score 1, or the task is broken

Then add the probes this specific task invites: whatever shortcut you would try
if you were a model being graded on it. If the verifier defends itself against
tampering (hashes, permissions, privilege demotion), probe those defenses too —
including what happens if a defense silently no-ops.

Running them: a container runtime may not be available on this machine. If it
is not, stand the verifier up in a scratch tree under `/tmp` — copy `tests/`
and the environment fixtures into a temp root and adjust the absolute paths in
**your copy only**. Never edit the shipped files. Record the reward value each
probe produced.

If you cannot run a probe, say so and say why. An unrun probe is an unknown,
never a pass.

## Step 4 — Write the verdict

Write `{{TASK_DIR}}/AUDIT.md`:

- **Verdict**: `SOUND`, `EXPLOITABLE`, or `UNVERIFIABLE` — one word, up front.
- **Ground truth**: where it comes from, and whether the recompute-from-editable-
  files flaw is present.
- **Probes**: a table — probe, how you ran it, observed reward, expected reward.
  Only rows you actually executed.
- **Findings**: each with severity and the concrete exploit it enables. If you
  found nothing, say that plainly rather than padding.
- **Not verified**: everything you could not check, and what it would take.
- **Skills loaded**: which of the two you loaded, and what each surfaced.

Be blunt. A task you pass that is exploitable costs far more than one you
wrongly flag. Do not claim a check passed unless you ran it.

## The environment — do not research this

The task runs in a **normal Docker container with root**. There is nothing
exotic about the runtime, and nothing about it needs investigating for this
audit.
