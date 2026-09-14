---
name: harbor-trajectory-analyser
description: "Analyze agent trajectories from Harbor evaluation runs to diagnose why agents succeed or fail. Use when you have a trial directory from a harbor run and want to understand the agent's behavior, identify failure modes, find wasted effort, and get actionable feedback for improving tasks or agents."
---

# Harbor Trajectory Analyzer

Diagnose agent behavior from Harbor evaluation runs. Point me at a trial directory and I'll tell you what happened, why, and what to do about it.

## Quick Start

- "Analyze `/path/to/harbor_jobs/2026-03-25__03-36-28/lean-two-group-structures__MpsiXne`"
- "Why did the agent fail on this run?" (with trial path)
- "Analyze all trials in `/path/to/harbor_jobs/2026-03-25__03-36-28/`"

---

## Protocol

When this skill is invoked, follow this protocol.

### Step 0: Identify the Target

The user provides either:
- **A trial directory** (contains `agent/`, `verifier/`, `config.json`, `trial.log`) — analyze one trial
- **A job directory** (contains `result.json` and multiple `task__ID/` subdirs) — batch mode, analyze all trials

If unclear, infer the best target from pipeline state or available artifacts. Only ask for clarification if multiple plausible targets exist and choosing the wrong one would waste a run.

### Step 1: Read the Trial

For each trial, read these files (they may not all exist):

**Always read:**
- `config.json` — task config, agent type, model, timeouts
- `result.json` — reward, timing, token usage (if present)
- `trial.log` — Harbor's own log of environment setup, agent invocation, verifier run

**Agent trace (the big one):**
- `agent/<agent>.txt` (e.g. `claude-code.txt`) — full agent trajectory (tool calls, reasoning, outputs). This can be huge (100KB+). Read strategically:
  - First 50 lines: what did the agent do first?
  - Last 50 lines: how did it end? timeout? completion? error?
  - Search for `error`, `fail`, `timeout`, `FAIL` to find problems
  - Search for `tool_use` to understand the sequence of actions
  - Search for `<think>` tags to read the agent's reasoning at key moments

- `agent/exit-code.txt` — agent process exit code (0=success, non-zero=crash/timeout)
- `agent/oracle.txt` — if oracle run, the solution script output

**Verifier output:**
- `verifier/reward.txt` — the final reward (0 or 1, or float)
- `verifier/test-stdout.txt` — test script output (why it passed/failed)
- `verifier/build_output.txt` — build/compile output (if present)
- `verifier/ctrf.json` — structured test results (if pytest was used)

**Task instruction (from the task source, not the trial):**
- Find the task path from `config.json` → `task.path`
- Read the original `instruction.md` from the task directory

### Step 2: Produce the Diagnosis

Structure your analysis as follows:

```
## Trajectory Analysis: {task_name}

### Outcome
- **Reward**: {0.0 or 1.0}
- **Agent exit code**: {code}
- **Wall time**: {seconds}
- **Tokens used**: {input/output/total if available}

### Timeline
Break the agent's trajectory into phases with approximate time spent:
1. **Setup** (Xs): What environment setup did the agent do?
2. **Understanding** (Xs): How did it interpret the task?
3. **Attempt 1** (Xs): First approach — what was it?
4. **Debugging** (Xs): What errors did it hit, how did it respond?
5. **Attempt N** (Xs): Subsequent attempts
6. **Final state**: What was the last thing the agent did?

### Failure Mode (if reward < 1.0)

Classify into one of these categories:
- **SETUP_FAILURE**: Agent couldn't set up the environment (install tools, deps)
- **WRONG_APPROACH**: Agent misunderstood the task or chose a fundamentally wrong strategy
- **PARTIAL_SOLUTION**: Right approach but incomplete or buggy implementation
- **CORRECT_BUT_REJECTED**: Agent's solution is actually correct but the verifier rejected it (verifier bug)
- **TIMEOUT**: Agent ran out of time
- **LOOP**: Agent got stuck repeating the same failed approach
- **TOOLING_ERROR**: Agent's tools crashed or misbehaved (not the agent's fault)
- **INSTRUCTION_AMBIGUITY**: The task instruction was unclear and the agent interpreted it differently than intended

Explain which category applies and why.

### Key Moments
List the 3-5 most important decisions or turning points:
- "At [timestamp/step N], the agent decided to X instead of Y — this was the critical mistake"
- "At [step N], the agent correctly identified the issue but then Y"
- "The agent spent N minutes on X, which was wasted because Y"

### Root Cause
One paragraph: the single most important reason for the outcome.

### Recommendations
- **For the agent/model**: What should it have done differently?
- **For the task**: Should the instruction, verifier, or environment change?
- **For the benchmark**: Is this task fairly testing what it claims to test?
```

Also produce a normalized re-entry recommendation for the coordinator:
- `REENTER_ORACLE_2`
- `REENTER_CALIBRATION`
- `READY_TO_PUBLISH`
- `NEEDS_HUMAN_DECISION`

### Step 3: Batch Mode (Job Directory)

If analyzing a full job directory with multiple trials:

1. Read `result.json` for the summary stats
2. Analyze each trial (can use Agent tool for parallelism on large jobs)
3. Produce a summary table:

```
| Task | Reward | Failure Mode | Time | Root Cause |
|------|--------|-------------|------|------------|
| task-a | 1.0 | — | 45s | — |
| task-b | 0.0 | SETUP_FAILURE | 120s | curl not installed |
| task-c | 0.0 | LOOP | 1800s | Retried same broken syntax 5x |
```

4. Identify **patterns** across failures:
   - Are multiple tasks failing for the same reason?
   - Is setup time dominating? (suggests environment should pre-install tools)
   - Is the model consistently making the same kind of mistake?

### Step 4: Interactive Follow-up

After presenting the analysis, be ready for:
- "Show me what the agent was thinking at step N"
- "What was the exact error message?"
- "Compare this run to the previous one"
- "What would the agent need to do differently to pass?"

Read more of the trajectory as needed to answer these.

## Difficulty Ladder Use

When this skill is used inside the task factory, help place the current run in the three-level difficulty ladder.

Interpret calibration outcomes this way:
- if the agent solves the current version cleanly, the current version can become one of the easier levels and the next iteration should consider a harder successor
- if the agent fails, determine whether the failure indicates genuine difficulty, verifier/environment failure, or instruction ambiguity

Only genuine difficulty should be used as evidence for a harder tier. Environment and verifier failures should route back to oracle-level fixes instead.

## Artifact Preservation

Never recommend discarding prior agent runs. Preserve:
- each trial directory
- each task variant
- the mapping from variant to trial result

## Orchestrator Contract

Return a concise structured summary:

```text
FAILURE_MODE: <normalized failure mode or SUCCESS>
REENTRY: REENTER_ORACLE_2|REENTER_CALIBRATION|READY_TO_PUBLISH|NEEDS_HUMAN_DECISION
DIFFICULTY_SIGNAL: easier|matched|harder|invalidated-by-tooling
ROOT_CAUSE: <one short line>
NOTES: <one short line>
```

---

## Reading Large Trajectories Efficiently

The agent transcript in `agent/` is typically JSON-lines (one JSON object per line). Each line has a `type` field:

- `type: "step_start"` — new reasoning step
- `type: "text"` — agent's response text (may contain `<think>` tags)
- `type: "tool_use"` — tool call with input/output
- `type: "step_finish"` — step completed, includes token counts

Strategy for large files:
1. Check file size first (`wc -l` / `wc -c`)
2. Read first 30 lines (initial approach)
3. Read last 30 lines (final state)
4. Grep for `"tool"` entries to get the action sequence
5. Grep for `error\|fail\|FAIL\|timeout` to find problems
6. Read specific sections around identified problems

Do NOT try to read a 400KB+ file in one shot — it will exceed token limits.

---

## Reference: Trial Directory Structure

```
task-name__HASH/
├── config.json          # Task + agent + environment configuration
├── result.json          # Reward, timing, tokens (may be at job level only)
├── trial.log            # Harbor's orchestration log
├── agent/
│   ├── <agent>.txt      # Full agent trajectory (name depends on the agent)
│   ├── exit-code.txt    # Agent process exit code
│   ├── oracle.txt       # Oracle agent output (if -a oracle)
│   ├── setup/           # Agent setup logs
│   └── command-N/       # Individual command outputs
├── verifier/
│   ├── reward.txt       # Final reward (0, 1, or float)
│   ├── test-stdout.txt  # Test script stdout
│   ├── build_output.txt # Build output (if applicable)
│   └── ctrf.json        # Structured test results (if pytest)
└── artifacts/           # Task-specific artifacts
```

## Reference: Common Failure Patterns

| Pattern | Symptoms | Usual Cause |
|---------|----------|-------------|
| Missing tool | `command not found` in early steps | Bare ubuntu, agent didn't install deps |
| Dependency spiral | Agent installing 5+ packages | Task should pre-install in Dockerfile |
| Version mismatch | Works locally, fails in container | Pinned vs latest version conflict |
| Path confusion | File written to wrong location | instruction.md says one path, framework expects another |
| Syntax churn | Same file rewritten 3+ times | Agent guessing syntax instead of reading docs |
| Silent timeout | Agent trace just stops, no error | Exceeded `agent.timeout_sec` |
| Verifier false negative | Solution looks correct, reward=0 | Bug in test.sh or test_state.py |
| Verifier false positive | Trivial solution, reward=1 | Verifier only checks file existence, not content |
