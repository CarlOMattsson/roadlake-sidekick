import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

/*
 * `findBy*` and `waitFor` have their own budget, independent of Vitest's `testTimeout`, and it defaults to one
 * second. A test that renders a whole room and then waits for a tool call to resolve is waiting on real microtask
 * and timer scheduling, which on a loaded machine takes longer than a second while the test as a whole is still
 * nowhere near its own timeout. Five seconds covers that: the slowest whole test in a full run takes about nine
 * seconds on a busy machine, so no single query comes near it. A selector that never matches still fails with the
 * same "unable to find role" message, only sooner than it would at fifteen seconds.
 */
configure({ asyncUtilTimeout: 5_000 });

/* jsdom lacks the observers and media query API the primitives rely on. */
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
/**
 * Component tests run in the reduced-motion branch by default: they assert what
 * the interface says, not how it moves, and the reduced branch is the one that
 * must always keep every control and value present. The motion branch has its
 * own test that overrides this.
 */
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string) => ({
    matches: query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  });
}

/**
 * The router is a module singleton, so a tree left mounted by an earlier test would
 * keep re-rendering on the next navigation and duplicate every landmark.
 */
afterEach(() => {
  cleanup();
  localStorage.clear();
});
