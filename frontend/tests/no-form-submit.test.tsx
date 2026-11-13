import path from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { controlSv } from "@/features/control-app/labels";
import { MemoryView } from "@/features/control-app/memory-view";
import type {
  ControlTransport,
  MemoryStatus,
  RecallResult,
} from "@/features/control-app/transport";
import { onEnterKey } from "@/features/mcp-apps/ui/enter-key";
import { featuresDir, readText, sourceFiles } from "./helpers/source-files";
import { savedViewsLabelsSv } from "@/features/work-app/saved-views/saved-views-labels";
import {
  fakeTransport,
  meetings,
  openPanel,
  renderBar,
  unfoldEdit,
} from "./helpers/saved-views-fixtures";

// The host may sandbox an MCP App without `allow-forms`, and then no form ever submits. These tests
// swallow every submit event before React sees it, the way such a sandbox does, and require that Enter in
// the field and a click on the button still act.

function swallowSubmit(event: Event) {
  event.preventDefault();
  event.stopImmediatePropagation();
}

beforeEach(() => window.addEventListener("submit", swallowSubmit, true));
afterEach(() => window.removeEventListener("submit", swallowSubmit, true));

const status: MemoryStatus = {
  settings: {
    journal: true,
    contacts: false,
    projects: false,
    tasks: false,
    paused: false,
    version: 1,
  },
  provider: "hindsight",
  sources: [],
};

function memoryTransport(
  recall: (request: { query: string }) => Promise<RecallResult>,
): ControlTransport {
  return {
    trash: vi.fn(),
    restore: vi.fn(),
    changes: vi.fn(),
    undoPurchase: vi.fn(),
    memoryStatus: vi.fn(() => Promise.resolve(status)),
    setMemory: vi.fn(),
    activity: vi.fn(),
    recall,
    forget: vi.fn(),
  };
}

const nothing: RecallResult = { status: "ok", facts: [], truncated: false };

describe("Memory search without form submission", () => {
  it("asks recall_memory on Enter in the field", async () => {
    const recall = vi.fn(() => Promise.resolve(nothing));
    render(
      <MemoryView
        initial={status}
        transport={memoryTransport(recall)}
        labels={controlSv}
      />,
    );
    const search = within(screen.getByRole("search"));
    await userEvent.type(search.getByRole("searchbox"), "promenad{Enter}");
    expect(recall).toHaveBeenCalledWith({ query: "promenad" });
  });

  it("asks recall_memory on the Search button, which is not a submit button", async () => {
    const recall = vi.fn(() => Promise.resolve(nothing));
    render(
      <MemoryView
        initial={status}
        transport={memoryTransport(recall)}
        labels={controlSv}
      />,
    );
    const search = within(screen.getByRole("search"));
    await userEvent.type(search.getByRole("searchbox"), "hund");
    const button = search.getByRole("button", { name: controlSv.searchButton });
    expect(button).toHaveAttribute("type", "button");
    await userEvent.click(button);
    expect(recall).toHaveBeenCalledWith({ query: "hund" });
  });

  it("shows the too-short notice on Enter", async () => {
    const recall = vi.fn(() => Promise.resolve(nothing));
    render(
      <MemoryView
        initial={status}
        transport={memoryTransport(recall)}
        labels={controlSv}
      />,
    );
    await userEvent.type(screen.getByRole("searchbox"), "a{Enter}");
    expect(screen.getByRole("alert")).toHaveTextContent(
      controlSv.searchTooShort,
    );
    expect(recall).not.toHaveBeenCalled();
  });
});

describe("Saved views without form submission", () => {
  it("saves the current view on Enter in the name field", async () => {
    const fake = fakeTransport([meetings]);
    fake.createSavedWorkView.mockResolvedValue({
      saved_view: { ...meetings, id: "v-new", name: "Mina" },
    });
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });
    await openPanel(user);
    await screen.findByText("Möten");
    await user.type(
      screen.getByLabelText(savedViewsLabelsSv.nameLabel),
      "Mina{Enter}",
    );
    expect(fake.createSavedWorkView).toHaveBeenCalledWith(
      "Mina",
      expect.anything(),
      expect.any(String),
    );
  });

  it("renames a view on Enter and on Save", async () => {
    const fake = fakeTransport([meetings]);
    fake.updateSavedWorkView.mockResolvedValue({
      saved_view: { ...meetings, name: "Veckomöten", version: 3 },
    });
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });
    await openPanel(user);
    await unfoldEdit(user, "Möten");
    await user.click(screen.getByRole("button", { name: "Byt namn: Möten" }));
    const edit = screen.getByRole("form", { name: "Byt namn: Möten" });
    const input = within(edit).getByRole("textbox");
    await user.clear(input);
    await user.type(input, "Veckomöten{Enter}");
    expect(fake.updateSavedWorkView).toHaveBeenCalledWith(
      meetings.id,
      2,
      { name: "Veckomöten" },
      expect.any(String),
    );
  });
});

describe("onEnterKey", () => {
  function field(action: () => void) {
    render(
      <input aria-label="f" onKeyDown={(event) => onEnterKey(event, action)} />,
    );
    return screen.getByLabelText("f");
  }

  it("runs on a plain Enter and ignores other keys, modified Enter and IME composition", () => {
    const action = vi.fn();
    const input = field(action);
    fireEvent.keyDown(input, { key: "a" });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(action).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(action).toHaveBeenCalledTimes(1);
  });
});

describe("Every form in the MCP apps", () => {
  it("acts without submission: a form's onSubmit only prevents navigation", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(
      featuresDir,
      (name) => name.endsWith(".tsx") && !name.includes(".test."),
    )) {
      const text = readText(file);
      for (const match of text.matchAll(/<form\b[^>]*?onSubmit=\{([^}]*)/gs)) {
        if (match[1]?.trim() !== "preventSubmit")
          offenders.push(path.relative(featuresDir, file));
      }
    }
    expect(offenders).toEqual([]);
  });
});
