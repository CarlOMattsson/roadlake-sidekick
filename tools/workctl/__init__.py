"""workctl: the logic of ``tools/work.sh`` (Sidekick Work, the isolated work-laptop package) in testable Python.

Why this exists
---------------
``tools/work.sh`` grew to ~2 400 lines of bash that mixes orchestration (docker compose calls, waiting, traps,
locks) with logic that is easy to get wrong and hard to test in shell: address parsing, escaping, secret
generation, file rendering. The logic moves here, step by step, and ``work.sh`` stays a thin shell that calls
``workctl`` for it. Behaviour, flags, output and exit codes of ``work.sh`` do not change.

Constraints
-----------
* The package runs with the system ``python3`` on the user's computer *before* the backend's virtual
  environment exists: standard library only, and syntax that works on Python 3.9 (the ``python3`` of a stock
  macOS), so no ``match``, no ``X | Y`` outside annotations, ``from __future__ import annotations`` everywhere.
* Called as ``PYTHONPATH=tools python3 -m workctl <command> ...`` (``work.sh`` has a ``workctl`` function for
  it). Inside the package only relative imports are used, so the tests can import it as ``tools.workctl``.
* A secret never travels on a command line: values that are secrets are read from stdin, and secret files are
  created with mode 600 from the start.

Module plan (inventory of ``work.sh`` and where each part stands)
-----------------------------------------------------------------
Moved:

* ``addresses``  : ``parse_base_url`` and ``parse_allowlist`` (model server URL and allowlist validation).
* ``autostart``  : ``xml_escape``, ``systemd_quote`` and the launchd plist / systemd unit text.
* ``secretfiles``: ``generate_secrets``, ``set_line``/``drop_line`` and ``apply_model_key``
  (the 600 files in ``deploy/work/secrets/``).
* ``generated``  : the gateway HAProxy configuration, the allowlist compose override and ``build-info.json``.
* ``desktopconfig``: the Claude Desktop entry file ``start`` writes, the guarded merge into the user's own
  file (``claude-config``) and the model id list of a ``/models`` answer.
* ``messages``   : the message table (``messages.json``, sv/en) behind ``msg``/``say``/``sayf``/``errf``.
* ``workenv``    : one value of ``work.env`` (``envval``) and the memory switch (``memory_wanted``).
* ``derive``     : work.env to the exported ``SIDEKICK_WORK_*`` variables, the allowlist and the trust store.
* ``status``     : the version line and the translation of the gateway probe in ``status``;
  ``probe_egress`` and ``probe_gateway`` are the two scripts ``status`` runs *inside* the containers
  (passed to ``python -c``, so each is a plain file with a ``__main__`` guard).
* ``diagnose``   : the decisions of the hint after a failed first start (log evidence, table state, volume
  name); ``work.sh`` only gathers the logs and runs the read-only queries.
* ``backupfiles``: the number of sets kept, the free-space check, the time stamp of a new set and the pruning of old
  ones; also used by ``deploy/selfhost/update.sh`` and ``tools/db-backup.sh``.
* ``restore``    : the complete backup sets of a directory, what a typed ``restore`` argument names and what
  undoing a half-done database swap has to do.
* ``updatestate``: the state files of ``deploy/selfhost/update.sh``: the atomic journal entry, the release pointer
  and its restore after a rollback, the lock owner and the snapshot name with the regex for its finished form.
  Reading the journal and the pointer stays in ``update.sh`` (``--check`` and the dry run run without python3).
* ``drilltimings``: the table of step durations of ``tools/drill.sh`` (plain text and the Markdown job summary).
* ``drillpolicy``: the other checks of ``tools/drill.sh``: the extra reserved ports, the image pair, the free port,
  the digest of a push and the versions of a release.
* ``prompts``    : the guide's questions (read one line, hidden input, defaults), yes answers and numbered choices.
* ``owner``      : the UUID check for the user Claude Desktop acts as.
* ``setupguide`` : the questions of ``setup`` (memory, model server and key, memory model, allowlist, rooms, app
  language) and the writing of the answers; the shell keeps the tool checks, the first-run secrets, autostart and start.

* ``invocation`` : the options of start, update and restore (a refused call is a usage error), the name a command
  takes the lock under and the image the stack runs from.
* ``stackstate`` : the tag that keeps the previous image and the name of the database a restore sets aside (whether a
  container is or may become active is ``deploy/selfhost/update_policy.py``, shared with the updater).

Still in ``work.sh`` (candidates to move next, in order of value):

1. Backup, restore and update orchestration (docker, traps, locks, pause/resume of writers): thin shell
   around compose calls, last to move; its decision pieces have moved (``backupfiles``, ``restore``, ``backupkey``).
"""
