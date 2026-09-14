#!/usr/bin/env python3
"""Compress one Harbor trial into a compact evidence digest.

A trial carries roughly 300 KB of raw evidence — trajectory.json, the terminal
pane capture, and pytest stdout. Handed that directly, an agent spends its run
writing extraction tooling instead of diagnosing, and often exhausts its context
before it builds anything.

This does the extraction only. It selects and truncates; it does not interpret.
The diagnosis stays with whoever reads the digest.

Usage: digest_trial.py <trial-dir> [-o OUT] [--step-chars N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# pytest emits the full diff for every failing assertion, which is where most of
# test-stdout.txt's bulk comes from. The summary lines and the assertion context
# carry the signal.
FAIL_LINE = re.compile(r"^(FAILED|ERROR|E\s+assert|E\s+\w*Error|assert\s)", re.M)
SUMMARY = re.compile(r"^=+ short test summary info =+$", re.M)


def read(path: Path, limit: int | None = None) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text if limit is None else text[:limit]


def verifier_section(trial: Path) -> tuple[str, bool]:
    """Return (markdown, has_failure_content).

    has_failure_content is False when nothing recognisable as a failure was
    extracted — no summary banner and no assertion lines. The last-40-lines
    fallback below still gets written for a human, but it is not counted as
    evidence, since it carries no located failure.
    """
    out = read(trial / "verifier" / "test-stdout.txt")
    if not out:
        return "_no verifier output_", False

    lines = out.splitlines()
    # Everything from the summary banner onward names the failures compactly.
    tail = []
    m = SUMMARY.search(out)
    if m:
        tail = out[m.start():].splitlines()

    # Plus the assertion lines themselves, wherever they occur, with a little
    # surrounding context so the reason is legible.
    hits: list[str] = []
    # Adjacent failures share context lines, so the same chunk is reached
    # repeatedly. Compare against chunks already emitted -- the old check
    # tested a list against a list of *strings*, so it never matched and
    # duplicates ate the budget below.
    seen: set[tuple[str, ...]] = set()
    for i, line in enumerate(lines):
        if FAIL_LINE.match(line.strip()) or FAIL_LINE.match(line):
            lo, hi = max(0, i - 2), min(len(lines), i + 3)
            chunk = tuple(ln[:400] for ln in lines[lo:hi])
            if chunk not in seen:
                seen.add(chunk)
                hits.extend(list(chunk) + ["  ---"])
        if len(hits) > 120:
            hits.append("  … (further assertion context truncated)")
            break

    parts = []
    if tail:
        parts.append("### Summary\n```\n" + "\n".join(tail[:40]) + "\n```")
    if hits:
        parts.append("### Failing assertions (with context)\n```\n" + "\n".join(hits) + "\n```")
    if parts:
        return "\n\n".join(parts), True
    return "```\n" + "\n".join(lines[-40:]) + "\n```", False


def trajectory_section(trial: Path, step_chars: int) -> tuple[str, str]:
    raw = read(trial / "agent" / "trajectory.json")
    if not raw:
        # Instruction is "" — not a sentinel string — so callers can test it for
        # truthiness. The doc renders its own "_not recovered_" placeholder.
        return "_no trajectory_", ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "_trajectory.json is not valid JSON_", ""

    steps = data.get("steps") or []
    # Step 1 is the harness handing the agent its instruction. That text is the
    # task as the agent actually saw it — frequently the thing that explains the
    # failure, and easy to miss if you only read the agent's own reasoning.
    # Prefer the first "user" step. mini-swe-agent puts a short system prompt
    # ("You are a helpful assistant...") in step 1 and the actual task in step 2,
    # so "first non-agent step" yields 62 characters of boilerplate and the
    # digest loses the instruction entirely. Fall back to any non-agent step for
    # harnesses that do not label roles this way.
    instruction = ""
    for s in steps:
        if s.get("source") == "user":
            instruction = str(s.get("message", ""))
            break
    if not instruction.strip():
        for s in steps:
            if s.get("source") != "agent":
                instruction = str(s.get("message", ""))
                break

    out = []
    for s in steps:
        src = s.get("source", "?")
        msg = str(s.get("message", "")).strip()
        if len(msg) > step_chars:
            head = msg[: step_chars // 2]
            tail = msg[-step_chars // 2 :]
            msg = f"{head}\n  …[{len(msg) - step_chars} chars omitted]…\n{tail}"
        out.append(f"--- step {s.get('step_id')} [{src}] ---\n{msg}")

    metrics = data.get("final_metrics") or {}
    header = f"steps={len(steps)} metrics={json.dumps(metrics)[:200]}"
    return header + "\n\n" + "\n\n".join(out), instruction


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trial_dir", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--step-chars", type=int, default=2000,
                    help="per-step message budget before truncation (default 2000)")
    args = ap.parse_args()

    trial: Path = args.trial_dir
    if not trial.is_dir():
        print(f"error: not a directory: {trial}", file=sys.stderr)
        return 2

    reward = read(trial / "verifier" / "reward.txt").strip() or "none"
    traj, instruction = trajectory_section(trial, args.step_chars)
    verifier, have_failures = verifier_section(trial)
    have_instruction = bool(instruction.strip())

    doc = f"""# Trial digest — {trial.name}

Reward: **{reward}**  (0 = the model failed this task)
Source: `{trial}`

This is an extracted digest, not an analysis. Raw files are still on disk at the
path above if you need to check something specific.

## The task the agent was given

```
{instruction[:6000] or "_not recovered_"}
```

## Why the verifier failed

{verifier}

## What the agent did

{traj}
"""

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(doc, encoding="utf-8")
        raw_total = sum(
            (trial / p).stat().st_size
            for p in ("agent/trajectory.json", "agent/terminus_2.pane",
                      "verifier/test-stdout.txt")
            if (trial / p).exists()
        )
        print(f"{args.out}  ({len(doc):,} chars, from {raw_total:,} bytes raw)")
    else:
        sys.stdout.write(doc)

    # The digest is always written — it is still the fastest way to see what was
    # and was not on disk. The exit code is what tells a caller whether spending
    # an agent session on it is worth anything.
    if not have_instruction and not have_failures:
        print(
            f"error: digest is unusable — no task instruction recovered from "
            f"{trial}/agent/trajectory.json (missing, unparseable, or no "
            f"non-agent step) AND no failing-assertion content extracted from "
            f"{trial}/verifier/test-stdout.txt. Wrote the digest anyway for "
            f"debugging, but there is no evidence in it to diagnose.",
            file=sys.stderr,
        )
        return 3
    if not have_instruction:
        print(f"warning: no task instruction recovered from {trial}/agent/"
              f"trajectory.json — digest has verifier evidence only.",
              file=sys.stderr)
    elif not have_failures:
        print(f"warning: no failing-assertion content extracted from {trial}/"
              f"verifier/test-stdout.txt — digest has the instruction and "
              f"trajectory only.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
