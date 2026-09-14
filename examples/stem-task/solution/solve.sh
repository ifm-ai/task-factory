#!/bin/bash
python3 - <<'PY'
import json
import os
from pathlib import Path

# The unique solution is n = 3.
answer = {"solutions": [3]}

path = Path(os.environ.get("ANSWER_PATH", "/app/answer.json"))
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(answer))
PY
