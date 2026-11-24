# Building Sidekick with AI agents

[Svenska](ai-native-development.sv.md)

<!-- description: How Sidekick is developed: one person directs the product, architecture and quality bar, AI coding agents write the code, and checks and daily use test it. -->

Sidekick is developed and maintained by one person, Carl O Mattsson, and its application code is written by AI coding agents. This page explains how that works, which checks stand behind a change, and where the method is still hard.

The page is about the agents that build Sidekick. The AI you use in Sidekick is something else: Claude on your own subscription, and the optional features that call a model with your own key ([AI costs](ai-costs.md)).

## The development model

Carl does not write Sidekick's application code. The work is done in Claude Code. A main session plans the work and hands it to coding agents on models chosen by difficulty: fast models search the code, run tests and update documentation, and stronger models write code, do design work and handle the parts that touch security. A separate agent reviews changes that are close to security, and the test suites are run together on the integrated branch before anything is pushed.

Writing no code by hand is not the same as doing no technical work. Someone has to know how the system fits together, choose between trade-offs and judge whether the behaviour is right. That part stays with the maintainer.

Carl reports that the private development history holds more than 10,000 commits, and that the public repository is an exported subset of it. The figure is his own, and it says nothing about quality.

## Direction and implementation

The maintainer decides what Sidekick should do and how it should behave, at the level a user notices. Two examples: an AI plan is approved by the owner in the app, never by the model, and safe suggestions are approved at most three at a time, with undo. How such a requirement becomes components, style rules and database queries is left to the agents.

Delegating in this way differs from accepting whatever comes back. A requirement arrives with constraints, the result is tried in real use, and when it falls short it goes back with more precise direction. Decisions about the product, the price, publishing and the license are made by the maintainer, and the agents prepare the material. Which capabilities exist, and how they work together, is not the agents' call.

## Architecture and written rules

An agent starts a task with no memory of the previous one. What carries over is what is written in the repository, so the rules are kept there.

- **[AGENTS.md](../../AGENTS.md)** holds the architecture rules for anyone who changes the code, person or agent. The central one: the MCP tools for Claude and the routes for the Android app call the same application use cases, so a rule about ownership or permissions is written once ([How the parts fit together](overview.md)).
- **[The decision log](../decisions/log.md)** numbers the product decisions that hold today, and the code refers to them by number. Larger technical decisions are architecture decision records, such as [ADR-011](../decisions/adr/ADR-011-ai-delegated-steps.md).
- **The backend's layers** are described and tested ([Backend layering](architecture/backend.md)). Tests read the imports and fail when an interface module reaches straight into the database layer.
- **The frontend's lint rules** stop one room's folder from importing another room's files, keep a source file under 500 lines, and require user-visible text to come from the label files.

Where older code breaks a rule, the file is listed by name as an exception, and the lists may only shrink.

## Verification

**Configured.** The repository has strict type checking for Python and TypeScript, linting and formatting, tests for the backend, the frontend and the Android app, and browser tests of the rooms in a simulated host. Policy tests cover the architecture and the migrations, snapshots of the MCP tool contracts must match the code, and the history is scanned for secrets ([development guide](../contribute/development.md)).

**Run.** Before a push, `tools/check-all.sh` runs these stages locally. In the public repository, CI runs on every push to `main`, with coverage thresholds, and CodeQL analyses each push. A release adds a dependency audit, a vulnerability scan of the container image, and a drill that installs, updates, backs up and restores an installation in disposable containers. The image and the Android APK are then signed, and anyone can check the signatures ([Verifying a release](../maintainers/release.md#verifying-a-release)).

**Verified.** Sidekick is in daily use with Claude, with the Android app on a real phone, and on Linux. macOS has not been tried.

None of this makes AI-written code secure or correct in itself. The checks catch classes of error, such as a type that does not fit, a crossed boundary or a leaked secret. They cannot say whether a feature does what a person needs, and not every line is read by a human.

## One change from start to finish

A typical change starts with a problem or a wanted capability, stated with its constraints. Agents read the existing code and implement the change. The checks run, the result is tried in real use, and new direction follows until it is acceptable. Then it is documented and released.

[Issue #53](https://github.com/CarlOMattsson/roadlake-sidekick/issues/53) shows this on a real case. It concerns AI steps ([issue #26](https://github.com/CarlOMattsson/roadlake-sidekick/issues/26)), where Claude drafts a plan and the owner approves it in the app.

1. **A report from real use.** Carl pressed Approve plan in the app view in a Claude desktop client and got a permission error.
2. **A first fix.** A suspected cause was removed, and the status note said that the fix had not been verified in a real host.
3. **A test in a real host.** The error remained. The server logs showed why: the host dropped the mark that the app puts on its calls, and the server relied on that mark to tell the app from the model.
4. **A new design.** A token passed as an ordinary argument would not be enough, because the model could fetch it too. The server now hands the app a signed, single-use decision ticket in metadata that the model is not shown. The same ticket covers automations and groups of suggestions ([issue #40](https://github.com/CarlOMattsson/roadlake-sidekick/issues/40)).
5. **Back to real use.** The change was implemented, reviewed and merged. When this was written the issue was still open: the design does not count as verified until it has worked in the host where the error was found.

The first fix reached `main`, and the error was still there. It was found because a person used the feature.

## What it makes possible, and what stays hard

One person can keep a backend, the rooms inside Claude, an Android app and documentation in two languages moving at once. An idea can be tried as working software soon after it is described, and a second approach when the first one fails.

The hard parts are these:

- **Consistency.** Agents follow the patterns they can see. A rule that exists only in someone's head is not followed.
- **Regressions and complexity.** The suites catch only what someone thought to test. Code is cheap to produce, so it accumulates, and the system is larger than one person can reread. The size limits and the shrinking exception lists push back.
- **Results that only look right.** A change can pass every check and still not work for the person using it. Finding that out takes the maintainer's time.

## Who is behind it

Carl O Mattsson created Sidekick and maintains it. His part covers the product direction, the architecture, the interaction design, the requirements and the judgement of quality. He is responsible for what is released.

## An ongoing experiment

Sidekick is a product first. It is also a practical test of how much coherent, usable software one person can build and maintain when AI agents do the implementation under human direction.

The project is source available, not open source ([License, license key and price](licensing.md)), so the code, the rules, the checks and the issues are there to read. This page does not claim that the method suits every project or replaces a team. It describes what has worked here so far, and what has not.
