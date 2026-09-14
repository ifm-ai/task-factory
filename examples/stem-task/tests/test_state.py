import json
import os
from pathlib import Path

EXPECTED = [3]


def coerce_value(v):
    """Coerce string digits to int for type-flexible comparisons."""
    if isinstance(v, str) and v.lstrip("-").isdigit():
        return int(v)
    return v


def load_answer():
    path = Path(os.environ.get("ANSWER_PATH", "/app/answer.json"))
    assert path.exists(), f"{path} does not exist"
    data = json.loads(path.read_text())
    assert isinstance(data, dict)
    return data


def test_top_level_shape():
    data = load_answer()
    assert set(data.keys()) == {"solutions"}
    assert isinstance(data["solutions"], list)


def test_schema_and_order():
    values = [coerce_value(v) for v in load_answer()["solutions"]]
    assert values == sorted(values)
    assert len(values) == len(set(values))
    for value in values:
        assert isinstance(value, int)
        assert value > 1


def test_exact_values():
    values = [coerce_value(v) for v in load_answer()["solutions"]]
    assert values == EXPECTED


def test_every_reported_solution_is_valid():
    for n in [coerce_value(v) for v in load_answer()["solutions"]]:
        assert (pow(2, n, n * n) + 1) % (n * n) == 0
