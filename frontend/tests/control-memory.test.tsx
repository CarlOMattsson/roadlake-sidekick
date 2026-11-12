import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { controlEn, controlSv } from "@/features/control-app/labels";
import { MemoryView } from "@/features/control-app/memory-view";
import type {
  ControlTransport,
  MemoryStatus,
  SetMemoryResult,
} from "@/features/control-app/transport";

/** A row's meta line, matched on its whole text: each "·" part is a span of its own. */
const metaLine = (text: string) => (_: string, el: Element | null) =>
  !!el?.classList.contains("control-row-secondary") && el.textContent === text;

/** An error as the app client throws it: only the closed code is read by the view. */
function fail(code: string): Error {
  return Object.assign(new Error(code), { code });
}

const settings = {
  journal: true,
  contacts: false,
  projects: true,
  tasks: false,
  paused: false,
  version: 4,
};
const status: MemoryStatus = {
  settings,
  provider: "hindsight",
  sources: [
    {
      kind: "journal_entry",
      retained: 12,
      pending: 2,
      failed: 0,
      parked: 0,
      excluded: 0,
    },
    {
      kind: "project",
      retained: 1,
      pending: 0,
      failed: 1,
      parked: 0,
      excluded: 0,
    },
  ],
};

function makeTransport(
  setMemory: ControlTransport["setMemory"],
  after: MemoryStatus = status,
): ControlTransport {
  return {
    trash: vi.fn(),
    restore: vi.fn(),
    changes: vi.fn(),
    undoPurchase: vi.fn(),
    memoryStatus: vi.fn(() => Promise.resolve(after)),
    setMemory,
    activity: vi.fn(),
  };
}

const needsConfirmation = (documents: number | null): SetMemoryResult => ({
  status: "needs_confirmation",
  settings,
  turning_off: [{ domain: "journal", documents }],
});

describe("MemoryView status", () => {
  it("draws each domain as a switch with a track and a knob and no visible On/Off text; the state leads the meta line", () => {
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    const on = screen.getByRole("switch", { name: "Dagbok: på" });
    const off = screen.getByRole("switch", { name: "Kontakter: av" });

    expect(on).toHaveAttribute("aria-checked", "true");
    expect(off).toHaveAttribute("aria-checked", "false");
    for (const element of [on, off]) {
      expect(element.querySelector(".control-switch-track")).not.toBeNull();
      expect(element.querySelector(".control-switch-knob")).not.toBeNull();
    }
    // The switch has no word of its own: its name is the aria-label, its visible content is the track alone.
    for (const element of [on, off]) {
      expect(element.querySelector(".control-switch-label")).toBeNull();
      expect(element.textContent).toBe("");
      expect(element.querySelector(".control-switch-track")).toHaveAttribute(
        "aria-hidden",
        "true",
      );
    }
    // The mode is the first word of the row's meta line instead.
    const metaOf = (element: HTMLElement) =>
      element.closest("li")?.querySelector(".control-row-secondary")
        ?.textContent ?? "";
    expect(metaOf(on)).toMatch(/^På · /);
    expect(metaOf(off)).toBe("Av · inte med i minnet");
  });

  it("says on, shows counts per domain and one visible switch each", () => {
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Minnet är på" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(metaLine("På · 12 anteckningar i minnet · 2 på väg")),
    ).toBeVisible();
    expect(
      screen.getByText(
        metaLine("På · 1 projekt i minnet · 1 väntar på minnet"),
      ),
    ).toBeVisible();
    // Both domains that are off say so; neither shows a count.
    expect(
      screen.getAllByText(metaLine("Av · inte med i minnet")),
    ).toHaveLength(2);
    expect(screen.getByRole("switch", { name: "Dagbok: på" })).toBeChecked();
    expect(
      screen.getByRole("switch", { name: "Kontakter: av" }),
    ).not.toBeChecked();
  });

  it("an on domain without a count says the count is unknown", () => {
    render(
      <MemoryView
        initial={{ ...status, sources: [] }}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    // Journal and projects are on but have no count; contacts and tasks are off.
    expect(screen.getAllByText(metaLine("På · Antal okänt"))).toHaveLength(2);
    expect(
      screen.getAllByText(metaLine("Av · inte med i minnet")),
    ).toHaveLength(2);
    expect(screen.queryByText("inget antal")).toBeNull();
  });

  it("a paused memory dims the domain rows and says paused on the on switches", () => {
    render(
      <MemoryView
        initial={{ ...status, settings: { ...settings, paused: true } }}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    expect(screen.getByRole("list", { name: "Sidekicks minne" })).toHaveClass(
      "control-list-paused",
    );
    // The switches carry no text; the paused mode leads the meta line of the two rows that are on.
    expect(screen.getByRole("switch", { name: "Dagbok: på" }).textContent).toBe(
      "",
    );
    expect(
      screen.getByText(
        metaLine("På · pausad · 12 anteckningar i minnet · 2 på väg"),
      ),
    ).toBeVisible();
    expect(
      screen.getByText(
        metaLine("På · pausad · 1 projekt i minnet · 1 väntar på minnet"),
      ),
    ).toBeVisible();
    expect(
      screen.getAllByText(metaLine("Av · inte med i minnet")),
    ).toHaveLength(2);
    expect(screen.getByRole("switch", { name: "Dagbok: på" })).toBeChecked();
  });

  it("a running memory does not dim the rows", () => {
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    expect(
      screen.getByRole("list", { name: "Sidekicks minne" }),
    ).not.toHaveClass("control-list-paused");
    expect(
      screen.getByText(metaLine("På · 12 anteckningar i minnet · 2 på väg")),
    ).toBeVisible();
    expect(screen.queryByText(/pausad/)).toBeNull();
  });

  it("puts the headline alone in the head row, and the pause is the list's action row under it", () => {
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    const heading = screen.getByRole("heading", { name: "Minnet är på" });
    const pause = screen.getByRole("button", { name: "Pausa minnet" });
    const text = heading.parentElement as HTMLElement;
    const headrow = text.parentElement as HTMLElement;
    expect(text).toHaveClass("control-headrow-text");
    expect(headrow).toHaveClass("control-headrow");
    // The head row holds the text and nothing else: no button in it.
    expect(headrow.children).toHaveLength(1);
    expect(headrow.querySelector("button")).toBeNull();
    expect(text.querySelector("p.control-headrow-meta")).toHaveTextContent(
      "2 av 4 källor",
    );
    // The pause comes right under the head row, as an action row with a glyph, not as a button.
    expect(pause).toHaveClass("sk-action-row", "control-pause");
    expect(pause).not.toHaveClass("sk-btn--secondary");
    expect(pause).not.toHaveClass("sk-btn--compact");
    expect(headrow.nextElementSibling).toBe(pause);
    expect(pause.querySelector("svg")).not.toBeNull();
  });

  it("swaps the pause glyph and text for a play glyph and 'Återuppta minnet' while paused, and the English action row says the same", () => {
    const { unmount } = render(
      <MemoryView
        initial={{ ...status, settings: { ...settings, paused: true } }}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    const resume = screen.getByRole("button", { name: "Återuppta minnet" });
    expect(resume).toHaveClass("sk-action-row", "control-pause");
    expect(resume.querySelector("svg")).not.toBeNull();
    unmount();
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(vi.fn())}
        labels={controlEn}
      />,
    );
    const pause = screen.getByRole("button", { name: "Pause memory" });
    expect(pause).toHaveClass("sk-action-row", "control-pause");
    expect(pause.previousElementSibling).toHaveClass("control-headrow");
  });

  it("names the modes in both languages (locale parity)", () => {
    expect(controlSv.domainOn).toBe("På");
    expect(controlSv.domainOnPaused).toBe("På · pausad");
    expect(controlEn.domainOn).toBe("On");
    expect(controlEn.domainOnPaused).toBe("On · paused");
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(vi.fn())}
        labels={controlEn}
      />,
    );
    expect(
      screen.getByText(metaLine("On · 12 entries in memory · 2 on the way")),
    ).toBeVisible();
    const sw = screen.getByRole("switch", { name: "Journal: on" });
    expect(sw.textContent).toBe("");
  });

  it.each([
    [
      { ...status, settings: { ...settings, paused: true } },
      "Minnet är pausat",
    ],
    [
      {
        ...status,
        settings: { ...settings, journal: false, projects: false },
      },
      "Minnet är av",
    ],
  ])("headline %#", (given, headline) => {
    render(
      <MemoryView
        initial={given}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    expect(screen.getByRole("heading", { name: headline })).toBeVisible();
  });

  it("a provider that is off says so in the headline and a warning line", () => {
    const first = render(
      <MemoryView
        initial={{ ...status, provider: "off" }}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    const heading = screen.getByRole("heading", {
      name: "Minnet är på, men tjänsten är avstängd",
    });
    expect(heading).toBeVisible();
    expect(heading).toHaveClass("control-heading-warning");
    const note = screen.getByText(controlSv.providerOff);
    expect(note).toBeVisible();
    expect(note).toHaveClass("control-notice-warning");
    expect(note).not.toHaveClass("control-note");
    first.unmount();
  });

  it("a fake provider says it is a test service in the headline and a warning line", () => {
    render(
      <MemoryView
        initial={{ ...status, provider: "fake" }}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    const heading = screen.getByRole("heading", {
      name: "Minnet använder en testtjänst",
    });
    expect(heading).toHaveClass("control-heading-warning");
    const note = screen.getByText(controlSv.providerFake);
    expect(note).toBeVisible();
    expect(note).toHaveClass("control-notice-warning");
    expect(note).not.toHaveClass("control-note");
  });

  it("a paused memory with a provider that is off keeps the paused headline, without the warning colour", () => {
    render(
      <MemoryView
        initial={{
          ...status,
          provider: "off",
          settings: { ...settings, paused: true },
        }}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    const heading = screen.getByRole("heading", { name: "Minnet är pausat" });
    expect(heading).not.toHaveClass("control-heading-warning");
    expect(screen.getByText(controlSv.providerOff)).toHaveClass(
      "control-notice-warning",
    );
  });

  it("a healthy provider keeps the plain headline and shows no provider line", () => {
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    const heading = screen.getByRole("heading", { name: "Minnet är på" });
    expect(heading).not.toHaveClass("control-heading-warning");
    expect(screen.queryByText(controlSv.providerOff)).toBeNull();
    expect(screen.queryByText(controlSv.providerFake)).toBeNull();
  });
});

describe("MemoryView changes", () => {
  it("turning a domain ON is sent at once, without confirm", async () => {
    const user = userEvent.setup();
    const setMemory = vi.fn(() =>
      Promise.resolve<SetMemoryResult>({
        status: "updated",
        settings: { ...settings, contacts: true, version: 5 },
        turning_off: [],
      }),
    );
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(setMemory)}
        labels={controlSv}
      />,
    );
    await user.click(screen.getByRole("switch", { name: "Kontakter: av" }));
    expect(setMemory).toHaveBeenCalledTimes(1);
    expect(setMemory).toHaveBeenCalledWith({
      expectedVersion: 4,
      domain: "contacts",
      value: true,
    });
    expect(await screen.findByText(controlSv.memorySaved)).toBeVisible();
  });

  it("pause and resume send paused with the version", async () => {
    const user = userEvent.setup();
    const setMemory = vi.fn(() =>
      Promise.resolve<SetMemoryResult>({
        status: "updated",
        settings: { ...settings, paused: true, version: 5 },
        turning_off: [],
      }),
    );
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(setMemory)}
        labels={controlSv}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Pausa minnet" }));
    expect(setMemory).toHaveBeenCalledWith({
      expectedVersion: 4,
      paused: true,
    });
  });

  it("a stale version reads the status again and says so", async () => {
    const user = userEvent.setup();
    const setMemory = vi.fn(() => Promise.reject(fail("conflict")));
    const transport = makeTransport(setMemory, {
      ...status,
      settings: { ...settings, version: 9 },
    });
    render(
      <MemoryView initial={status} transport={transport} labels={controlSv} />,
    );
    await user.click(screen.getByRole("switch", { name: "Kontakter: av" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.memoryConflict,
    );
    expect(transport.memoryStatus).toHaveBeenCalledTimes(1);
  });
});

describe("MemoryView turning a domain OFF needs an explicit confirmation", () => {
  it("asks first, shows what is deleted, and sends confirm only after the button", async () => {
    const user = userEvent.setup();
    const setMemory = vi
      .fn<ControlTransport["setMemory"]>()
      .mockResolvedValueOnce(needsConfirmation(12))
      .mockResolvedValueOnce({
        status: "updated",
        settings: { ...settings, journal: false, version: 5 },
        turning_off: [{ domain: "journal", documents: 12 }],
      });
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(setMemory)}
        labels={controlSv}
      />,
    );

    await user.click(screen.getByRole("switch", { name: "Dagbok: på" }));

    // Step 1: the host answered needs_confirmation; nothing was confirmed.
    expect(setMemory).toHaveBeenCalledTimes(1);
    expect(setMemory).toHaveBeenLastCalledWith({
      expectedVersion: 4,
      domain: "journal",
      value: false,
    });
    const question = screen.getByRole("group", { name: "Slå av dagboken?" });
    expect(question).toHaveTextContent(
      "Bara Sidekicks minne av dagboken raderas (12 poster). Dagboken ändras inte.",
    );
    expect(question).toHaveTextContent(
      "Vill du ha minnet tillbaka måste det byggas upp igen.",
    );
    expect(question).toHaveFocus();
    // The other controls wait while the question is open.
    expect(
      screen.getByRole("switch", { name: "Kontakter: av" }),
    ).toBeDisabled();

    // Step 2: only the explicit button sends confirm: true, with the version the host answered for.
    await user.click(
      screen.getByRole("button", { name: "Ja, radera minnet av dagboken" }),
    );
    expect(setMemory).toHaveBeenCalledTimes(2);
    expect(setMemory).toHaveBeenLastCalledWith({
      expectedVersion: 4,
      domain: "journal",
      value: false,
      confirm: true,
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("group", { name: "Slå av dagboken?" }),
      ).toBeNull(),
    );
  });

  it("Cancel sends nothing", async () => {
    const user = userEvent.setup();
    const setMemory = vi
      .fn<ControlTransport["setMemory"]>()
      .mockResolvedValue(needsConfirmation(12));
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(setMemory)}
        labels={controlSv}
      />,
    );
    await user.click(screen.getByRole("switch", { name: "Dagbok: på" }));
    await user.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(setMemory).toHaveBeenCalledTimes(1);
    expect(setMemory.mock.calls.some(([c]) => c.confirm === true)).toBe(false);
    expect(
      screen.queryByRole("group", { name: "Slå av dagboken?" }),
    ).toBeNull();
    expect(screen.getByRole("switch", { name: "Dagbok: på" })).toBeEnabled();
  });

  it("Cancel comes first in the question, so Tab reaches it before the red button", async () => {
    const user = userEvent.setup();
    const setMemory = vi
      .fn<ControlTransport["setMemory"]>()
      .mockResolvedValue(needsConfirmation(12));
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(setMemory)}
        labels={controlSv}
      />,
    );
    await user.click(screen.getByRole("switch", { name: "Dagbok: på" }));
    const question = screen.getByRole("group", { name: "Slå av dagboken?" });
    expect(
      within(question)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Avbryt", "Ja, radera minnet av dagboken"]);

    await user.tab();
    expect(
      within(question).getByRole("button", { name: "Avbryt" }),
    ).toHaveFocus();
    await user.tab();
    expect(
      within(question).getByRole("button", {
        name: "Ja, radera minnet av dagboken",
      }),
    ).toHaveFocus();
  });

  it("without a count the question says all facts go", async () => {
    const user = userEvent.setup();
    const setMemory = vi
      .fn<ControlTransport["setMemory"]>()
      .mockResolvedValue(needsConfirmation(null));
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(setMemory)}
        labels={controlSv}
      />,
    );
    await user.click(screen.getByRole("switch", { name: "Dagbok: på" }));
    expect(
      screen.getByRole("group", { name: "Slå av dagboken?" }),
    ).toHaveTextContent(
      "Bara Sidekicks minne av dagboken raderas. Dagboken ändras inte.",
    );
  });

  it("a stale version on the confirmed call closes the question and reads again", async () => {
    const user = userEvent.setup();
    const setMemory = vi
      .fn<ControlTransport["setMemory"]>()
      .mockResolvedValueOnce(needsConfirmation(12))
      .mockRejectedValueOnce(fail("conflict"));
    const transport = makeTransport(setMemory);
    render(
      <MemoryView initial={status} transport={transport} labels={controlSv} />,
    );
    await user.click(screen.getByRole("switch", { name: "Dagbok: på" }));
    await user.click(
      screen.getByRole("button", { name: "Ja, radera minnet av dagboken" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.memoryConflict,
    );
    expect(
      screen.queryByRole("group", { name: "Slå av dagboken?" }),
    ).toBeNull();
    expect(transport.memoryStatus).toHaveBeenCalledTimes(1);
  });

  it("after the confirmed switch-off the count reads deleting until a later status read", async () => {
    const user = userEvent.setup();
    const offSettings = { ...settings, journal: false, version: 5 };
    const setMemory = vi
      .fn<ControlTransport["setMemory"]>()
      .mockResolvedValueOnce(needsConfirmation(12))
      .mockResolvedValueOnce({
        status: "updated",
        settings: offSettings,
        turning_off: [{ domain: "journal", documents: 12 }],
      })
      .mockResolvedValueOnce({
        status: "updated",
        settings: { ...offSettings, contacts: true, version: 6 },
        turning_off: [],
      });
    // The read right after the switch-off still carries the old journal count.
    const transport = makeTransport(setMemory, {
      ...status,
      settings: offSettings,
    });
    render(
      <MemoryView initial={status} transport={transport} labels={controlSv} />,
    );
    await user.click(screen.getByRole("switch", { name: "Dagbok: på" }));
    await user.click(
      screen.getByRole("button", { name: "Ja, radera minnet av dagboken" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Dagboken är avslagen. Minnet raderas inom några minuter.",
    );
    expect(screen.getByText("· raderas…")).toBeVisible();
    expect(
      screen.queryByText(metaLine("På · 12 anteckningar i minnet · 2 på väg")),
    ).toBeNull();

    // A later status read replaces the marker: the switched-off journal shows "not in memory" again.
    await user.click(screen.getByRole("switch", { name: "Kontakter: av" }));
    expect(setMemory).toHaveBeenLastCalledWith({
      expectedVersion: 5,
      domain: "contacts",
      value: true,
    });
    await waitFor(() => expect(screen.queryByText("· raderas…")).toBeNull());
    expect(
      screen.getAllByText(metaLine("Av · inte med i minnet")),
    ).toHaveLength(3);
  });
});

describe("MemoryView sources heading", () => {
  it("puts an h3 Källor / Sources before the list, with the meta in the language of the labels", () => {
    const { unmount } = render(
      <MemoryView
        initial={status}
        transport={makeTransport(vi.fn())}
        labels={controlSv}
      />,
    );
    const section = screen.getByRole("heading", { level: 3, name: "Källor" });
    expect(section).toHaveClass("control-section");
    expect(section.nextElementSibling?.tagName).toBe("UL");
    unmount();
    render(
      <MemoryView
        initial={status}
        transport={makeTransport(vi.fn())}
        labels={controlEn}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 3, name: "Sources" }),
    ).toBeInTheDocument();
    expect(document.querySelector("p.control-headrow-meta")).toHaveTextContent(
      "2 of 4 sources",
    );
  });
});
