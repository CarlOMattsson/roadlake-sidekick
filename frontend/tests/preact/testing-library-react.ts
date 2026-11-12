/**
 * A minimal stand-in for `@testing-library/react` when the MCP App tests run on Preact
 * (vitest.mcp-app-preact.config.ts aliases the package to this file).
 *
 * Why: the real package is CommonJS and requires `react-dom` natively, so the Preact aliases never reach it and it
 * would render with React. This module offers the subset the tests use (`render`, `cleanup`, `act`, plus everything
 * `@testing-library/dom` exports) on top of `preact/compat`, which is what the shipped bundle renders with.
 */
import { configure, getQueriesForElement } from "@testing-library/dom";
import type { ReactElement } from "react";
import { act as preactAct } from "preact/test-utils";
import { render as preactRender } from "preact";

export * from "@testing-library/dom";

// Preact's act flushes a synchronous callback synchronously, as React's does.
export const act = preactAct;

// Same wiring as the real package: DOM events and async waits run inside act so Preact flushes its updates.
configure({
  eventWrapper: (callback) => {
    let value: unknown;
    void preactAct(() => {
      value = callback();
    });
    return value as never;
  },
  // Like the real package, let queued renders settle after an async user action (user-event, waitFor).
  asyncWrapper: async (callback) => {
    try {
      return (await callback()) as never;
    } finally {
      await preactAct(async () => {});
    }
  },
});

const mounted = new Set<{ container: HTMLElement }>();

export function render(ui: ReactElement) {
  const container = document.body.appendChild(document.createElement("div"));
  const entry = { container };
  mounted.add(entry);
  void preactAct(() => {
    preactRender(ui as never, container);
  });
  return {
    container,
    rerender: (next: ReactElement) =>
      void preactAct(() => {
        preactRender(next as never, container);
      }),
    unmount: () =>
      void preactAct(() => {
        preactRender(null, container);
      }),
    ...getQueriesForElement(container),
  };
}

export function cleanup() {
  for (const { container } of mounted) {
    void preactAct(() => {
      preactRender(null, container);
    });
    container.remove();
  }
  mounted.clear();
}
