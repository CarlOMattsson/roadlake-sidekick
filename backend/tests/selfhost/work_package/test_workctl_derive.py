"""The values compose needs, derived from work.env by tools/workctl."""

import stat
from pathlib import Path

import pytest
from tools.workctl import cli, derive, messages

PLACEHOLDERS = {
    "SIDEKICK_WORK_MODEL_PORT": "1",
    "SIDEKICK_WORK_MODEL_PATH": "/v1",
    "SIDEKICK_WORK_UPSTREAM_ADDR": "unset:1",
    "SIDEKICK_WORK_UPSTREAM_HOST_HEADER": "unset",
    "SIDEKICK_WORK_UPSTREAM_TLS": "",
    "SIDEKICK_WORK_MEMORY_MODEL": "unset",
}
CONFIGURED_BUNDLE = "/corp/ca.pem"


def _derive(
    tmp_path: Path, text: str, lenient: bool = False, environ: dict[str, str] | None = None
) -> derive.Derived:
    env_file = tmp_path / "work.env"
    env_file.write_text(text, encoding="utf-8")
    return derive.derive(
        env_file, tmp_path / "generated", "en", lenient, {} if environ is None else environ
    )


def _on(url: str, extra: str = "", model: str = "fast") -> str:
    return f"SIDEKICK_WORK_MODEL_BASE_URL={url}\nSIDEKICK_WORK_MEMORY_MODEL={model}\n{extra}"


def test_an_http_server_gets_the_port_in_its_host_header(tmp_path: Path) -> None:
    result = _derive(
        tmp_path, _on("http://vllm.company.lan:8000/v1", "SIDEKICK_WORK_CA_BUNDLE=/ca\n")
    )
    assert result.memory is True and result.allow == []
    assert result.exports == {
        "SIDEKICK_WORK_MODEL_PORT": "8000",
        "SIDEKICK_WORK_MODEL_PATH": "/v1",
        "SIDEKICK_WORK_UPSTREAM_ADDR": "vllm.company.lan:8000",
        "SIDEKICK_WORK_UPSTREAM_HOST_HEADER": "vllm.company.lan:8000",
        "SIDEKICK_WORK_UPSTREAM_TLS": "",
        "SIDEKICK_WORK_MEMORY_ENABLED": "true",
        "SIDEKICK_WORK_MEMORY_MODEL": "fast",
        "SIDEKICK_WORK_CA_BUNDLE": "/ca",
    }


@pytest.mark.parametrize(
    ("url", "host_header"),
    [
        ("http://m.lan/v1", "m.lan"),
        ("https://m.lan/v1", "m.lan"),
        ("http://m.lan:443/v1", "m.lan:443"),
        ("https://m.lan:80/v1", "m.lan:80"),
        ("https://m.lan:8443/v1", "m.lan:8443"),
        ("http://[2001:db8::1]:8000/v1", "[2001:db8::1]:8000"),
        ("http://[2001:db8::1]/v1", "[2001:db8::1]"),
    ],
)
def test_the_host_header_leaves_out_only_the_default_port(
    tmp_path: Path, url: str, host_header: str
) -> None:
    exports = _derive(tmp_path, _on(url, "SIDEKICK_WORK_CA_BUNDLE=/ca\n")).exports
    assert exports["SIDEKICK_WORK_UPSTREAM_HOST_HEADER"] == host_header


def test_an_https_server_with_a_name_verifies_the_certificate_and_sends_sni(tmp_path: Path) -> None:
    exports = _derive(
        tmp_path, _on("https://llm.company.lan/v1", "SIDEKICK_WORK_CA_BUNDLE=/ca\n")
    ).exports
    assert exports["SIDEKICK_WORK_MODEL_PORT"] == "443"
    assert exports["SIDEKICK_WORK_UPSTREAM_TLS"] == (
        "ssl verify required ca-file /etc/ssl/work-ca.pem verifyhost llm.company.lan "
        "sni str(llm.company.lan)"
    )


def test_an_https_server_by_ip_address_sends_no_sni(tmp_path: Path) -> None:
    exports = _derive(
        tmp_path, _on("https://10.0.0.5:8443/v1", "SIDEKICK_WORK_CA_BUNDLE=/ca\n")
    ).exports
    assert exports["SIDEKICK_WORK_UPSTREAM_TLS"] == (
        "ssl verify required ca-file /etc/ssl/work-ca.pem verifyhost 10.0.0.5"
    )


def test_a_resolve_ip_replaces_the_upstream_address_but_not_the_host_header(tmp_path: Path) -> None:
    extra = "SIDEKICK_WORK_MODEL_RESOLVE_IP=10.1.2.3\nSIDEKICK_WORK_CA_BUNDLE=/ca\n"
    exports = _derive(tmp_path, _on("http://vllm.company.lan:8000/v1", extra)).exports
    assert exports["SIDEKICK_WORK_UPSTREAM_ADDR"] == "10.1.2.3:8000"
    assert exports["SIDEKICK_WORK_UPSTREAM_HOST_HEADER"] == "vllm.company.lan:8000"


def test_an_ipv6_resolve_ip_is_bracketed(tmp_path: Path) -> None:
    extra = "SIDEKICK_WORK_MODEL_RESOLVE_IP=2001:db8::1\nSIDEKICK_WORK_CA_BUNDLE=/ca\n"
    exports = _derive(tmp_path, _on("http://vllm.company.lan:8000/v1", extra)).exports
    assert exports["SIDEKICK_WORK_UPSTREAM_ADDR"] == "[2001:db8::1]:8000"


def test_the_allowlist_is_parsed_against_the_model_port(tmp_path: Path) -> None:
    extra = "SIDEKICK_WORK_ALLOW=embed.company.lan:443\nSIDEKICK_WORK_CA_BUNDLE=/ca\n"
    assert _derive(tmp_path, _on("http://m.lan:8000/v1", extra)).allow == [
        ("embed.company.lan", 443)
    ]


def test_an_allowlist_port_equal_to_the_model_port_is_an_error_with_its_reason(
    tmp_path: Path,
) -> None:
    extra = "SIDEKICK_WORK_ALLOW=embed.company.lan:8000\n"
    with pytest.raises(derive.DeriveError) as raised:
        _derive(tmp_path, _on("http://m.lan:8000/v1", extra))
    assert str(raised.value) == (
        "SIDEKICK_WORK_ALLOW: 'embed.company.lan:8000': port 8000 is already used "
        "(the model server, MCP or another entry)"
    )


def test_a_bad_allowlist_is_ignored_while_stopping(tmp_path: Path) -> None:
    result = _derive(
        tmp_path, _on("http://m.lan:8000/v1", "SIDEKICK_WORK_ALLOW=10.0.0.1:443\n"), lenient=True
    )
    assert result.allow == [] and result.memory is True


@pytest.mark.parametrize("url", ["", "<model server>", "http://<host>/v1"])
def test_a_missing_or_placeholder_url_is_an_error_with_both_lines(tmp_path: Path, url: str) -> None:
    with pytest.raises(derive.DeriveError) as raised:
        _derive(tmp_path, _on(url))
    assert str(raised.value) == messages.text("en", "url_unset") + "\n" + messages.text(
        "en", "url_unset_hint"
    )


@pytest.mark.parametrize("url", ["", "ftp://m.lan/v1"])
def test_an_unusable_url_gives_placeholders_while_stopping(tmp_path: Path, url: str) -> None:
    result = _derive(
        tmp_path, _on(url, "SIDEKICK_WORK_ALLOW=embed.company.lan:443\n"), lenient=True
    )
    assert result.memory is True and result.allow == []
    assert {name: result.exports[name] for name in PLACEHOLDERS} == PLACEHOLDERS
    assert result.exports["SIDEKICK_WORK_MEMORY_ENABLED"] == "true"


def test_an_unparsable_url_is_an_error_naming_the_setting(tmp_path: Path) -> None:
    with pytest.raises(derive.DeriveError) as raised:
        _derive(tmp_path, _on("ftp://m.lan/v1"))
    assert str(raised.value) == (
        "SIDEKICK_WORK_MODEL_BASE_URL: "
        "the address must start with http:// or https:// and have a host"
    )


def test_the_gateways_own_mcp_port_is_refused_even_while_stopping(tmp_path: Path) -> None:
    for lenient in (False, True):
        with pytest.raises(derive.DeriveError) as raised:
            _derive(tmp_path, _on("http://m.lan:8765/v1"), lenient=lenient)
        assert str(raised.value) == messages.text("en", "port_clash")


@pytest.mark.parametrize("model", ["", "<model id>"])
def test_a_missing_or_placeholder_memory_model_is_an_error(tmp_path: Path, model: str) -> None:
    with pytest.raises(derive.DeriveError) as raised:
        _derive(tmp_path, _on("http://m.lan:8000/v1", model=model))
    assert str(raised.value) == messages.text("en", "mem_unset")


def test_a_missing_memory_model_is_fine_while_stopping(tmp_path: Path) -> None:
    result = _derive(
        tmp_path,
        _on("http://m.lan:8000/v1", "SIDEKICK_WORK_CA_BUNDLE=/ca\n", model=""),
        lenient=True,
    )
    assert result.exports["SIDEKICK_WORK_MEMORY_MODEL"] == ""


def test_the_environment_overrides_the_memory_model_of_work_env(tmp_path: Path) -> None:
    result = _derive(
        tmp_path,
        _on("http://m.lan:8000/v1", "SIDEKICK_WORK_CA_BUNDLE=/ca\n"),
        environ={"SIDEKICK_WORK_MEMORY_MODEL": "from-env"},
    )
    assert result.exports["SIDEKICK_WORK_MEMORY_MODEL"] == "from-env"


def test_memory_off_needs_no_model_server_and_uses_placeholders(tmp_path: Path) -> None:
    result = _derive(
        tmp_path, "SIDEKICK_WORK_MEMORY=off\nSIDEKICK_WORK_ALLOW=embed.company.lan:443\n"
    )
    assert result.memory is False
    assert result.allow == [("embed.company.lan", 443)]
    assert result.exports["SIDEKICK_WORK_MEMORY_ENABLED"] == "false"
    assert {name: result.exports[name] for name in PLACEHOLDERS} == PLACEHOLDERS


def test_memory_off_with_a_bad_allowlist_is_an_error_unless_stopping(tmp_path: Path) -> None:
    text = "SIDEKICK_WORK_MEMORY=off\nSIDEKICK_WORK_ALLOW=nonsense\n"
    with pytest.raises(derive.DeriveError) as raised:
        _derive(tmp_path, text)
    assert str(raised.value).startswith("SIDEKICK_WORK_ALLOW: 'nonsense'")
    assert _derive(tmp_path, text, lenient=True).allow == []


def test_lines_are_memory_then_exports_then_allowlist(tmp_path: Path) -> None:
    lines = _derive(
        tmp_path, "SIDEKICK_WORK_MEMORY=off\nSIDEKICK_WORK_ALLOW=a.lan:443,b.lan:444\n"
    ).lines()
    assert lines[0] == "MEMORY=0"
    assert "SIDEKICK_WORK_MODEL_PORT=1" in lines
    assert "SIDEKICK_WORK_UPSTREAM_TLS=" in lines
    assert lines[-2:] == ["allow a.lan 443", "allow b.lan 444"]


def test_the_texts_the_errors_use_are_plain(tmp_path: Path) -> None:
    """They are printed without printf: a directive or an escape would show up literally."""
    for key in ("url_unset", "url_unset_hint", "port_clash", "mem_unset"):
        for lang in ("sv", "en"):
            assert "%" not in messages.text(lang, key) and "\\" not in messages.text(lang, key)


def test_a_configured_ca_bundle_is_used_as_it_is(tmp_path: Path) -> None:
    assert derive.ca_bundle(CONFIGURED_BUNDLE, tmp_path / "generated") == CONFIGURED_BUNDLE
    assert not (tmp_path / "generated").exists()


def test_the_system_ca_bundle_is_used_when_it_exists(tmp_path: Path) -> None:
    system = tmp_path / "system.crt"
    system.write_text("pem", encoding="utf-8")
    assert derive.ca_bundle("", tmp_path / "generated", system) == str(system)
    assert not (tmp_path / "generated").exists()


def test_without_a_system_bundle_an_empty_world_readable_bundle_is_made(tmp_path: Path) -> None:
    gen_dir = tmp_path / "generated"
    path = derive.ca_bundle("", gen_dir, tmp_path / "absent.crt", system_name="Linux")
    assert path == str(gen_dir / "ca-bundle.pem")
    assert (gen_dir / "ca-bundle.pem").read_bytes() == b""
    assert stat.S_IMODE((gen_dir / "ca-bundle.pem").stat().st_mode) == 0o644
    assert stat.S_IMODE(gen_dir.stat().st_mode) == 0o755


def test_on_macos_the_keychain_certificates_are_exported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], stdout: object, **_kwargs: object) -> None:
        calls.append(command)
        assert hasattr(stdout, "write")
        stdout.write(b"-----BEGIN CERTIFICATE-----\n")  # type: ignore[union-attr]

    monkeypatch.setattr(derive.shutil, "which", lambda _name: "/usr/bin/security")
    monkeypatch.setattr(derive.subprocess, "run", fake_run)
    path = derive.ca_bundle(
        "", tmp_path / "generated", tmp_path / "absent.crt", system_name="Darwin"
    )
    assert calls == [["/usr/bin/security", "find-certificate", "-a", "-p", *derive.MACOS_KEYCHAINS]]
    assert Path(path).read_bytes() == b"-----BEGIN CERTIFICATE-----\n"


def test_on_macos_a_failing_export_leaves_an_empty_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_run(*_args: object, **_kwargs: object) -> None:
        raise OSError("no security")

    monkeypatch.setattr(derive.shutil, "which", lambda _name: "/usr/bin/security")
    monkeypatch.setattr(derive.subprocess, "run", failing_run)
    path = derive.ca_bundle(
        "", tmp_path / "generated", tmp_path / "absent.crt", system_name="Darwin"
    )
    assert Path(path).read_bytes() == b""


def _run_derive(
    tmp_path: Path, text: str, capsys: pytest.CaptureFixture[str], *flags: str, lang: str = "en"
) -> tuple[int, str, str]:
    env_file = tmp_path / "work.env"
    env_file.write_text(text, encoding="utf-8")
    code = cli.main(
        [
            "derive",
            "--env-file",
            str(env_file),
            "--gen-dir",
            str(tmp_path / "generated"),
            "--lang",
            lang,
            *flags,
        ]
    )
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_the_derive_command_prints_the_lines_work_sh_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _on(
        "http://m.lan:8000/v1",
        "SIDEKICK_WORK_ALLOW=embed.company.lan:443\nSIDEKICK_WORK_CA_BUNDLE=/ca\n",
    )
    code, out, err = _run_derive(tmp_path, text, capsys)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == "MEMORY=1"
    assert "SIDEKICK_WORK_UPSTREAM_ADDR=m.lan:8000" in lines
    assert "SIDEKICK_WORK_CA_BUNDLE=/ca" in lines
    assert lines[-1] == "allow embed.company.lan 443"


def test_the_derive_command_reports_an_unusable_work_env_on_stderr_with_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run_derive(tmp_path, _on("<model server>"), capsys, lang="sv")
    assert (code, out) == (1, "")
    assert (
        err
        == messages.text("sv", "url_unset") + "\n" + messages.text("sv", "url_unset_hint") + "\n"
    )


def test_the_derive_command_with_lenient_accepts_the_same_work_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run_derive(
        tmp_path, _on("<model server>", "SIDEKICK_WORK_CA_BUNDLE=/ca\n"), capsys, "--lenient"
    )
    assert (code, err) == (0, "")
    assert "SIDEKICK_WORK_UPSTREAM_ADDR=unset:1" in out.splitlines()
