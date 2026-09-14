# task-factory

Agent skills and a runnable program for turning a source of hard problems
into Harbor tasks that are oracle-validated, audited for reward hacking, and
calibrated against a real agent. Built to generate STEM and coding
environments for RL post-training; the same loop produces benchmark tasks.

**Status: pre-release.** Skills are being generalised from an internal
deployment. Paths, model names, and the quickstart are not final.

## What is here

| Path | What it is |
|---|---|
| `auto.md` | The program. Hand it to a coding agent and it runs the factory loop |
| `skills/` | Agent skills the program calls, one directory each with a `SKILL.md` |
| `prompts/` | Recipes for RL-targeted tasks: mine a failed trial, perturb a solved task into a ladder, audit with a second model |
| `scripts/probe_verifier.py` | Negative-probe battery for a task verifier. No Docker, stdlib only |
| `scripts/digest_trial.py` | Compresses a Harbor trial into a ~20 KB evidence digest |
| `examples/stem-task/` | A finished math task: instruction, environment, verifier, reference solution |

## Skills

| Skill | Question it answers |
|---|---|
| `verifier-hardening` | Will this verifier reject wrong answers and accept every correct one? |
| `reward-hacking-audit` | Can an agent score 1 without doing the work? |
| `task-design-review` | Is the task contaminated, brute-forceable, ambiguous, or mis-graded? |
| `harbor-trajectory-analyser` | Why did each trial pass or fail? |
| `harbor-task-refine` | Structural cleanup of an existing task |

Skills follow the `SKILL.md` convention and load in Claude Code (`.claude/skills/`)
or any agent that reads a directory of Markdown skills.

Task authoring itself is Harbor's own skill and is not vendored here. Install
it, and any other Harbor skills you want (`harbor-cli`, `rewardkit`,
`harbor-exec`), from [harbor-framework/skills](https://github.com/harbor-framework/skills):

```bash
npx skills add https://github.com/harbor-framework/skills --skill harbor-task-creator
```

`skills-lock.json` records the upstream skills this program expects.

## Quickstart

```bash
uv tool install harbor                 # Harbor CLI
docker info                            # or another Harbor environment backend

# validate an example end to end
harbor run -p examples/stem-task                       # oracle
python scripts/probe_verifier.py examples/stem-task    # negative probes
harbor run -p examples/stem-task -a <agent> -m <model> -n 4   # calibrate
```

To run the factory, open `auto.md`, fill in the Setup block, and give the
file to your agent as its instructions.

## The loop

```
READ → SOURCE → PICK → GROUND → HARDEN → ORACLE → AUDIT
     → SMOKE → CALIBRATE → TRIAGE → REVIEW → LOG → PUBLISH → repeat
```

Three gates are never skipped: the oracle (the reference solution passes the
verifier), the hardening probes (wrong answers score 0), and the reward-hacking
audit (reward is evidence of work). Calibration measures difficulty; it is not
a dial the loop turns.

## License

Apache-2.0. See [LICENSE](LICENSE).
