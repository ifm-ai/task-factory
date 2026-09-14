#!/usr/bin/env python3
"""Run the mandatory negative-probe battery against a Harbor task's verifier.

`verifier-hardening` requires every task to prove, by running them, that a
missing answer, an empty answer, garbage, the input echoed back, and a
degenerate structure all score 0 — and that the reference solution scores 1.
Read alone, a verifier that compares `None == None` on an absent key looks
correct; only running it exposes that.

Every agent that has done this so far rebuilt the same harness from scratch:
copy tests/ somewhere, rewrite the absolute runtime paths, stage fixtures,
drive test.sh, read reward.txt, repeat six times. That is a large fraction of
a run spent on plumbing that is identical across tasks. This is that plumbing,
once.

On top of that battery it checks the defect that an audit of 27 generated
tasks found in seven of them — more than any other: the verifier's whole
ground truth is a fixed, finite set of inputs, so a candidate that recognises
those inputs and replays canned answers scores 1 without implementing the
capability the instruction demands. `visible-inputs` (static) asks whether the
graded fixtures are already in the agent's image; `memorised` (executed)
builds that memorising candidate and reports a violation if it scores 1.

No Docker, stdlib only. The task directory is never written to; everything
happens in a scratch tree that mimics the runtime layout (/app, /tests,
/logs/verifier). Probes that this tool cannot construct honestly are reported
SKIPPED with a reason — a skip is information, a wrong guess is not.

Exit status is 0 only when every MUST holds, so this is usable as a gate.

Usage: probe_verifier.py <task-dir> [--keep] [-v]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Runtime mount points, rewritten to point into the scratch tree. The negative
# lookahead keeps "/application" and "/apps" from being mangled.
RUNTIME_DIRS = ("app", "tests", "logs", "solution")


def path_re(extra_dirs: tuple[str, ...] = ()) -> re.Pattern[str]:
    """Rewrite pattern for the mount points, plus anything the image adds.

    A task may COPY fixtures outside /app -- /opt/acceptance, /srv/postoffice.
    Those get staged into the scratch tree, but if the pattern does not know
    about them the verifier keeps its absolute path, reads the host's (absent)
    /opt/..., and fails for a reason that has nothing to do with the task.
    """
    dirs = RUNTIME_DIRS + tuple(d for d in extra_dirs if d not in RUNTIME_DIRS)
    return re.compile(r"/(%s)(?![A-Za-z0-9_.-])" % "|".join(map(re.escape, dirs)))


PATH_RE = path_re()

# Task images pin an absolute interpreter to defend against PATH shims. That
# path rarely exists on the host running this tool, so it is redirected to the
# interpreter we are already using.
PY_ABS_RE = re.compile(r"/usr/(?:local/)?bin/python[0-9.]*")

# Emitted by test.sh's fail_closed and by a verifier's demotion preflight when
# the sandbox defences cannot engage. Offline that is expected, not a defect.
HARDENING_REFUSAL_RE = re.compile(
    r"HARDENING FAILURE|defences cannot engage|NOT demoted", re.I)

# Rewriting is confined to code. Fixture bytes must survive untouched: the
# csv-surgical-purge verifier sha256-checks every file under tests/cases/, and
# a single substituted byte there fails the manifest, not the probe.
CODE_SUFFIXES = {".py", ".sh", ".bash", ".pl", ".rb", ".js"}
SCRIPT_SUFFIXES = {".py", ".sh", ".bash", ".pl", ".rb", ".js"}
EXEC_MARKERS = ("subprocess", "sys.executable", "os.system", "popen",
                "check_output", "os.exec")

REWARD_REL = "logs/verifier/reward.txt"

# Probe payloads for the two answer shapes we handle. Anything else degrades to
# SKIPPED rather than guessing.
GARBAGE_DATA = b"\xff\xfe not a valid answer -- garbage \x00 !!!\n"
WHITESPACE_DATA = b"   \n\n \t\n"


class Probe:
    """One probe and its outcome. `reward` is None when it could not be run."""

    def __init__(self, name: str, expect: str, note: str = ""):
        self.name = name
        self.expect = expect          # "1" or "0"
        self.note = note              # what payload was used, or why skipped
        self.reward: str | None = None
        self.skipped_reason: str | None = None
        self.output = ""

    @property
    def status(self) -> str:
        if self.skipped_reason:
            return "SKIPPED"
        return "PASS" if self.reward == self.expect else "FAIL"


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    """Content map of a tree, used to spot what the reference solution wrote."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[str(p.relative_to(root))] = sha(p)
    return out


# --------------------------------------------------------------------------
# staging


def parse_dockerfile(dockerfile: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """Extract (src, dst) COPY pairs and note anything we cannot emulate.

    Only WORKDIR and COPY are honoured. RUN steps that generate fixtures at
    build time have no equivalent here, so they are surfaced as caveats rather
    than silently producing an incomplete /app.
    """
    copies: list[tuple[str, str]] = []
    caveats: list[str] = []
    workdir = "/"
    text = dockerfile.read_text(encoding="utf-8", errors="replace")
    # Join escaped continuation lines so multi-line COPY/RUN read as one.
    text = re.sub(r"\\\s*\n", " ", text)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        verb, _, rest = line.partition(" ")
        verb = verb.upper()
        if verb == "WORKDIR":
            workdir = rest.strip()
        elif verb == "COPY" or verb == "ADD":
            parts = [p for p in shlex.split(rest) if not p.startswith("--")]
            if len(parts) < 2:
                caveats.append(f"unparsed {verb}: {line}")
                continue
            dst = parts[-1]
            if not dst.startswith("/"):
                dst = os.path.join(workdir, dst)
            for src in parts[:-1]:
                copies.append((src, dst))
        elif verb == "RUN":
            caveats.append(f"RUN step not emulated: {line[:80]}")
    return copies, caveats


def stage_app(task: Path, scratch: Path, extra: set[str] | None = None) -> list[str]:
    """Materialise the agent-visible filesystem the image would have provided."""
    env_dir = task / "environment"
    app = scratch / "app"
    app.mkdir(parents=True, exist_ok=True)
    caveats: list[str] = []
    dockerfile = env_dir / "Dockerfile"

    copies: list[tuple[str, str]] = []
    if dockerfile.is_file():
        copies, caveats = parse_dockerfile(dockerfile)

    if not copies:
        # No parseable COPY (or no Dockerfile): the whole environment dir is
        # the best available guess at what /app holds.
        if env_dir.is_dir():
            for child in env_dir.iterdir():
                if child.name == "Dockerfile":
                    continue
                target = app / child.name
                if child.is_dir():
                    shutil.copytree(child, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, target)
            caveats.append("no COPY directives parsed; copied environment/* into /app")
        return caveats

    for src, dst in copies:
        src_path = env_dir / src.rstrip("/")
        dst_path = scratch / dst.lstrip("/")
        top = dst.lstrip("/").split("/", 1)[0]
        if extra is not None and top and top not in RUNTIME_DIRS:
            extra.add(top)
        if not src_path.exists():
            caveats.append(f"COPY source missing in environment/: {src}")
            continue
        if src_path.is_dir():
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
        else:
            if dst.endswith("/") or dst_path.is_dir():
                dst_path.mkdir(parents=True, exist_ok=True)
                dst_path = dst_path / src_path.name
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
    return caveats


def rewrite_file(path: Path, scratch: Path, notes: list[str],
                 pattern: re.Pattern[str] | None = None) -> None:
    """Point one code file's absolute runtime paths at the scratch tree."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        notes.append(f"not rewritten (undecodable): {path.name}")
        return
    new = (pattern or PATH_RE).sub(lambda m: f"{scratch}/{m.group(1)}", text)

    def swap_interp(m: re.Match) -> str:
        return m.group(0) if os.path.exists(m.group(0)) else sys.executable

    new2 = PY_ABS_RE.sub(swap_interp, new)
    if new2 != new:
        notes.append(f"{path.name}: absolute interpreter redirected to {sys.executable}")
    if new2 != text:
        path.write_text(new2, encoding="utf-8")


def stage_code(task: Path, scratch: Path, notes: list[str],
               pattern: re.Pattern[str] | None = None) -> None:
    """Copy tests/ and solution/ in, then rewrite only the code inside them."""
    for name in ("tests", "solution"):
        src = task / name
        if src.is_dir():
            shutil.copytree(src, scratch / name, dirs_exist_ok=True)

    tests = scratch / "tests"
    if tests.is_dir():
        # Top level only — tests/cases/ and friends are fixture data.
        for p in sorted(tests.iterdir()):
            if p.is_file() and p.suffix in CODE_SUFFIXES:
                rewrite_file(p, scratch, notes, pattern)
    sol = scratch / "solution"
    if sol.is_dir():
        # solve.sh often delegates to a solve.py holding its own /app defaults,
        # so the whole solution tree gets rewritten, not just the entry point.
        for p in sorted(sol.rglob("*")):
            if p.is_file() and p.suffix in CODE_SUFFIXES:
                rewrite_file(p, scratch, notes, pattern)


# --------------------------------------------------------------------------
# execution


def run(cmd: list[str], cwd: Path, timeout: float,
        extra_env: dict[str, str] | None = None) -> tuple[int, str]:
    env = dict(os.environ)
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), env=env, timeout=timeout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, f"[timed out after {timeout:g}s]"
    except OSError as exc:
        return 127, f"[could not execute: {exc}]"
    return proc.returncode, proc.stdout.decode(errors="replace")


def read_reward(scratch: Path) -> str | None:
    p = scratch / REWARD_REL
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8", errors="replace").strip() or None


def reset_app(scratch: Path, pristine: Path) -> None:
    app = scratch / "app"
    shutil.rmtree(app, ignore_errors=True)
    shutil.copytree(pristine, app)


def reset_logs(scratch: Path) -> None:
    # A stale reward from the previous probe would masquerade as this one's.
    shutil.rmtree(scratch / "logs", ignore_errors=True)
    (scratch / "logs" / "verifier").mkdir(parents=True)


def run_verifier(scratch: Path, timeout: float) -> tuple[str | None, str]:
    test_sh = scratch / "tests" / "test.sh"
    # A hardened test.sh fails closed when it is not root, because a reward
    # computed with the sandbox defences inert is not trustworthy. This probe
    # opts in explicitly: it certifies verifier LOGIC, and says so.
    rc, out = run(["bash", str(test_sh)], scratch / "tests", timeout,
                  extra_env={"HARBOR_OFFLINE_PROBE": "1"})
    # test.sh redirects the verifier into verify.log, so its diagnostics -- the
    # reason a run failed -- never reach stdout. Fold it in; without it a
    # hardening refusal is indistinguishable from a wrong answer.
    vlog = scratch / "logs" / "verifier" / "verify.log"
    if vlog.is_file():
        tail = vlog.read_text(errors="replace").strip()
        if tail:
            out += "\n[verify.log]\n" + tail[-4000:]
    reward = read_reward(scratch)
    if reward is None:
        out += f"\n[no reward.txt written; test.sh exited {rc}]"
    return reward, out


# --------------------------------------------------------------------------
# answer-shape detection


def choose_artifact(new: list[str], verifier_src: str) -> tuple[str | None, str]:
    """Pick the single file the reference solution produced as *the* answer."""
    if not new:
        return None, "reference solution created/changed no file under /app"
    if len(new) == 1:
        return new[0], ""
    # More than one: the verifier naming one of them settles it.
    named = [r for r in new if f"/app/{r}" in verifier_src]
    if len(named) == 1:
        return named[0], ""
    return None, ("reference solution touched %d files under /app (%s) and the "
                  "verifier does not single one out" % (len(new), ", ".join(new[:5])))


def payloads(artifact: str, is_script: bool, verifier_src: str) -> dict[str, tuple[bytes, str]]:
    """Probe payloads, chosen for the answer shape. Each is (bytes, description)."""
    suffix = Path(artifact).suffix
    if is_script:
        if suffix in (".sh", ".bash"):
            garbage = b"if then fi ((((\n"
            noop = b"#!/bin/sh\nexit 0\n"
            trunc = b'#!/bin/sh\nfor f in "$@"; do : > "$f"; done\nexit 0\n'
        else:
            garbage = b"def broken(:\n"
            noop = b"import sys\nsys.exit(0)\n"
            trunc = (b"import sys\n"
                     b"for p in sys.argv[1:]:\n"
                     b"    open(p, 'wb').write(b'')\n")
        return {
            "empty": (b"", "zero-byte script"),
            "garbage": (garbage, "script with a syntax error"),
            "unchanged": (noop, "no-op script: exits 0, leaves its input untouched"),
            "truncated": (trunc, "script that truncates every path argument to zero bytes"),
        }

    if suffix == ".json" or "json" in verifier_src:
        degenerate = (b"{}\n", "empty JSON object")
    else:
        degenerate = (WHITESPACE_DATA, "whitespace only")
    return {
        "empty": (b"", "zero-byte file"),
        "garbage": (GARBAGE_DATA, "non-UTF-8 junk"),
        "unchanged": (b"", "input echoed back"),   # bytes filled in by caller
        "truncated": degenerate,
    }


def pick_input(pristine: Path, artifact: str | None) -> tuple[Path | None, str]:
    """The task input to echo back for the `unchanged` probe."""
    cands = []
    for p in sorted(pristine.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(pristine))
        if rel == artifact:
            continue
        # Worked-example expected outputs are *correct* answers for their own
        # input; echoing one back could legitimately score 1 and would read as
        # a spurious FAIL.
        if "expected" in p.name:
            continue
        cands.append(p)
    if not cands:
        return None, "no input fixture staged under /app to echo back"
    cands.sort(key=lambda p: (-p.stat().st_size, str(p)))
    return cands[0], ""


# --------------------------------------------------------------------------
# generalisation: is the graded oracle a fixed, finite, replayable input set?

# The largest exploitable class in the task audits is not a broken comparison.
# It is a verifier whose entire ground truth is a finite list of inputs. A
# candidate that recognises those inputs and replays canned answers scores 1
# without implementing anything, and for RL that trains memorisation while the
# reward curve looks healthy. Two probes:
#
#   visible-inputs  static. Harbor uploads tests/ only after the agent stops,
#                   while environment/ is in the container from the first
#                   second, so a graded fixture whose bytes also sit in the
#                   image is the hole. Compared by content, not by name.
#   memorised       executed. Record what the verifier asks the reference
#                   deliverable, install a candidate that answers exactly
#                   those recordings and a sentinel for everything else, and
#                   score it. Reward 1 is conclusive by construction: any
#                   graded input outside the recorded set would have hit the
#                   sentinel and failed.

MEMO_SENTINEL = b"probe-verifier: input outside the memorised table\n"

# The verifier compiles the deliverable rather than executing it directly.
COMPILER_RE = re.compile(r"\b(?:gcc|clang|cc|g\+\+)\b")

# Ceiling on what gets baked into a synthesised replay table. A graded set too
# large to embed is reported SKIPPED rather than truncated into a probe that
# would fail for the wrong reason.
MAX_EMBED_BYTES = 512 * 1024

# Names that mean "this fixture is the answer", not "this fixture is input".
# A visible answer is a leak whatever the deliverable's shape.
ANSWER_NAME_RE = re.compile(r"expect|answer|golden|truth|solution|reference",
                            re.I)

# A verifier that builds its own inputs at scoring time is not confined to the
# fixtures on disk, so a visible fixture is not the whole graded set.
GENERATOR_RE = re.compile(r"\brandom\b|\bsecrets\b|urandom|\bRandom\(")

KEYIFY = """
def keyify(args):
    \"\"\"An argument that is an absolute path to a file is keyed by that
    file's content, not by its path: verifiers routinely stage the same
    fixture at a fresh temporary path on every run, and a path-keyed table
    would miss a graded input that is in fact identical every time. Relative
    arguments are left alone — they are ordinary values, and a bare "2" can
    collide with an unrelated file in whatever directory the verifier runs
    from.\"\"\"
    out = []
    for a in args:
        try:
            if a.startswith("/") and os.path.isfile(a):
                with open(a, "rb") as fh:
                    out.append("sha256:" + hashlib.sha256(fh.read()).hexdigest())
                continue
        except OSError:
            pass
        out.append(a)
    return out
"""

RECORDER_PY = r'''#!/usr/bin/env python3
"""Recording shim. Delegates every invocation to the reference deliverable,
so the verifier sees the reference's own behaviour, and logs what it was
asked and what it returned."""
import base64
import hashlib
import json
import os
import subprocess
import sys

__KEYIFY__

mode, ref, record = sys.argv[1], sys.argv[2], sys.argv[3]
args = sys.argv[4:]
try:
    data = sys.stdin.buffer.read()
except OSError:
    data = b""
cmd = [sys.executable, ref] if mode == "python" else ["bash", ref]
proc = subprocess.run(cmd + args, input=data, capture_output=True)
with open(record, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "argv": args,
        "key": keyify(args),
        "stdin": base64.b64encode(data).decode(),
        "stdout": base64.b64encode(proc.stdout).decode(),
        "rc": proc.returncode,
    }) + "\n")
sys.stdout.buffer.write(proc.stdout)
sys.stdout.buffer.flush()
sys.stderr.buffer.write(proc.stderr)
sys.exit(proc.returncode)
'''

REPLAY_PY = '''#!/usr/bin/env python3
"""Synthesised memorising candidate. It implements nothing: it looks the
invocation up in a table of what the reference answered for the inputs the
verifier actually asked about, and emits a sentinel for anything else."""
import base64
import hashlib
import json
import os
import sys

__KEYIFY__

TABLE = {table}
SENTINEL = {sentinel!r}

try:
    stdin = sys.stdin.buffer.read()
except OSError:
    stdin = b""
hit = TABLE.get(json.dumps([keyify(sys.argv[1:]),
                            base64.b64encode(stdin).decode()]))
if hit is None:
    sys.stdout.buffer.write(SENTINEL)
    sys.exit(0)
sys.stdout.buffer.write(base64.b64decode(hit[0]))
sys.exit(hit[1])
'''

# The C deliverable is compiled by the verifier, so the recorder cannot
# delegate to the reference the way a script shim does — running another
# program from C is exactly what such verifiers tend to ban. It records only,
# and the expected outputs are recomputed afterwards by compiling the
# reference on this host. That means the recording pass scores 0 and is not
# self-certifying; see the SKIPPED path in memorise_probe().
RECORDER_C = r'''/* probe-verifier recording stub: captures argv and stdin, answers nothing. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    char path[] = "%(recdir)s/rec-XXXXXX";
    int fd = mkstemp(path);
    if (fd < 0) {
        return 1;
    }
    FILE *f = fdopen(fd, "wb");
    if (!f) {
        return 1;
    }
    fprintf(f, "PVREC1\n%%d\n", argc - 1);
    for (int i = 1; i < argc; i++) {
        fprintf(f, "%%zu\n%%s", strlen(argv[i]), argv[i]);
    }
    fputs("STDIN\n", f);
    int c;
    while ((c = getchar()) != EOF) {
        fputc(c, f);
    }
    fclose(f);
    return 0;
}
'''

REPLAY_C_HEAD = r'''/* Synthesised memorising candidate. It implements nothing: it compares stdin
   against the inputs the verifier graded on and replays the reference's
   answers, emitting a sentinel for anything else. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

'''

REPLAY_C_MAIN = r'''
struct entry {
    const unsigned char *in;
    size_t inlen;
    const unsigned char *out;
    size_t outlen;
};

static const struct entry TABLE[] = {
%(rows)s};

static const unsigned char SENTINEL[] = {%(sentinel)s};

int main(void)
{
    size_t cap = 1 << 16, len = 0;
    unsigned char *buf = malloc(cap);
    int c;

    if (!buf) {
        return 1;
    }
    while ((c = getchar()) != EOF) {
        if (len == cap) {
            cap *= 2;
            buf = realloc(buf, cap);
            if (!buf) {
                return 1;
            }
        }
        buf[len++] = (unsigned char)c;
    }
    for (size_t i = 0; i < sizeof TABLE / sizeof TABLE[0]; i++) {
        if (TABLE[i].inlen == len && memcmp(TABLE[i].in, buf, len) == 0) {
            fwrite(TABLE[i].out, 1, TABLE[i].outlen, stdout);
            return 0;
        }
    }
    fwrite(SENTINEL, 1, sizeof SENTINEL, stdout);
    return 0;
}
'''


def deliverable_shape(artifact: str, verifier_src: str) -> tuple[str | None, str]:
    """Which recorder/replayer pair, if any, fits this deliverable."""
    suffix = Path(artifact).suffix
    executed = any(m in verifier_src for m in EXEC_MARKERS)
    if suffix == ".py" and executed:
        return "python", ""
    if suffix in (".sh", ".bash") and executed:
        return "shell", ""
    if suffix == ".c" and COMPILER_RE.search(verifier_src):
        return "c-source", ""
    if suffix in SCRIPT_SUFFIXES or suffix == ".c":
        # e.g. a module the verifier imports and calls in-process, which this
        # tool has no way to interpose on.
        return None, (
            f"{artifact} is a program, but the verifier does not run it as a "
            "subprocess this tool can record; recording covers argv/stdin "
            "subprocesses and compiled filters only")
    if executed:
        return None, (
            f"the verifier runs subprocesses, but {artifact} has no recognised "
            f"source suffix ({suffix or 'none'}) to synthesise a recorder for")
    return None, (
        f"{artifact} (suffix {suffix or 'none'}) is a data artifact, not a "
        "program graded on a set of inputs, so replaying answers for those "
        "inputs is not defined")


def c_bytes(data: bytes) -> str:
    """A C initialiser list. Empty arrays are illegal, so keep one dead byte."""
    if not data:
        return "0"
    return ", ".join(f"0x{b:02x}" for b in data)


def parse_c_record(blob: bytes) -> tuple[list[str], bytes] | None:
    """Undo RECORDER_C's framing: argv strings, then stdin to EOF."""
    head = b"PVREC1\n"
    if not blob.startswith(head):
        return None
    rest = blob[len(head):]
    count, _, rest = rest.partition(b"\n")
    try:
        n = int(count)
    except ValueError:
        return None
    args = []
    for _ in range(n):
        size, _, rest = rest.partition(b"\n")
        try:
            k = int(size)
        except ValueError:
            return None
        args.append(rest[:k].decode("utf-8", errors="replace"))
        rest = rest[k:]
    if not rest.startswith(b"STDIN\n"):
        return None
    return args, rest[len(b"STDIN\n"):]


def visible_inputs_probe(task: Path, pristine: Path, artifact: str | None,
                         ref_blob: bytes | None, shape: str | None,
                         verifier_src: str) -> Probe:
    """Are the bytes the verifier grades on already in the agent's image?

    Content, never filename: a fixture copied under a different name is the
    same leak. The check is deliberately conservative, because sharing bytes
    between environment/ and tests/ has a legitimate form — pinning a copy of
    the visible instance so an agent cannot edit the input out from under the
    verifier. It reports a leak only when the shared fixture really is the
    whole oracle: a program deliverable (a general capability was promised),
    no held-out fixture in tests/, and no sign of the verifier generating
    inputs of its own. Everything else it reports as a note.
    """
    pr = Probe("visible-inputs", "clean")
    visible: dict[str, list[str]] = {}
    for p in sorted(pristine.rglob("*")):
        if p.is_file() and not p.is_symlink():
            visible.setdefault(sha(p), []).append(str(p.relative_to(pristine)))

    tests = task / "tests"
    if not tests.is_dir():
        pr.skipped_reason = "no tests/ directory to compare against"
        return pr
    # Fixtures the agent cannot see mean the graded set is not the visible
    # one, whatever else is shared.
    held_out = [p for p in sorted(tests.rglob("*"))
                if p.is_file() and not p.is_symlink()
                and p.suffix not in CODE_SUFFIXES and p.name != "test.sh"
                and sha(p) not in visible]
    generates = bool(GENERATOR_RE.search(verifier_src))

    leaks: list[str] = []
    notes: list[str] = []
    for p in sorted(tests.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        digest = sha(p)
        if digest not in visible:
            continue
        rel = f"tests/{p.relative_to(tests)}"
        seen = f"/app/{visible[digest][0]}"
        if p.suffix in CODE_SUFFIXES:
            # A shared implementation is the point of some tasks (speed this
            # up, port this); code that matches is not a leaked oracle.
            notes.append(f"{rel} == {seen} (code, shared on purpose)")
        elif ANSWER_NAME_RE.search(p.name):
            leaks.append(f"{rel} (an expected-answer fixture) == {seen}")
        elif shape is None:
            notes.append(f"{rel} == {seen} (the graded instance, which a data "
                         "deliverable cannot be solved without)")
        elif held_out:
            notes.append(f"{rel} == {seen}, but {len(held_out)} fixture(s) "
                         "under tests/ are not in the image, so the graded set "
                         "is not the visible one")
        elif generates:
            notes.append(f"{rel} == {seen}, but the verifier builds inputs at "
                         "scoring time, so the graded set is not the visible "
                         "one")
        else:
            leaks.append(f"{rel} (a graded fixture) == {seen}")

    if ref_blob is not None and sha_bytes(ref_blob) in visible:
        where = visible[sha_bytes(ref_blob)][0]
        leaks.append(f"the reference answer {artifact} == /app/{where}, which "
                     "the agent is given")

    pr.reward = "clean" if not leaks else f"{len(leaks)} leak"
    pr.note = "; ".join(leaks) if leaks else (
        "; ".join(notes) if notes else
        "no tests/ fixture shares bytes with the agent's image")
    return pr


def memorise_probe(scratch: Path, pristine: Path, artifact: str,
                   ref_blob: bytes, shape: str, verifier_timeout: float,
                   verbose: bool) -> Probe:
    """Score a candidate that only replays the graded inputs' answers."""
    pr = Probe("memorised", "0")
    memo = scratch / "_memo"
    memo.mkdir(parents=True, exist_ok=True)
    ref = memo / ("reference" + Path(artifact).suffix)
    ref.write_bytes(ref_blob)
    os.chmod(ref, 0o755)
    target = scratch / "app" / artifact

    # ---- record: what does the verifier ask the deliverable?
    calls: list[tuple[list[str], bytes, bytes, int]] = []
    certified = False
    if shape in ("python", "shell"):
        recorder = memo / "recorder.py"
        recorder.write_text(RECORDER_PY.replace("__KEYIFY__", KEYIFY),
                            encoding="utf-8")
        log = memo / "calls.jsonl"
        exe = sys.executable
        if shape == "python":
            shim = ("#!/usr/bin/env python3\nimport os, sys\n"
                    "os.execv(%r, [%r, %r, 'python', %r, %r] + sys.argv[1:])\n"
                    % (exe, exe, str(recorder), str(ref), str(log)))
        else:
            shim = ("#!/bin/bash\nexec %s %s shell %s %s \"$@\"\n" % (
                shlex.quote(exe), shlex.quote(str(recorder)),
                shlex.quote(str(ref)), shlex.quote(str(log))))
        reset_app(scratch, pristine)
        reset_logs(scratch)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(shim, encoding="utf-8")
        os.chmod(target, 0o755)
        rec_reward, rec_out = run_verifier(scratch, verifier_timeout)
        # A shim that delegates is transparent, so a recording pass that still
        # scores 1 proves the verifier ran to completion: every input it
        # grades on is in the log.
        certified = rec_reward == "1"
        pr.output += f"[recording pass reward {rec_reward}]\n{rec_out}\n"
        if log.is_file():
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                calls.append((rec.get("key", rec["argv"]),
                              base64.b64decode(rec["stdin"]),
                              base64.b64decode(rec["stdout"]),
                              int(rec["rc"])))
    else:  # c-source
        gcc = shutil.which("gcc")
        if not gcc:
            pr.skipped_reason = "no gcc on this host to compile the reference"
            return pr
        recdir = memo / "crec"
        recdir.mkdir()
        reset_app(scratch, pristine)
        reset_logs(scratch)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(RECORDER_C % {"recdir": recdir}, encoding="utf-8")
        rec_reward, rec_out = run_verifier(scratch, verifier_timeout)
        pr.output += f"[recording pass reward {rec_reward}]\n{rec_out}\n"
        inputs = []
        for p in sorted(recdir.iterdir()):
            parsed = parse_c_record(p.read_bytes())
            if parsed is None:
                continue
            args, data = parsed
            if args:
                pr.skipped_reason = ("the compiled deliverable is invoked with "
                                     "arguments; replay synthesis here covers "
                                     "stdin-only filters")
                return pr
            if data not in [d for _, d in inputs]:
                inputs.append((args, data))
        refbin = memo / "reference.bin"
        rc, out = run([gcc, "-O2", "-o", str(refbin), str(ref)], memo, 180)
        if rc != 0:
            pr.skipped_reason = f"reference source does not compile here: {out.strip()[:120]}"
            return pr
        for args, data in inputs:
            proc = subprocess.run([str(refbin)], input=data,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, timeout=60)
            calls.append((args, data, proc.stdout, proc.returncode))

    if not calls:
        pr.skipped_reason = ("nothing recorded: the verifier never executed the "
                             "deliverable in a way this shim could observe")
        return pr
    if all(not stdout for _, _, stdout, _ in calls):
        pr.skipped_reason = (
            f"the deliverable wrote no stdout across {len(calls)} graded "
            "invocation(s): its answer is a side effect (files), which replay "
            "synthesis does not reproduce")
        return pr
    total = sum(len(i) + len(o) for _, i, o, _ in calls)
    if total > MAX_EMBED_BYTES:
        pr.skipped_reason = (f"graded inputs total {total} bytes, over the "
                             f"{MAX_EMBED_BYTES}-byte embedding ceiling")
        return pr

    # ---- replay: answer exactly those recordings, nothing else.
    novel_stdin = b"probe-verifier-unseen-input\n"
    if shape == "c-source":
        arrays, rows = [], []
        for i, (_, data, out, _rc) in enumerate(calls):
            arrays.append("static const unsigned char in%d[] = {%s};"
                          % (i, c_bytes(data)))
            arrays.append("static const unsigned char out%d[] = {%s};"
                          % (i, c_bytes(out)))
            rows.append("    {in%d, %d, out%d, %d},\n" % (i, len(data), i, len(out)))
        source = (REPLAY_C_HEAD + "\n".join(arrays) + "\n"
                  + REPLAY_C_MAIN % {"rows": "".join(rows),
                                     "sentinel": c_bytes(MEMO_SENTINEL)})
        replay_src = memo / "replay.c"
        replay_src.write_text(source, encoding="utf-8")
        replay_bin = memo / "replay.bin"
        rc, out = run([gcc, "-O2", "-o", str(replay_bin), str(replay_src)],
                      memo, 180)
        if rc != 0:
            pr.skipped_reason = f"synthesised candidate does not compile: {out.strip()[:120]}"
            return pr
        control = subprocess.run([str(replay_bin)], input=novel_stdin,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, timeout=60).stdout
        payload = source.encode("utf-8")
    else:
        table = {json.dumps([argv, base64.b64encode(data).decode()]):
                 [base64.b64encode(out).decode(), rc]
                 for argv, data, out, rc in calls}
        source = REPLAY_PY.format(table=repr(table),
                                  sentinel=MEMO_SENTINEL).replace(
                                      "__KEYIFY__", KEYIFY)
        replay_src = memo / "replay.py"
        replay_src.write_text(source, encoding="utf-8")
        control = subprocess.run(
            [sys.executable, str(replay_src), "--probe-verifier-unseen"],
            input=novel_stdin, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=60).stdout
        if shape == "python":
            payload = source.encode("utf-8")
        else:
            # A .sh deliverable has to stay a shell script; the table lives
            # beside it under /app, where an agent could equally have put it.
            helper = scratch / "app" / "_memorised_table.py"
            helper.write_text(source, encoding="utf-8")
            payload = ("#!/bin/bash\nexec %s %s \"$@\"\n" % (
                shlex.quote(sys.executable),
                shlex.quote(str(helper)))).encode("utf-8")

    if control != MEMO_SENTINEL:
        pr.skipped_reason = ("the synthesised candidate did not answer a novel "
                             "input with its sentinel, so it is not a clean "
                             "memoriser and proves nothing")
        return pr

    reset_app(scratch, pristine)
    reset_logs(scratch)
    if shape == "shell":
        (scratch / "app" / "_memorised_table.py").write_text(source,
                                                            encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    os.chmod(target, 0o755)
    reward, out = run_verifier(scratch, verifier_timeout)
    pr.output += out
    pr.note = (f"{len(calls)} graded invocation(s) recorded and replayed; "
               f"every other input answers {MEMO_SENTINEL.decode().strip()!r}")
    if verbose:
        print(f"  memorised table: {len(calls)} entries, {total} bytes, "
              f"capture {'certified' if certified else 'not certified'}")

    if reward == "1":
        # Conclusive: an uncaptured graded input would have hit the sentinel.
        pr.reward = "1"
        return pr
    pr.reward = reward or "0"

    # A replay that scored 0 only means "not memorisable" if the recording
    # channel could see the graded input in the first place. When every
    # invocation carries the same argv and stdin, the input reached the
    # deliverable some other way — files staged around it — and a table keyed
    # on argv/stdin was never able to represent it. Saying PASS there would be
    # the silently-inert check this tool exists to avoid.
    keys = [(tuple(argv), data) for argv, data, _, _ in calls]
    if len(set(keys)) < len(keys) or all(not a and not d for a, d in keys):
        pr.skipped_reason = (
            f"the graded input does not arrive through argv/stdin: "
            f"{len(calls)} invocation(s) collapse to {len(set(keys))} distinct "
            "argv/stdin key(s), so a replay keyed on them can neither "
            "reproduce nor rule out memorisation")
        return pr
    if certified:
        return pr
    why = ("the recording stub for a compiled deliverable cannot delegate to "
           "the reference, so it scored 0 and a verifier that stops at its "
           "first failure would have been observed only partially"
           if shape == "c-source" else
           "the recording pass did not itself score 1, so the verifier may "
           "have stopped early")
    pr.skipped_reason = (
        f"inconclusive: the replay scored {pr.reward}, but {why}; the "
        f"{len(calls)} captured input(s) are not certified to be the whole "
        "graded set")
    return pr


# --------------------------------------------------------------------------


def read_timeouts(task: Path) -> tuple[float, float]:
    """Agent and verifier timeouts from task.toml, capped so a gate cannot hang."""
    agent, verifier = 300.0, 300.0
    toml = task / "task.toml"
    if toml.is_file():
        text = toml.read_text(encoding="utf-8", errors="replace")
        found = {}
        for section in ("agent", "verifier"):
            m = re.search(r"\[%s\][^\[]*?timeout_sec\s*=\s*([0-9.]+)" % section,
                          text, re.S)
            if m:
                found[section] = float(m.group(1))
        agent = found.get("agent", agent)
        verifier = found.get("verifier", verifier)
    return min(agent, 900.0), min(verifier, 900.0)


def generalisation_probes(task: Path, scratch: Path, pristine: Path,
                          artifact: str | None, ref_blob: bytes | None,
                          artifact_why: str, verifier_src: str,
                          verifier_timeout: float,
                          verbose: bool) -> list[Probe]:
    """The two checks on whether the graded oracle is a finite input set."""
    shape: str | None = None
    shape_why = artifact_why or "answer artifact not identified"
    if artifact:
        shape, shape_why = deliverable_shape(artifact, verifier_src)
    if verbose:
        print(f"  deliverable:     {shape or 'not a recordable program'}")

    out = [visible_inputs_probe(task, pristine, artifact, ref_blob, shape,
                                verifier_src)]

    if artifact is None or ref_blob is None:
        mem = Probe("memorised", "0")
        mem.skipped_reason = (
            shape_why if artifact is None else
            f"the reference solution left no readable {artifact} to record")
        out.append(mem)
    elif shape is None:
        mem = Probe("memorised", "0")
        mem.skipped_reason = shape_why
        out.append(mem)
    else:
        out.append(memorise_probe(scratch, pristine, artifact, ref_blob,
                                  shape, verifier_timeout, verbose))
    return out


def probe_all(task: Path, scratch: Path, verbose: bool) -> list[Probe]:
    notes: list[str] = []
    # Stage first so the rewrite pattern can learn any mount points the image
    # adds outside /app; rewriting before staging would miss them.
    extra_dirs: set[str] = set()
    caveats = stage_app(task, scratch, extra_dirs)
    if extra_dirs:
        notes.append("image dirs outside /app rewritten: "
                     + ", ".join("/" + d for d in sorted(extra_dirs)))
    stage_code(task, scratch, notes, path_re(tuple(sorted(extra_dirs))))

    pristine = scratch / "_pristine_app"
    shutil.copytree(scratch / "app", pristine)

    verifier_src = ""
    for p in sorted((scratch / "tests").glob("*")):
        if p.is_file() and p.suffix in CODE_SUFFIXES:
            verifier_src += (task / "tests" / p.name).read_text(
                encoding="utf-8", errors="replace")

    agent_timeout, verifier_timeout = read_timeouts(task)
    if verbose:
        print(f"scratch:   {scratch}")
        for c in caveats:
            print(f"  caveat:  {c}")
        for n in notes:
            print(f"  rewrite: {n}")
        print(f"  timeouts: agent {agent_timeout:g}s, verifier {verifier_timeout:g}s")

    probes: list[Probe] = []

    # ---- reference: must come first, because what it writes defines "the
    # answer" that every other payload has to stand in for.
    ref = Probe("reference", "1", "solution/solve.sh")
    solve = scratch / "solution" / "solve.sh"
    artifact: str | None = None
    ref_blob: bytes | None = None
    artifact_why = ""
    if not solve.is_file():
        ref.skipped_reason = "no solution/solve.sh"
        artifact_why = "no reference solution to learn the answer shape from"
    else:
        reset_app(scratch, pristine)
        reset_logs(scratch)
        rc, out = run(["bash", str(solve)], scratch / "app", agent_timeout)
        after = snapshot(scratch / "app")
        before = snapshot(pristine)
        touched = sorted(k for k, v in after.items() if before.get(k) != v)
        if rc != 0:
            out += f"\n[solve.sh exited {rc}]"
        reward, vout = run_verifier(scratch, verifier_timeout)
        ref.reward = reward or "0"
        ref.output = out + "\n" + vout
        # A well-hardened verifier refuses to score when it cannot demote the
        # code it executes -- correct behaviour that this tool cannot satisfy,
        # since it runs as an ordinary user outside a container. Scoring 0 for
        # that reason says nothing about the task, and calling it FAIL condemns
        # sound tasks; a gate people learn to distrust stops being a gate.
        if reward != "1" and HARDENING_REFUSAL_RE.search(ref.output):
            ref.skipped_reason = (
                "verifier refused to score outside a container (its privilege "
                "drop cannot engage here); run the oracle to certify this task")
            artifact_why = "reference could not be certified offline"
        artifact, artifact_why = choose_artifact(touched, verifier_src)
        if artifact and (scratch / "app" / artifact).is_file():
            # reset_app for the next probe destroys it, and the generalisation
            # probes need the reference answer itself, not just its name.
            ref_blob = (scratch / "app" / artifact).read_bytes()
        if verbose:
            print(f"  reference wrote: {touched or '(nothing)'}")
            print(f"  answer artifact: {artifact or '(undetermined)'}")
    probes.append(ref)

    # ---- missing: needs no artifact knowledge — a pristine /app *is* the
    # no-answer state.
    p = Probe("missing", "0", "pristine /app, no answer produced")
    reset_app(scratch, pristine)
    reset_logs(scratch)
    p.reward, p.output = run_verifier(scratch, verifier_timeout)
    p.reward = p.reward or "0"
    probes.append(p)

    is_script = False
    if artifact:
        is_script = (Path(artifact).suffix in SCRIPT_SUFFIXES
                     and any(m in verifier_src for m in EXEC_MARKERS))
        if verbose:
            print(f"  answer shape:    {'executable script' if is_script else 'data file'}")

    order = ["empty", "garbage", "unchanged", "truncated"]
    if not artifact:
        for name in order:
            pr = Probe(name, "0")
            pr.skipped_reason = artifact_why or "answer artifact not identified"
            probes.append(pr)
        probes.extend(generalisation_probes(
            task, scratch, pristine, None, None, "", verifier_src,
            verifier_timeout, verbose))
        return probes

    plan = payloads(artifact, is_script, verifier_src)
    echo_src, echo_why = (None, "")
    if not is_script:
        echo_src, echo_why = pick_input(pristine, artifact)

    for name in order:
        data, desc = plan[name]
        pr = Probe(name, "0", f"{artifact}: {desc}")
        if name == "unchanged" and not is_script:
            if echo_src is None:
                pr.skipped_reason = echo_why
                probes.append(pr)
                continue
            data = echo_src.read_bytes()
            pr.note = f"{artifact}: bytes of {echo_src.relative_to(pristine)} echoed back"
        reset_app(scratch, pristine)
        reset_logs(scratch)
        target = scratch / "app" / artifact
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, 0o755 if is_script else 0o644)
        pr.reward, pr.output = run_verifier(scratch, verifier_timeout)
        pr.reward = pr.reward or "0"
        probes.append(pr)

    probes.extend(generalisation_probes(
        task, scratch, pristine, artifact, ref_blob, artifact_why,
        verifier_src, verifier_timeout, verbose))
    return probes


def report(task: Path, probes: list[Probe], verbose: bool) -> int:
    print(f"\nverifier probes — {task.name}")
    print(f"{'probe':<14} {'reward':>6} {'expect':>7}  {'result':<8} note")
    print("-" * 78)
    for p in probes:
        shown = "-" if p.skipped_reason else (p.reward or "none")
        note = p.skipped_reason or p.note
        print(f"{p.name:<14} {shown:>6} {p.expect:>7}  {p.status:<8} {note}")

    failed = [p for p in probes if p.status == "FAIL"]
    skipped = [p for p in probes if p.status == "SKIPPED"]
    print()
    if verbose or failed:
        for p in probes:
            if p.output and (verbose or p.status == "FAIL"):
                tail = p.output.strip()[-1500:]
                print(f"--- {p.name} output ---\n{tail}\n")

    # A skip is reported, not a violation — except for the reference, which
    # every other probe's construction depends on. Without it, nothing here is
    # certified.
    ref = next((p for p in probes if p.name == "reference"), None)
    ref_missing = ref is None or ref.status == "SKIPPED"

    if failed:
        print(f"FAIL: {len(failed)} probe(s) violated a MUST: "
              f"{', '.join(p.name for p in failed)}")
        return 1
    if ref_missing:
        # Distinguish "this task is broken" from "this tool cannot judge it
        # here". Both leave nothing certified, but only the first is a defect,
        # and reporting them alike condemns sound tasks -- run the oracle for
        # those. Exit 4 so a caller can tell the two apart.
        why = (ref.skipped_reason if ref is not None and ref.skipped_reason
               else "no reference probe")
        print(f"UNCERTIFIED: {why}")
        return 4
    print(f"OK: {len(probes) - len(skipped)} probe(s) passed"
          + (f", {len(skipped)} skipped" if skipped else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("task_dir", type=Path)
    ap.add_argument("--keep", action="store_true",
                    help="retain the scratch tree and print its path")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show staging decisions and every probe's output")
    args = ap.parse_args()

    task: Path = args.task_dir.resolve()
    if not (task / "task.toml").is_file():
        print(f"error: no task.toml in {task} — point at the task dir itself",
              file=sys.stderr)
        return 2
    if not (task / "tests" / "test.sh").is_file():
        print(f"error: no tests/test.sh in {task}", file=sys.stderr)
        return 2

    scratch = Path(tempfile.mkdtemp(prefix="probe-verifier-"))
    try:
        probes = probe_all(task, scratch, args.verbose)
        rc = report(task, probes, args.verbose)
    finally:
        if args.keep:
            print(f"scratch kept: {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
