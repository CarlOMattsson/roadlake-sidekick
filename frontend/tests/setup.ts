import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

/*
 * `findBy*` and `waitFor` have their own budget, independent of Vitest's `testTimeout`,
 * and it defaults to one second.
 *
 * That is the tighter of the two limits here and the one that actually bites: a test that
 * renders a whole room and then waits for a tool call to resolve is waiting on real
 * microtask and timer scheduling, which on a loaded machine takes longer than a second
 * while the test as a whole is still nowhere near its own timeout. Measured on this
 * machine, that produced a failure that never reproduced in isolation — eight consecutive
 * isolated runs passed — and only appeared in a full parallel run.
 *
 * Raising it costs a passing run nothing: the budget is a ceiling on how long a query may
 * take before it is called a failure, not a delay. A selector that never matches still
 * fails, and still reports the same "unable to find role" message.
 */
configure({ asyncUtilTimeout: 15_000 });

/* jsdom lacks the observers and media query API the primitives rely on. */
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
/**
 * Component tests run in the reduced-motion branch by default: they assert what
 * the interface says, not how it moves, and the reduced branch is the one that
 * must always keep every control and value present. The motion branch has its
 * own test that overrides this.
 */
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

/**
 * The router is a module singleton, so a tree left mounted by an earlier test would
 * keep re-rendering on the next navigation and duplicate every landmark.
 */
afterEach(() => {
  cleanup();
  localStorage.clear();
});
