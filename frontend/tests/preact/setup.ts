/**
 * Extra setup for the Preact run (vitest.mcp-app-preact.config.ts), after tests/setup.ts.
 *
 * Preact's hooks flush effects "after the next paint" with a 35 ms timeout that also holds a
 * requestAnimationFrame handle, and the timeout calls `cancelAnimationFrame` when it fires. A render that
 * finishes outside `act` right at the end of a file can leave that timeout pending past the jsdom teardown, where
 * `cancelAnimationFrame` is gone ("cancelAnimationFrame is not defined"). Scheduling the flush with a plain
 * zero-delay timeout and draining one turn after the file's last test leaves nothing pending at teardown.
 * `act` still takes over the hook while a test drives the tree, as before.
 */
import { options } from "preact";
import { afterAll } from "vitest";

options.requestAnimationFrame = (callback) => {
  setTimeout(callback, 0);
};

afterAll(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));
