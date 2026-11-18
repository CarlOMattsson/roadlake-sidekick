"""The model-visible MCP tool list stays inside a fixed context budget.

Every tool a host shows the model costs its name, description and inputSchema in the model's
context. The cost is estimated from the reviewed snapshot as characters divided by 3.5, the same
rough estimate used when the budget was set. App-only tools (`_meta.ui.visibility == ["app"]`)
are not shown to the model and are not counted. The ceiling is a guard against silent growth,
not a target: raise it only with a reviewed reason in the same change.

The outputSchema is deliberately NOT part of that token budget. The budget counts what every host
is certain to put in the model's context (name, description, inputSchema); a host may or may not
forward an outputSchema, and the model-visible ones are ~170 000 characters (~48 700 tokens by the
same estimate), several times the whole budget. Mixing them would hide growth in the part we
control. So the outputSchema of the model-visible tools has its own ceiling (OUTPUT_SCHEMA_CHAR_CAP,
the measured size plus 5 %), which makes growth of what a host that does load it would pay a
reviewed decision too. Revisit by trimming schemas, not by raising the cap, when a host is known to
load them.

On failure the report lists every tool with its character counts for description, inputSchema
and outputSchema.
"""

import json

from tests.contract_counts import MCP_TOOLS_SNAPSHOT, app_only_tool_names

CHARS_PER_TOKEN = 3.5
# The budget covers the model-visible tools only, including the memory controls the owner must
# be able to reach by voice. A change to it is a reviewed decision, as the module docstring says.
# 2026-11-11: raised from 18 600 for `update_task`'s `recurrence` rule (the rule's own schema, about
# 130 tokens, so the owner can ask for "every week" on a Task) and the Process filter of
# `get_work_hierarchy`; measured 18 723, rounded up.
# 2026-11-11: raised to 18 850 for the 8-to-128-character bound on the `idempotency_key` of the five
# model-visible Contact write tools (about 54 tokens in all), the bound every other write tool has;
# measured 18 804, rounded up.
# 2026-11-13: raised to 19 350 for the owner's tags on Contacts and Journal entries: a `tags` input
# on `create_contact`, `update_contact`, `write_journal_entry` and `update_journal_entry`, and a
# `tags` and `tag_match` filter on `list_contacts` and `list_journal_entries` (about 450 tokens in
# all); measured 19 305, rounded up.
# 2026-11-13: raised to 19 450 for project progress (`tasks_total`, `tasks_done`) in
# `get_contact_context`, `changes.status` on `update_step_action` to reopen an Action, and the
# `order` of `list_journal_entries` (about 90 tokens in all); measured 19 392, rounded up.
# 2026-11-15: raised to 19 900 for going through many Tasks by voice: `get_review_queue` and
# `review_tasks` (about 445 tokens together, descriptions already shortened); measured 19 870,
# rounded up.
# 2026-11-15: raised to 20 050 for `restore_task`, the undo of archive (also of a review's
# archive), about 145 tokens; measured 20 015, rounded up. The owner allows up to 25 000 for this
# work; only what is measured is taken.
# 2026-11-15: raised to 20 150 for Ambitions (`changes.ambition` on `update_task`, the `ambitions`
# filter on `list_tasks`, the `ambition` review decision), about 90 tokens; measured 20 106,
# rounded up. No new tool and no new output field.
# 2026-11-16: raised to 22 600 for the seven model-visible AI Step tools (`set_ai_plan`,
# `get_ai_plan`, `list_ai_steps`, `start_ai_step`, `report_ai_step_result`,
# `review_ai_step_result`, `get_ai_step_run`) and `ai_possible` on `update_task`, about 2 400
# tokens, of which the plan's spec schema is about 700; measured 22 536, rounded up.
# `approve_ai_plan` is app-only and costs nothing here.
# 2026-11-16: raised to 23 350 for the `clear` parameter of the eight update tools (task, project,
# domain, process, step, action, contact, shopping item): a closed list of the fields that can be
# emptied, replacing null as the way to clear them, about 710 tokens in all; measured 23 313,
# rounded up.
# 2026-11-18: raised to 23 400 for `list_id` in the item of `update_shopping_item`
# (moving an item to another list), about 80 tokens; measured 23 394, rounded up.
TOKEN_BUDGET = 23_400
LARGEST_LISTED = 5
# Measured 2026-10-25: the longest model-visible description is 527 chars, rounded up to 50.
DESCRIPTION_CHAR_CAP = 550
# Measured 2026-11-11: the 70 model-visible tools carry 170 527 characters of outputSchema; the cap
# is that plus 5 % (rounded up). App-only tools are not counted, as for the token budget.
# 2026-11-16: raised to 221 100 for the outputs of the AI Step tools (the plan, a step page, a
# started step and a run, 30 000 characters together); measured 210 488, plus 5 %.
OUTPUT_SCHEMA_CHAR_CAP = 221_100


def _estimated_tokens(tool: dict[str, object]) -> float:
    text = (
        str(tool["name"]) + str(tool.get("description") or "") + json.dumps(tool.get("inputSchema"))
    )
    return len(text) / CHARS_PER_TOKEN


def _description_chars(tool: dict[str, object]) -> int:
    return len(str(tool.get("description") or ""))


def _schema_chars(schema: object) -> int:
    return 0 if schema is None else len(json.dumps(schema))


def _per_tool_report(tools: list[dict[str, object]], app_only: frozenset[str]) -> str:
    lines = []
    for tool in tools:
        name = str(tool["name"])
        marker = " [app-only]" if name in app_only else ""
        lines.append(
            f"  {name}{marker}: description={_description_chars(tool)}, "
            f"inputSchema={_schema_chars(tool.get('inputSchema'))}, "
            f"outputSchema={_schema_chars(tool.get('outputSchema'))}"
        )
    return "\n".join(lines)


def test_model_visible_tool_context_stays_within_budget() -> None:
    tools = json.loads(MCP_TOOLS_SNAPSHOT.read_text(encoding="utf-8"))
    app_only = app_only_tool_names()
    visible = [tool for tool in tools if tool["name"] not in app_only]
    costs = {str(tool["name"]): _estimated_tokens(tool) for tool in visible}
    total = sum(costs.values())
    largest = sorted(costs.items(), key=lambda item: item[1], reverse=True)[:LARGEST_LISTED]
    largest_text = ", ".join(f"{name} (~{round(cost)})" for name, cost in largest)
    longest_description = max(_description_chars(tool) for tool in visible)
    output_schema_total = sum(_schema_chars(tool.get("outputSchema")) for tool in visible)
    report = (
        "per-tool characters (all tools):\n"
        f"{_per_tool_report(tools, app_only)}\n"
        f"longest model-visible description: {longest_description} chars "
        f"(cap {DESCRIPTION_CHAR_CAP})\n"
        f"outputSchema total, model-visible tools: {output_schema_total} chars "
        f"(cap {OUTPUT_SCHEMA_CHAR_CAP})"
    )
    print(report)
    assert total <= TOKEN_BUDGET, (
        f"model-visible MCP tools cost ~{round(total)} tokens, over the {TOKEN_BUDGET} budget. "
        f"Largest: {largest_text}. Shorten descriptions or schemas, or make a tool app-only "
        f"if the model does not need it.\n{report}"
    )
    assert longest_description <= DESCRIPTION_CHAR_CAP, (
        f"longest model-visible tool description is {longest_description} chars, over the "
        f"{DESCRIPTION_CHAR_CAP} cap. Shorten it or raise the cap with a reviewed reason.\n{report}"
    )
    assert output_schema_total <= OUTPUT_SCHEMA_CHAR_CAP, (
        f"outputSchema of the model-visible tools is {output_schema_total} chars, over the "
        f"{OUTPUT_SCHEMA_CHAR_CAP} cap. Trim the schemas or raise the cap with a reviewed reason."
        f"\n{report}"
    )
