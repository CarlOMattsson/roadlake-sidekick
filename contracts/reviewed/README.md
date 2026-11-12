# Reviewed contract baselines

These are the accepted contract artifacts of the Project and Task, Contacts and Journal features and the restored Work feature. They are
never rewritten. What they promise must still hold: every reviewed operation and tool has to exist with
the same identity, shape, annotations, and accepted inputs. Later features add fields and routes on
purpose, so an addition is not a violation while removing or reshaping something reviewed is.

The gate that reads them is `backend/tests/contract/test_reviewed_contracts.py`, with
`test_work_contracts.py` covering the Work fixtures. It compares the reviewed **MCP tool** baselines of
the project-task, contacts and journal features with the running server. `hindsight-memory/` describes the
Hindsight memory settings.

`contracts/openapi.generated.json` and `contracts/mcp-tools.generated.json` one directory up are a
different thing: they are the single snapshot of the *current* surface, regenerated deliberately and
compared literally by `test_generated_contracts.py`. Nothing in this directory is regenerated.

Two reviewed promises are deliberately superseded and are named in the gate itself rather than edited
away here.
