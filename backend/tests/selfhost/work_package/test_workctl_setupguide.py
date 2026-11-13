"""The questions of `work.sh setup` with scripted answers (no terminal, no model server)."""

import io
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from tools.workctl import secretfiles, setupguide, workenv

DEFAULT_ROOMS = "work,journal,contacts,control"
KEY = "guide-key"


class Script:
    """Scripted answers for ``ask`` (and ``confirm``); every prompt is recorded."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.secret_prompts: list[str] = []

    def ask(self, prompt: str, default: str = "", *, secret: bool = False) -> str:
        self.prompts.append(prompt)
        if secret:
            self.secret_prompts.append(prompt)
        answer = self.answers.pop(0)
        return answer or default

    def confirm(self, prompt: str, default: str) -> bool:
        self.prompts.append(prompt)
        return (self.answers.pop(0) or default) in ("y", "j")


@pytest.fixture(name="files")
def _files(tmp_path: Path) -> tuple[Path, Path]:
    env_file = tmp_path / "work.env"
    env_file.write_text(
        "# A note.\nSIDEKICK_WORK_MODEL_BASE_URL=<https://model.company.lan/v1>\nSIDEKICK_WORK_MEMORY_MODEL=<model>\n",
        encoding="utf-8",
    )
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "sidekick.env").write_text("SIDEKICK_DATABASE_URL=x\n", encoding="utf-8")
    (secrets / "hindsight.env").write_text(
        "HINDSIGHT_API_LLM_API_KEY=not-needed\n", encoding="utf-8"
    )
    return env_file, secrets


def _fetch(
    models: Sequence[str], seen: list[tuple[str, str]] | None = None
) -> Callable[[str, str], list[str]]:
    def fetch(url: str, key: str) -> list[str]:
        if seen is not None:
            seen.append((url, key))
        if key == "wrong":
            raise ValueError("no")
        return list(models)

    return fetch


def _run(
    files: tuple[Path, Path],
    script: Script,
    fetch: Callable[[str, str], Sequence[str]],
    lang: str = "en",
) -> tuple[str, str]:
    out, err = io.StringIO(), io.StringIO()
    setupguide.run_guide(
        lang,
        files[0],
        files[1],
        DEFAULT_ROOMS,
        ask=script.ask,
        confirm=script.confirm,
        fetch=fetch,
        out=out,
        err=err,
    )
    return out.getvalue(), err.getvalue()


@pytest.mark.parametrize(
    ("answer", "language"),
    [("sv", "sv"), ("SV", "sv"), ("svenska", "sv"), ("en", "en"), ("", "en"), ("x", "en")],
)
def test_the_guide_language_is_swedish_only_for_an_answer_starting_with_sv(
    answer: str, language: str
) -> None:
    assert setupguide.normalize_language(answer) == language


def test_ask_language_offers_the_current_language_as_the_default() -> None:
    script = Script("")
    assert setupguide.ask_language("sv", script.ask) == "sv"
    assert script.prompts[0].endswith("[sv]: ")


def test_memory_on_stores_url_key_model_and_the_rest(files: tuple[Path, Path]) -> None:
    env_file, secrets = files
    seen: list[tuple[str, str]] = []
    script = Script(
        "y", "https://model.company.lan/v1", KEY, "2", "embed.company.lan:9443", "work", "en"
    )
    out, err = _run(files, script, _fetch(["glm-x", "flash-y"], seen))
    assert seen == [("https://model.company.lan/v1", KEY)]
    assert workenv.env_value(env_file, "SIDEKICK_WORK_MEMORY") == "on"
    assert (
        workenv.env_value(env_file, "SIDEKICK_WORK_MODEL_BASE_URL")
        == "https://model.company.lan/v1"
    )
    assert workenv.env_value(env_file, "SIDEKICK_WORK_MEMORY_MODEL") == "flash-y"
    assert workenv.env_value(env_file, "SIDEKICK_WORK_ALLOW") == "embed.company.lan:9443"
    assert workenv.env_value(env_file, "SIDEKICK_ENABLED_ROOMS") == "work"
    assert workenv.env_value(env_file, "SIDEKICK_WORK_LOCALE") == "en"
    assert secretfiles.stored_model_key(secrets) == KEY
    assert "  1) glm-x\n  2) flash-y\n" in out
    assert "2 models found" in out
    assert "App language: en. Rooms: work." in out
    assert KEY not in out + err
    assert len(script.secret_prompts) == 1
    assert "# A note." in env_file.read_text(encoding="utf-8")


def test_memory_off_asks_no_server_question_and_proposes_every_room_but_shopping(
    files: tuple[Path, Path],
) -> None:
    env_file, _ = files
    script = Script("n", "", "", "")
    out, err = _run(files, script, _fetch([]))
    assert workenv.env_value(env_file, "SIDEKICK_WORK_MEMORY") == "off"
    assert workenv.env_value(env_file, "SIDEKICK_ENABLED_ROOMS") == DEFAULT_ROOMS
    assert workenv.env_value(env_file, "SIDEKICK_WORK_LOCALE") == "sv"
    assert "Memory: off" in out
    assert not any("Model server address" in prompt for prompt in script.prompts)
    assert any(f"[{DEFAULT_ROOMS}]" in prompt for prompt in script.prompts)
    assert err == ""


def test_a_dash_for_the_rooms_switches_every_room_on(files: tuple[Path, Path]) -> None:
    env_file, _ = files
    workenv.set_value(env_file, "SIDEKICK_ENABLED_ROOMS", "work")
    _run(files, Script("n", "", "-", ""), _fetch([]))
    assert workenv.env_value(env_file, "SIDEKICK_ENABLED_ROOMS") == ""
    assert "# SIDEKICK_ENABLED_ROOMS=work" in env_file.read_text(encoding="utf-8")


def test_a_bad_address_is_asked_for_again_and_the_key_is_not_asked_for_it(
    files: tuple[Path, Path],
) -> None:
    env_file, _ = files
    script = Script("y", "ftp://nope", "https://m.company.lan/v1", KEY, "", "", "", "")
    _, err = _run(files, script, _fetch(["glm-x"]))
    assert "That address cannot be used" in err
    assert len(script.secret_prompts) == 1
    assert workenv.env_value(env_file, "SIDEKICK_WORK_MEMORY_MODEL") == "glm-x"


def test_a_failed_test_can_be_given_up_and_the_typed_values_are_kept(
    files: tuple[Path, Path],
) -> None:
    env_file, secrets = files
    script = Script("y", "https://m.company.lan/v1", "wrong", "n", "typed-model", "", "", "")
    out, err = _run(files, script, _fetch(["glm-x"]))
    assert "did not answer as expected" in err
    assert workenv.env_value(env_file, "SIDEKICK_WORK_MODEL_BASE_URL") == "https://m.company.lan/v1"
    assert workenv.env_value(env_file, "SIDEKICK_WORK_MEMORY_MODEL") == "typed-model"
    assert "models found" not in out
    assert secretfiles.stored_model_key(secrets) == "wrong"


def test_an_empty_key_tests_with_the_stored_one_and_a_dash_clears_it(
    files: tuple[Path, Path],
) -> None:
    _, secrets = files
    secretfiles.apply_model_key(secrets, "stored")
    seen: list[tuple[str, str]] = []
    _run(files, Script("y", "https://m.company.lan/v1", "", "", "", "", ""), _fetch(["a"], seen))
    assert seen == [("https://m.company.lan/v1", "stored")]
    assert secretfiles.stored_model_key(secrets) == "stored"
    seen.clear()
    _run(files, Script("y", "https://m.company.lan/v1", "-", "", "", "", ""), _fetch(["a"], seen))
    assert seen == [("https://m.company.lan/v1", "")]
    assert secretfiles.stored_model_key(secrets) == ""


def test_the_allowlist_is_asked_again_after_a_bad_entry_and_checked_against_the_model_port(
    files: tuple[Path, Path],
) -> None:
    env_file, _ = files
    script = Script(
        "y",
        "https://m.company.lan:8443/v1",
        KEY,
        "",
        "x.company.lan:8443",
        "10.0.0.5:443",
        "",
        "",
        "",
    )
    _, err = _run(files, script, _fetch(["a"]))
    assert err.count("Invalid list") == 2
    assert workenv.env_value(env_file, "SIDEKICK_WORK_ALLOW") == ""


def test_an_earlier_allowlist_is_offered_and_can_be_kept(files: tuple[Path, Path]) -> None:
    env_file, _ = files
    workenv.set_value(env_file, "SIDEKICK_WORK_ALLOW", "embed.company.lan:443")
    script = Script("n", "", "", "")
    _run(files, script, _fetch([]))
    assert workenv.env_value(env_file, "SIDEKICK_WORK_ALLOW") == "embed.company.lan:443"
    assert any("[embed.company.lan:443]" in prompt for prompt in script.prompts)


def test_the_app_language_is_asked_again_until_it_is_sv_or_en(files: tuple[Path, Path]) -> None:
    env_file, _ = files
    script = Script("n", "", "", "de", "sv")
    _, err = _run(files, script, _fetch([]))
    assert workenv.env_value(env_file, "SIDEKICK_WORK_LOCALE") == "sv"
    assert "Answer sv or en" in err


def test_the_texts_follow_the_guide_language(files: tuple[Path, Path]) -> None:
    out, _ = _run(files, Script("n", "", "", ""), _fetch([]), lang="sv")
    assert "Minne: av" in out
