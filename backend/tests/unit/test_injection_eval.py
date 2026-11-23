"""The injection check harness: its corpus, its arithmetic and its dry run. The live run is never
exercised here; a stub stands in for the model, and no test touches the network."""

import importlib.util
import json
import re
import socket
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

TOOL = Path(__file__).resolve().parents[3] / "tools" / "eval-injection.py"
if not TOOL.exists():
    pytest.skip(
        "the harness is maintainer tooling and is not in the published copy",
        allow_module_level=True,
    )

SENTINEL = "SENTINEL-8c21d7"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_injection_tool", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load()


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the harness tests must not open a connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def key_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("keys") / "eval.key"
    path.write_text(f"sk-or-{SENTINEL}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _example(identifier: str, label: str, lang: str = "en", kind: str = "k") -> object:
    category = "benign" if label == "benign" else "injection"
    return tool.Example(identifier, lang, label, category, kind, "mail", f"text of {identifier}")


def _outcome(identifier: str, label: str, score: float | None, **kwargs: str) -> object:
    noul = None if score is None else {"injection": score, "fraud": 0.0}
    return tool.Outcome(_example(identifier, label, **kwargs), noul, None if noul else "uncertain")


# The corpus


def test_the_corpus_is_balanced_bilingual_and_synthetic() -> None:
    examples = tool.load_corpus(tool.DEFAULT_CORPUS)

    counts = Counter((example.lang, example.label) for example in examples)
    assert len(examples) >= 80
    assert set(counts) == {(lang, label) for lang in ("sv", "en") for label in ("benign", "attack")}
    assert min(counts.values()) >= 20
    assert max(counts.values()) - min(counts.values()) <= 4
    assert {example.source for example in examples} == {"mail", "web", "calendar", "chat"}
    kinds = {example.kind for example in examples if example.label == "attack"}
    assert {
        "override",
        "hidden_html",
        "base64",
        "rot13",
        "urlencoded",
        "homoglyph",
        "fullwidth",
        "payment_fraud",
        "checker_manipulation",
    } <= kinds
    # Hard negatives are what make the false-alarm rate mean something.
    benign_kinds = {example.kind for example in examples if example.label == "benign"}
    assert {"web_security_article", "invoice_legit", "mail_imperative"} <= benign_kinds


def test_the_corpus_names_no_real_address() -> None:
    text = tool.DEFAULT_CORPUS.read_text(encoding="utf-8")

    for address in re.findall(r"[\w.+-]+@([\w.-]+\.[a-z]{2,})", text, flags=re.IGNORECASE):
        assert address.lower().endswith(("example.se", "example.com", "example.net"))
    for host in re.findall(r"https?://([\w.-]+)", text):
        assert host.endswith("example.net")


def test_a_corpus_with_a_repeated_id_or_an_unknown_label_is_refused(tmp_path: Path) -> None:
    row = {"id": "a", "lang": "en", "label": "benign", "category": "benign", "kind": "k",
           "source": "mail", "text": "x"}  # fmt: skip
    twice = tmp_path / "twice.jsonl"
    twice.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    odd = tmp_path / "odd.jsonl"
    odd.write_text(json.dumps({**row, "label": "maybe"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        tool.load_corpus(twice)
    with pytest.raises(ValueError):
        tool.load_corpus(odd)


# The arithmetic


def test_wilson_interval() -> None:
    assert tool.wilson(0, 0) is None
    low, high = tool.wilson(5, 10)
    assert (round(low, 3), round(high, 3)) == (0.237, 0.763)
    assert tool.wilson(0, 20)[0] == 0.0
    assert tool.wilson(20, 20)[1] == 1.0


def test_metrics_count_flagged_attacks_and_flagged_honest_texts_and_skip_failed_calls() -> None:
    outcomes = [
        _outcome("a1", "attack", 0.9, lang="sv", kind="override"),
        _outcome("a2", "attack", 0.4, lang="sv", kind="override"),
        _outcome("a3", "attack", 0.6, lang="en", kind="base64"),
        _outcome("b1", "benign", 0.5, lang="en"),
        _outcome("b2", "benign", 0.1, lang="sv"),
        _outcome("a4", "attack", None, lang="en", kind="base64"),
    ]

    row = tool.metrics_at(outcomes, 0.5)

    assert (row["recall"]["hits"], row["recall"]["of"]) == (2, 3)
    assert (row["false_alarms"]["hits"], row["false_alarms"]["of"]) == (1, 2)
    assert row["missed"] == ["a2"]
    assert row["false_alarm_ids"] == ["b1"]
    assert row["recall_by_language"]["sv"]["hits"] == 1
    assert row["recall_by_kind"]["base64"]["of"] == 1
    assert row["false_alarms_by_language"]["en"]["hits"] == 1


def test_the_higher_of_the_two_answers_decides() -> None:
    assert tool.flag_score({"injection": 0.1, "fraud": 0.8}) == 0.8


def test_the_suggested_threshold_is_the_highest_that_reaches_the_target() -> None:
    rows = [
        {"threshold": 0.1, "recall": {"rate": 1.0}},
        {"threshold": 0.3, "recall": {"rate": 0.96}},
        {"threshold": 0.5, "recall": {"rate": 0.8}},
    ]

    assert tool.suggest_threshold(rows, 0.95) == 0.3
    assert tool.suggest_threshold(rows, 1.01) is None
    assert tool.suggest_threshold([{"threshold": 0.5, "recall": {"rate": None}}], 0.5) is None


# The dry run


def test_the_dry_run_is_deterministic_writes_json_and_markdown_and_needs_no_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("one", "two"):
        assert tool.main(["--dry-run", "--out-dir", str(tmp_path / name)]) == 0

    results = []
    for name in ("one", "two"):
        (json_path,) = (tmp_path / name).glob("*.json")
        (md_path,) = (tmp_path / name).glob("*.md")
        result = json.loads(json_path.read_text(encoding="utf-8"))
        assert "Dry run with a fake model" in md_path.read_text(encoding="utf-8")
        results.append(result)
    first, second = results
    assert first["mode"] == "dry-run"
    assert first["measurement"] is False
    assert first["usage"]["answered"] == first["corpus"]["examples"] >= 80
    for volatile in ("run_id", "created_at"):
        del first[volatile], second[volatile]
    assert first == second
    assert "run " in capsys.readouterr().out


def test_the_result_holds_no_corpus_text(tmp_path: Path) -> None:
    tool.main(["--dry-run", "--out-dir", str(tmp_path)])

    written = "".join(path.read_text(encoding="utf-8") for path in tmp_path.iterdir())
    for example in tool.load_corpus(tool.DEFAULT_CORPUS):
        assert example.text not in written


def test_the_default_result_directory_is_ignored_by_git() -> None:
    ignored = (Path(tool.ROOT) / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "tmp/" in ignored
    assert tool.DEFAULT_OUT_DIR.relative_to(tool.ROOT).parts[0] == "tmp"


def test_one_mode_is_required_and_the_two_exclude_each_other() -> None:
    for argv in ([], ["--dry-run", "--live"]):
        with pytest.raises(SystemExit) as caught:
            tool.main(argv)
        assert caught.value.code == 2


# The live run, with a stub for the model


class StubScorer:
    name = "stub-model"

    def __init__(self, key: str, model: str, script: list[object] | None = None) -> None:
        self.key = key
        self.model = model
        self.calls = 0
        self.script = script or []

    def score(self, text: str) -> object:
        self.calls += 1
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
        attack = "ignore" in text.lower() or "ignorera" in text.lower()
        value = 0.9 if attack else 0.05
        return tool.Scored({"injection": value, "fraud": 0.01}, 10, 0.000001)


def _factory(holder: list[StubScorer], script: list[object] | None = None):  # type: ignore[no-untyped-def]
    def build(key: str, model: str) -> StubScorer:
        scorer = StubScorer(key, model, script)
        holder.append(scorer)
        return scorer

    return build


def test_live_needs_a_key_file_and_builds_no_model_without_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(tool.KEY_FILE_ENV, raising=False)
    built: list[StubScorer] = []

    code = tool.main(["--live", "--out-dir", str(tmp_path)], live_factory=_factory(built))

    assert code == 2
    assert built == []
    assert "key file" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_live_prints_calls_and_estimated_cost_before_it_runs_and_never_the_key(
    tmp_path: Path, key_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built: list[StubScorer] = []

    code = tool.main(
        ["--live", "--key-file", str(key_file), "--out-dir", str(tmp_path), "--limit", "10"],
        live_factory=_factory(built),
    )

    shown = capsys.readouterr().out
    assert code == 0
    assert "10 calls (limit 150)" in shown
    assert "estimated cost" in shown
    assert built[0].key == f"sk-or-{SENTINEL}"
    assert built[0].model == tool.DEFAULT_MODEL
    assert built[0].calls == 10
    assert SENTINEL not in shown
    for path in tmp_path.iterdir():
        assert SENTINEL not in path.read_text(encoding="utf-8")
    (json_path,) = tmp_path.glob("*.json")
    assert json.loads(json_path.read_text(encoding="utf-8"))["measurement"] is True


def test_the_key_file_can_be_named_by_the_environment(
    tmp_path: Path, key_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(tool.KEY_FILE_ENV, str(key_file))
    built: list[StubScorer] = []

    code = tool.main(
        ["--live", "--out-dir", str(tmp_path), "--limit", "3"], live_factory=_factory(built)
    )

    assert code == 0
    assert built[0].key == f"sk-or-{SENTINEL}"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604])
def test_a_key_file_others_can_read_is_refused_without_showing_the_key(
    tmp_path: Path, key_file: Path, mode: int
) -> None:
    key_file.chmod(mode)
    built: list[StubScorer] = []

    with pytest.raises(SystemExit) as caught:
        tool.main(
            ["--live", "--key-file", str(key_file), "--out-dir", str(tmp_path)],
            live_factory=_factory(built),
        )

    assert SENTINEL not in str(caught.value)
    assert built == []


def test_a_key_file_with_two_lines_is_refused(tmp_path: Path, key_file: Path) -> None:
    key_file.write_text(f"sk-or-{SENTINEL}\nsecond\n", encoding="utf-8")

    with pytest.raises(SystemExit) as caught:
        tool.main(["--live", "--key-file", str(key_file), "--out-dir", str(tmp_path)])

    assert SENTINEL not in str(caught.value)


@pytest.mark.parametrize(
    "limits", [["--max-calls", "20"], ["--max-cost-usd", "0.000001"]], ids=["calls", "cost"]
)
def test_a_plan_above_a_limit_is_refused_before_any_call(
    tmp_path: Path, key_file: Path, limits: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    built: list[StubScorer] = []

    code = tool.main(
        ["--live", "--key-file", str(key_file), "--out-dir", str(tmp_path), *limits],
        live_factory=_factory(built),
    )

    assert code == 2
    assert built == []
    assert "refused" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_a_transient_failure_is_retried_and_every_attempt_counts_as_a_call() -> None:
    examples = tool.load_corpus(tool.DEFAULT_CORPUS)[:2]
    scorer = StubScorer("k", "m", [tool.ScoreError("transient", 0.0), tool.ScoreError("transient")])
    waits: list[float] = []

    outcomes, usage = tool.run_scorer(scorer, examples, max_calls=10, sleep=waits.append)

    assert [o.noul is not None for o in outcomes] == [True, True]
    assert usage["calls"] == 4
    assert waits == [1.0, 1.0]


def test_the_call_limit_stops_the_run_and_marks_the_rest_not_run() -> None:
    examples = tool.load_corpus(tool.DEFAULT_CORPUS)[:5]
    scorer = StubScorer("k", "m")

    outcomes, usage = tool.run_scorer(scorer, examples, max_calls=3)

    assert scorer.calls == 3
    assert (usage["answered"], usage["not_run"], usage["aborted"]) == (3, 2, "call limit reached")
    assert len(outcomes) == 3


def test_a_refused_key_stops_the_run_at_once() -> None:
    examples = tool.load_corpus(tool.DEFAULT_CORPUS)[:5]
    scorer = StubScorer("k", "m", [tool.ScoreError("rejected_auth")])

    outcomes, usage = tool.run_scorer(scorer, examples, max_calls=50)

    assert scorer.calls == 1
    assert usage["aborted"] == "the key was refused"
    assert outcomes[0].error == "rejected_auth"


def test_an_incomplete_live_run_exits_with_failure_and_says_so(
    tmp_path: Path, key_file: Path
) -> None:
    built: list[StubScorer] = []
    script: list[object] = [tool.ScoreError("uncertain")]

    code = tool.main(
        ["--live", "--key-file", str(key_file), "--out-dir", str(tmp_path), "--limit", "4"],
        live_factory=_factory(built, script),
    )

    assert code == 1
    (summary,) = tmp_path.glob("*.md")
    assert "failed 1" in summary.read_text(encoding="utf-8")
