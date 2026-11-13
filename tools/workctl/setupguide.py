"""The questions of ``work.sh setup``: language, memory, model server and key, memory model, allowed addresses,
rooms and the apps' language. Every answer is written to ``work.env`` (or, for the key, to the secrets files) as it
is given, so a second run offers the earlier answers again and touches nothing else. The shell keeps what needs
docker: the tool checks, the secrets on a first run, and the two last questions (autostart, start now)."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from . import addresses, messages, modelserver, prompts, secretfiles, workenv

MEMORY = "SIDEKICK_WORK_MEMORY"
BASE_URL = "SIDEKICK_WORK_MODEL_BASE_URL"
MEMORY_MODEL = "SIDEKICK_WORK_MEMORY_MODEL"
ALLOW = "SIDEKICK_WORK_ALLOW"
ROOMS = secretfiles.ROOMS_NAME
LOCALE = "SIDEKICK_WORK_LOCALE"
APP_LANGUAGES = ("sv", "en")
ALL_ROOMS = "-"
NO_KEY = "-"

Ask = Callable[..., str]
Confirm = Callable[[str, str], bool]
FetchModels = Callable[[str, str], Sequence[str]]


def normalize_language(answer: str) -> str:
    """``sv`` for an answer that starts with sv or SV, ``en`` for anything else."""
    return "sv" if answer.startswith(("sv", "SV")) else "en"


def ask_language(current: str, ask: Ask = prompts.ask) -> str:
    """The language of the guide's own texts, asked first of all."""
    prompt = prompts.question(messages.text(current, "lang_q"), current)
    return normalize_language(ask(prompt, current))


class _Guide:
    def __init__(
        self,
        lang: str,
        env_file: Path,
        secrets_dir: Path,
        default_rooms: str,
        ask: Ask,
        confirm: Confirm,
        fetch: FetchModels,
        out: TextIO,
        err: TextIO,
    ) -> None:
        self.lang = lang
        self.env_file = env_file
        self.secrets_dir = secrets_dir
        self.default_rooms = default_rooms
        self._ask = ask
        self._confirm = confirm
        self._fetch = fetch
        self.out = out
        self.err = err

    def say(self, key: str) -> None:
        print(messages.text(self.lang, key).rstrip("\n"), file=self.out)

    def sayf(self, key: str, *values: object) -> None:
        print(messages.render(self.lang, key, *values), file=self.out)

    def errf(self, key: str, *values: object) -> None:
        print(messages.render(self.lang, key, *values), file=self.err)

    def value(self, key: str) -> str:
        return workenv.env_value(self.env_file, key)

    def ask(self, key: str, default: str = "", secret: bool = False) -> str:
        """The question of the message table with ``default`` in brackets; the answer, else the default."""
        self.out.flush()
        prompt = prompts.question(messages.text(self.lang, key), default)
        if secret:
            return self._ask(prompt, default, secret=True)
        return self._ask(prompt, default)

    def confirm(self, key: str, default: str) -> bool:
        self.out.flush()
        return self._confirm(prompts.question(messages.text(self.lang, key)), default)

    def placeholder_free(self, key: str) -> str:
        """The setting, or nothing while it still holds a ``<placeholder>`` of the example file."""
        value = self.value(key)
        return "" if "<" in value else value

    def memory_question(self) -> bool:
        if workenv.memory_wanted(self.env_file):
            return self.confirm("memory_q_on", "y")
        return self.confirm("memory_q", "n")

    def model_server(self) -> tuple[str, list[str]]:
        """Address and key of the model server, tested with ``GET /models``. Returns the address and the model ids."""
        url = self.placeholder_free(BASE_URL)
        kept_key = secretfiles.stored_model_key(self.secrets_dir)
        models: list[str] = []
        key = ""
        while True:
            url = self.ask("url_q", url)
            try:
                addresses.parse_base_url(url, self.lang)
            except addresses.AddressError as error:
                self.errf("url_bad", error)
                url = ""
                continue
            key = self.ask("key_q", secret=True)
            tested = kept_key if key == "" else ("" if key == NO_KEY else key)
            self.errf("testing", url)
            try:
                models = [model for model in self._fetch(url, tested) if model]
            except ValueError:
                self.errf("test_fail")
                if not self.confirm("retry_q", "n"):
                    break
                continue
            self.sayf("test_ok", len(models))
            break
        workenv.set_value(self.env_file, BASE_URL, url)
        if key:
            secretfiles.apply_model_key(self.secrets_dir, "" if key == NO_KEY else key)
        return url, models

    def memory_model(self, models: Sequence[str]) -> None:
        """The memory model (Hindsight's; Sidekick itself calls no model), chosen from the server's list."""
        current = self.placeholder_free(MEMORY_MODEL)
        if models:
            self.say("models_head")
            for number, model in enumerate(models, 1):
                print(f"  {number}) {model}", file=self.out)
            answer = self.ask("mem_q", current or models[0])
            chosen = prompts.pick_choice(answer, models)
        else:
            chosen = self.ask("mem_q", current)
        workenv.set_value(self.env_file, MEMORY_MODEL, chosen)

    def allowlist(self, url: str, memory_on: bool) -> None:
        self.say("allow_note")
        model_port = 0
        if memory_on:
            try:
                model_port = addresses.parse_base_url(url, self.lang).port
            except addresses.AddressError:
                model_port = 0
        while True:
            allow = self.ask("allow_q", self.value(ALLOW))
            if not allow:
                break
            try:
                addresses.parse_allowlist(allow, model_port, self.lang)
                break
            except addresses.AddressError as error:
                self.errf("allow_bad", error)
        if allow:
            workenv.set_value(self.env_file, ALLOW, allow)
        else:
            workenv.unset_value(self.env_file, ALLOW)

    def rooms(self) -> str:
        """The proposal for a work machine is every room except shopping; Enter takes the value offered in brackets
        (an existing work.env value wins) and ``-`` switches every room on."""
        self.say("rooms_note")
        rooms = self.ask("rooms_q", self.value(ROOMS) or self.default_rooms) or self.default_rooms
        if rooms == ALL_ROOMS:
            workenv.unset_value(self.env_file, ROOMS)
        else:
            workenv.set_value(self.env_file, ROOMS, rooms)
        return rooms

    def app_language(self) -> str:
        """The apps' language is its own question (the guide's display language may differ); Swedish is the proposal
        unless work.env already holds a value."""
        while True:
            language = self.ask("applang_q", self.value(LOCALE) or "sv")
            if language in APP_LANGUAGES:
                break
            self.errf("applang_bad")
        workenv.set_value(self.env_file, LOCALE, language)
        return language

    def run(self) -> None:
        memory_on = self.memory_question()
        url, models = "", []
        if memory_on:
            workenv.set_value(self.env_file, MEMORY, "on")
            url, models = self.model_server()
            self.memory_model(models)
        else:
            workenv.set_value(self.env_file, MEMORY, "off")
        self.allowlist(url, memory_on)
        rooms = self.rooms()
        language = self.app_language()
        self.say("wrote")
        self.sayf("summary", language, rooms)
        if memory_on:
            self.sayf("summary_mem_on", url)
        else:
            self.say("summary_mem_off")
        print(file=self.out)


def run_guide(
    lang: str,
    env_file: Path,
    secrets_dir: Path,
    default_rooms: str,
    *,
    ask: Ask = prompts.ask,
    confirm: Confirm = prompts.confirm,
    fetch: FetchModels = modelserver.fetch_model_ids,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> None:
    """Ask the questions of the guide up to and including the summary. ``ValueError`` when a value cannot be written
    to work.env; the caller reports it."""
    _Guide(lang, env_file, secrets_dir, default_rooms, ask, confirm, fetch, out or sys.stdout, err or sys.stderr).run()
