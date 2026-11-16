"""The attributes the AI runner puts on its telemetry survive the port; any content does not."""

from sidekick.shared.observability import safe_telemetry_attributes


def test_the_closed_values_the_ai_runner_emits_are_kept() -> None:
    emitted = {
        "ai.model": "claude-opus-5-5",
        "ai.runner": "server",
        "cap": "month",
        "kind": "lapsed",
        "outcome": "failed",
    }

    assert safe_telemetry_attributes(emitted) == emitted


def test_content_next_to_them_is_dropped() -> None:
    kept = safe_telemetry_attributes({"cap": "task", "prompt": "Call Anna about her tooth"})

    assert kept == {"cap": "task"}
