"""The model list of tools/workctl: bearer key, no redirects, bad answers refused."""

import http.server
import io
import json
import threading
from collections.abc import Iterator
from typing import ClassVar

import pytest
from tools.workctl import cli, modelserver

KEY = "test-key-123"


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        _Handler.seen.append(self.headers.get("Authorization", ""))
        if self.path == "/v1/models":
            if self.headers.get("Authorization") not in (None, f"Bearer {KEY}"):
                self.send_error(401)
                return
            self._reply(json.dumps({"data": [{"id": "glm-x"}, {"id": "flash-y"}]}))
        elif self.path == "/redirect/models":
            self.send_response(302)
            self.send_header("Location", "/v1/models")
            self.end_headers()
        elif self.path == "/html/models":
            self._reply("<html>")
        else:
            self.send_error(404)

    def _reply(self, text: str) -> None:
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture(name="server")
def _server() -> Iterator[str]:
    _Handler.seen = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_parse_model_ids_returns_the_ids_in_order() -> None:
    body = json.dumps({"data": [{"id": "a"}, {"id": "b/c"}, {"object": "x"}, "text"]})
    assert modelserver.parse_model_ids(body) == ["a", "b/c"]


def test_parse_model_ids_without_data_is_empty() -> None:
    assert modelserver.parse_model_ids("{}") == []


@pytest.mark.parametrize("body", ["", "not json", "[]", '{"data": 5}', "null"])
def test_parse_model_ids_rejects_something_that_is_not_a_model_list(body: str) -> None:
    with pytest.raises(ValueError):
        modelserver.parse_model_ids(body)


def test_fetch_sends_the_key_as_a_bearer_token(server: str) -> None:
    assert modelserver.fetch_model_ids(f"{server}/v1", KEY) == ["glm-x", "flash-y"]
    assert _Handler.seen == [f"Bearer {KEY}"]


def test_fetch_without_a_key_sends_no_authorization_header(server: str) -> None:
    assert modelserver.fetch_model_ids(f"{server}/v1", "") == ["glm-x", "flash-y"]
    assert _Handler.seen == [""]


def test_fetch_with_the_wrong_key_fails(server: str) -> None:
    with pytest.raises(ValueError):
        modelserver.fetch_model_ids(f"{server}/v1", "wrong")


@pytest.mark.parametrize("base", ["/missing", "/redirect", "/html"])
def test_fetch_fails_for_an_error_a_redirect_or_a_page_that_is_no_model_list(
    server: str, base: str
) -> None:
    with pytest.raises(ValueError):
        modelserver.fetch_model_ids(f"{server}{base}", KEY)


def test_fetch_refuses_an_address_that_is_not_http() -> None:
    with pytest.raises(ValueError):
        modelserver.fetch_model_ids("file:///etc", KEY)


def test_fetch_fails_when_nobody_listens() -> None:
    with pytest.raises(ValueError):
        modelserver.fetch_model_ids("http://127.0.0.1:1/v1", KEY)


def test_the_models_list_command_reads_the_key_from_stdin(
    server: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(KEY))
    assert cli.main(["models-list", "--base-url", f"{server}/v1"]) == 0
    assert capsys.readouterr().out == "glm-x\nflash-y\n"


def test_the_models_list_command_exits_1_and_prints_nothing_on_failure(
    server: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("wrong"))
    assert cli.main(["models-list", "--base-url", f"{server}/v1"]) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")
