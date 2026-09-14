---
name: harbor-task-refine
description: "Evaluate and iteratively improve Harbor benchmark tasks using parallel grader and verifier agents. Use when you have an existing task directory and want to assess quality, difficulty, verifier coverage, and fix issues automatically. Grades tasks on clarity, difficulty, and test robustness, then hands off to the coordinator for oracle validation."
---

# Harbor Task Refine

Evaluate and iteratively improve an existing Harbor task directory using two parallel agents (grader + verifier) in a feedback loop.

## When to Use

- After creating a task with `/harbor-task` to polish it
- To grade difficulty and quality of existing tasks
- To check if verifiers actually catch wrong solutions
- To validate that oracle passes before running real agents

## Quick Start

Point me at a task directory:
- "Refine `lean-two-group-structures/`"
- "Grade and fix `my-new-task/`"
- "Check the quality of all tasks in `tasks/`"

---

## Orchestration Protocol

When this skill is invoked, follow this protocol exactly. You are the **coordinator**. You spawn agents for evaluation, collect feedback, apply fixes, and iterate.

### Step 0: Identify the Task

Accept the task directory from context or pipeline state. Read all task files to understand what we're working with:

- `task.toml`
- `instruction.md`
- `environment/Dockerfile` (if present)
- `tests/test.sh`
- `tests/test_state.py` (if present)
- `solution/solve.sh`

### Step 1: Spawn Grader + Verifier in Parallel

Use the **Agent tool** to spawn two agents simultaneously in a single message. Both agents receive the full task content.

#### Grader Agent

Spawn with `subagent_type: "general-purpose"` and this prompt structure:

```
You are a Harbor benchmark task grader. Evaluate the following task and produce a structured report.

## Task Files
[paste all task file contents here]

## Evaluation Criteria

Rate each criterion 1-5 and explain your reasoning:

### 1. Clarity (1-5)
- Is the instruction unambiguous?
- Could a capable AI agent misinterpret what's being asked?
- Are success criteria explicit?

### 2. Difficulty Assessment
Rate as: easy / medium / hard
- Easy: single-step, obvious approach (e.g., create a file, write a simple function)
- Medium: multi-step, requires reasoning or domain knowledge
- Hard: complex, open-ended, requires specialized expertise
Explain what makes it this difficulty level.

### 3. Verifier Coverage (1-5)
- Do the tests actually verify what the instruction asks?
- Could a wrong solution pass the tests? (false positive risk)
- Could a correct solution fail the tests? (false negative risk)
- Are edge cases covered?

### 4. Solution Quality (1-5)
- Does solve.sh demonstrate the intended approach?
- Would oracle validation (running solve.sh then test.sh) pass?
- Is the solution minimal and correct?

### 5. Environment Fitness (1-5)
- Is the Dockerfile/docker_image appropriate for the task?
- Are all required dependencies available or installable?
- Are timeouts realistic for the task complexity?
- Is storage/memory sufficient?

### 6. Benchmark Value (1-5)
- Does this task test a meaningful capability?
- Is it distinguishing? (Would it separate good agents from bad ones?)
- Is it fair? (No trick questions, no reliance on training data)

## Output Format

Produce your report as:

GRADES:
- clarity: N/5
- difficulty: easy|medium|hard
- verifier_coverage: N/5
- solution_quality: N/5
- environment_fitness: N/5
- benchmark_value: N/5
- overall: N/5

ISSUES:
- [List each specific problem found]

SUGGESTIONS:
- [List each specific improvement, referencing which file to change]
```

#### Verifier Agent

Spawn with `subagent_type: "general-purpose"` and this prompt structure:

```
You are a Harbor benchmark task verifier. Your job is to check that the task's test infrastructure is correct and robust.

## Task Files
[paste all task file contents here]

## Verification Checks

Perform each check and report pass/fail with explanation:

### 1. Structural Completeness
- [ ] task.toml exists and has valid TOML syntax
- [ ] task.toml has version, metadata, verifier, agent, environment sections
- [ ] instruction.md exists and is non-empty
- [ ] tests/test.sh exists and is executable-ready (starts with #!/bin/bash)
- [ ] tests/test.sh writes to /logs/verifier/reward.txt
- [ ] solution/solve.sh exists (warn if missing, not fatal)
- [ ] environment/Dockerfile exists OR docker_image is set in task.toml

### 2. Test Script Analysis
- Does test.sh handle missing dependencies gracefully?
- Does test.sh produce reward.txt in ALL code paths (success AND failure)?
- If using pytest: are the --with packages pinned to specific versions?
- If using uvx: is the uv install fallback present?
- Could test.sh hang or timeout silently?

### 3. Verifier Robustness
- Read test_state.py (if present). For each assertion:
  - What exactly does it check?
  - Could a trivially wrong solution pass it? (false positive)
  - Could a correct solution fail it? (false negative)
- If script-based (no pytest): are the conditions specific enough?
- If LLM-as-Judge: is the rubric clear and the endpoint configured?
- **CRITICAL — False negative analysis**: For every grep/regex/pattern check in test.sh:
  - List ALL valid alternative syntaxes a correct solution might use
  - Could the agent use a synonym, different keyword, different code pattern?
  - Example: checking for `^instance` in Lean misses `def foo : Group T := ...` which is equally valid
  - Example: checking for `def solve` misses `function solve` or `const solve =`
  - For each pattern, ask: "If I were a capable agent solving this correctly, what are 3 different ways I might write this?" and verify the check accepts all of them

### 4. Solution-Test Alignment
- Trace through solve.sh mentally. Would its output pass every test?
- Are file paths consistent between solve.sh, instruction.md, and test assertions?
  (Common bug: instruction says /app/output.txt, test checks /output.txt)
- Do environment variables match between [solution] and [verifier] sections?

### 5. Environment Compatibility
- Will the Dockerfile build without root-only steps, so it works on rootless or non-Docker backends?
  (Known issues: multi-stage builds, USER directives, systemd services)
- Are apt-get commands tolerant of rootless dpkg errors? (use || true)
- If docker_image is set: is it a public image that can be pulled?
- Are timeout values realistic? (Lean+Mathlib needs 600s+, simple tasks need 120s)

### 6. Timeout Analysis
- Agent timeout vs task complexity: is there enough time?
- Verifier timeout: can test.sh complete within the limit?
- Build timeout: can the Dockerfile build within the limit?

## Output Format

CHECKS:
- structural_completeness: PASS|FAIL [details]
- test_script: PASS|WARN|FAIL [details]
- verifier_robustness: PASS|WARN|FAIL [details]
- solution_test_alignment: PASS|FAIL [details]
- environment_compatibility: PASS|WARN|FAIL [details]
- timeout_analysis: PASS|WARN|FAIL [details]

CRITICAL_ISSUES:
- [Issues that would cause oracle to fail or produce wrong rewards]

WARNINGS:
- [Issues that could cause problems but aren't blocking]

FIXES:
- [Specific file edits needed, with before/after or exact content]
```

### Step 2: Collect and Synthesize Feedback

Wait for both agents to complete. Then:

1. Parse grades from the grader
2. Parse checks from the verifier
3. Create a unified assessment:

```
## Task Assessment: {task_name}

### Grades
| Metric | Score |
|--------|-------|
| Clarity | N/5 |
| Difficulty | easy/medium/hard |
| Verifier Coverage | N/5 |
| Solution Quality | N/5 |
| Environment Fitness | N/5 |
| Benchmark Value | N/5 |
| **Overall** | **N/5** |

### Verifier Status
| Check | Status |
|-------|--------|
| Structure | PASS/FAIL |
| Test Script | PASS/WARN/FAIL |
| Robustness | PASS/WARN/FAIL |
| Alignment | PASS/FAIL |
| Environment | PASS/WARN/FAIL |
| Timeouts | PASS/WARN/FAIL |

### Issues Found
[merged list from both agents]

### Recommended Fixes
[merged list from both agents]
```

Present this as a structured assessment for the coordinator or user.

### Step 3: Apply Fixes

Default behavior in the shared workflow:
- auto-fix critical issues
- auto-fix safe verifier/environment/task-alignment issues
- leave deeper benchmark-design changes as warnings if they would materially change the task shape

Do not pause for user approval in orchestrated mode unless the only available fix would significantly change the benchmark.

### Step 4: Re-evaluate (If Fixes Were Applied)

If fixes were applied, run one more iteration:
1. Spawn grader + verifier again (same prompts, updated file contents)
2. Show the updated assessment
3. Highlight what improved and what remains

### Step 5: Oracle Validation Handoff

Do not run oracle from this skill in the orchestrated pipeline.

After fixes are applied, report one of:
- `READY_FOR_ORACLE_2`
- `BLOCKED_ON_CRITICAL_FIXES`

---

## Iteration Limits

- **Max iterations**: 3 (grader+verifier → fix → re-evaluate)
- **Stop early if**: overall grade >= 4/5 AND all verifier checks PASS
- **Do not keep polishing forever**: once critical issues are gone, hand back to the coordinator

## Batch Mode

If the user points to a directory containing multiple tasks (e.g., `tasks/`), iterate over each task subdirectory and produce a summary table:

```
| Task | Difficulty | Overall | Oracle | Issues |
|------|-----------|---------|--------|--------|
| task-a | easy | 4.2/5 | PASS | 0 |
| task-b | hard | 2.8/5 | FAIL | 3 |
| task-c | medium | 3.5/5 | SKIP | 1 |
```

---

## Reference: What Makes a Good Harbor Task

- **Clarity**: One correct interpretation. No ambiguity about deliverables.
- **Verifier**: Tests the actual requirement, not a proxy. Rejects wrong answers.
- **Difficulty**: Matched to the `difficulty` field in task.toml. A task labeled "easy" that requires 30 steps is mislabeled.
- **Environment**: Minimal — only install what's needed. Timeouts should be 2x the expected solve time.
- **Solution**: Demonstrates the simplest correct approach. Oracle should always get reward=1.0.
- **Value**: Tests a real capability. Avoids testing memorization or trivia.

## Difficulty Ladder Requirement

This skill should help the pipeline produce three difficulty levels for the same underlying task family whenever feasible.

Preferred strategy:
1. Start from the initial grounded task.
2. Let the agent attempt it.
3. If the agent solves it, preserve that version and create a harder successor.
4. Repeat at most two additional times.

Fallback strategy:
1. If the agent fails the initial version, preserve that base version.
2. Create two easier instruction variants by adding hints or clarifications while keeping the same core verifier when possible.

Do not overwrite prior versions. Save each variant and each agent attempt so the pipeline does not waste data.

## Orchestrator Contract

Return a concise structured summary:

```text
REFINE_STATUS: READY_FOR_ORACLE_2|BLOCKED_ON_CRITICAL_FIXES
CRITICAL_ISSUES: <count>
SAFE_FIXES_APPLIED: <count>
DIFFICULTY_RECOMMENDATION: easy|medium|hard
VARIANT_PLAN: none|harder-successor|hinted-variants
NOTES: <one short line>
```
