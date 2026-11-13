import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { controlEn, controlSv } from "@/features/control-app/labels";
import { MemoryView } from "@/features/control-app/memory-view";
import type {
  ControlTransport,
  MemoryStatus,
  RecallRequest,
  RecallResult,
  RecalledFact,
} from "@/features/control-app/transport";

/** A row's meta line, matched on its whole text: each "·" part is a span of its own. */
const metaLine = (text: string) => (_: string, el: Element | null) =>
  !!el?.classList.contains("control-row-secondary") && el.textContent === text;

/** An error as the app client throws it: only the closed code is read by the view. */
function fail(code: string): Error {
  return Object.assign(new Error(code), { code });
}

// The date on a fact's meta line leaves out the year of "today", so today is fixed.
beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-13T09:00:00Z") });
});
afterAll(() => {
  vi.useRealTimers();
});

const status: MemoryStatus = {
  settings: {
    journal: true,
    contacts: false,
    projects: true,
    tasks: false,
    paused: false,
    version: 4,
  },
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
  ],
};

const fact = (
  text: string,
  id: string,
  title: string | null,
): RecalledFact => ({
  text,
  occurred: null,
  source: {
    kind: "journal_entry",
    id,
    title,
    date: "2026-11-01",
    archived: false,
  },
});

const ok = (facts: RecalledFact[]): RecallResult => ({
  status: "ok",
  facts,
  truncated: false,
});

type Recall = (request: RecallRequest) => Promise<RecallResult>;
type Forget = (fact: RecalledFact) => Promise<unknown>;

function makeTransport(recall?: Recall, forget?: Forget): ControlTransport {
  return {
    trash: vi.fn(),
    restore: vi.fn(),
    changes: vi.fn(),
    undoPurchase: vi.fn(),
    memoryStatus: vi.fn(() => Promise.resolve(status)),
    setMemory: vi.fn(),
    activity: vi.fn(),
    ...(recall && forget ? { recall, forget } : {}),
  };
}

const sample = [
  fact("Anna föreslog en promenad", "id-1", "Söndag"),
  fact("Du ville sova längre", "id-2", null),
];

function renderMemory(transport: ControlTransport, labels = controlSv) {
  return render(
    <MemoryView initial={status} transport={transport} labels={labels} />,
  );
}

describe("Memory explanation", () => {
  it("states where the text goes, in both languages", () => {
    const { unmount } = renderMemory(makeTransport());
    expect(screen.getByText(controlSv.memoryExplain)).toBeInTheDocument();
    expect(controlSv.memoryExplain).toMatch(/Sidekick-server/);
    unmount();
    renderMemory(makeTransport(), controlEn);
    expect(screen.getByText(controlEn.memoryExplain)).toBeInTheDocument();
    expect(controlEn.memoryExplain).toMatch(/language model/);
  });

  it("lets a source row's meta line wrap instead of cutting it", () => {
    renderMemory(makeTransport());
    expect(screen.getByRole("list", { name: "Sidekicks minne" })).toHaveClass(
      "control-list-wrap",
    );
  });
});

describe("Memory recall", () => {
  it("offers neither the sample nor the search when the host lacks the tools", () => {
    renderMemory(makeTransport());
    expect(screen.queryByText("Visa vad Sidekick minns")).toBeNull();
    expect(screen.queryByRole("search")).toBeNull();
  });

  it("offers the sample only for a source that is on", () => {
    renderMemory(makeTransport(vi.fn(), vi.fn()));
    // Journal and Projects are on; Contacts and Tasks are off.
    expect(screen.getAllByText("Visa vad Sidekick minns")).toHaveLength(2);
  });

  it("offers neither the sample nor the search while the memory service is off, and says queued text is waiting", () => {
    render(
      <MemoryView
        initial={{ ...status, provider: "off" }}
        transport={makeTransport(vi.fn(), vi.fn())}
        labels={controlSv}
      />,
    );
    expect(screen.queryByText("Visa vad Sidekick minns")).toBeNull();
    expect(screen.queryByRole("search")).toBeNull();
    expect(
      screen.getByText(metaLine("På · 12 anteckningar i minnet · 2 väntar")),
    ).toBeVisible();
  });

  it("offers no search when every source is off", () => {
    render(
      <MemoryView
        initial={{
          ...status,
          settings: {
            ...status.settings,
            journal: false,
            projects: false,
          },
        }}
        transport={makeTransport(vi.fn(), vi.fn())}
        labels={controlSv}
      />,
    );
    expect(screen.queryByRole("search")).toBeNull();
  });

  it("dates a fact by its record and marks an archived record", async () => {
    const archived: RecalledFact = {
      text: "Köket målas i vitt",
      occurred: null,
      source: {
        kind: "project",
        id: "id-3",
        title: "Köksrenovering",
        date: null,
        archived: true,
      },
    };
    const recall = vi.fn<Recall>(() => Promise.resolve(ok([archived])));
    renderMemory(makeTransport(recall, vi.fn()));
    await userEvent.click(
      screen.getByRole("button", {
        name: "Visa vad Sidekick minns från Projekt",
      }),
    );
    expect(
      await screen.findByText(metaLine("Projekt · Köksrenovering · arkiverat")),
    ).toBeInTheDocument();
  });

  it("reads nothing until opened, then asks recall_memory for that source only and shows the facts without ids", async () => {
    const recall = vi.fn<Recall>(() => Promise.resolve(ok(sample)));
    renderMemory(makeTransport(recall, vi.fn()));
    expect(recall).not.toHaveBeenCalled();

    await userEvent.click(
      screen.getByRole("button", {
        name: "Visa vad Sidekick minns från Dagbok",
      }),
    );

    expect(recall).toHaveBeenCalledWith({
      query: controlSv.recallProbe,
      kind: "journal_entry",
    });
    expect(await screen.findByText("Anna föreslog en promenad")).toBeVisible();
    expect(
      screen.getByText(metaLine("Dagboksanteckning · Söndag · 1 nov")),
    ).toBeInTheDocument();
    expect(screen.getByText(controlSv.recallSample)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/id-1|id-2/);
    expect(
      screen.getByRole("button", {
        name: "Dölj vad Sidekick minns från Dagbok",
      }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("says so when there is nothing to show", async () => {
    const recall = vi.fn<Recall>(() => Promise.resolve(ok([])));
    renderMemory(makeTransport(recall, vi.fn()));
    await userEvent.click(
      screen.getByRole("button", {
        name: /Visa vad Sidekick minns från Dagbok/,
      }),
    );
    expect(await screen.findByText(controlSv.recallEmpty)).toBeInTheDocument();
  });

  it("drops a fact of the wrong shape quietly and keeps the others", async () => {
    const broken = [
      { text: "Utan källa", occurred: null },
      {
        text: "Okänd sort",
        source: { kind: "nonsense", id: "x", title: null },
      },
      null,
      sample[0]!,
    ] as unknown as RecalledFact[];
    const recall = vi.fn<Recall>(() => Promise.resolve(ok(broken)));
    renderMemory(makeTransport(recall, vi.fn()));
    await userEvent.click(
      screen.getByRole("button", {
        name: /Visa vad Sidekick minns från Dagbok/,
      }),
    );

    expect(await screen.findByText("Anna föreslog en promenad")).toBeVisible();
    expect(screen.queryByText("Utan källa")).toBeNull();
    expect(screen.queryByText("Okänd sort")).toBeNull();
    expect(screen.getAllByRole("button", { name: /Glöm/ })).toHaveLength(1);
  });

  it("says memory is paused and off instead of listing", async () => {
    const recall = vi.fn<Recall>(() =>
      Promise.resolve({ status: "paused", facts: [], truncated: false }),
    );
    renderMemory(makeTransport(recall, vi.fn()));
    await userEvent.click(
      screen.getByRole("button", {
        name: /Visa vad Sidekick minns från Dagbok/,
      }),
    );
    expect(await screen.findByText(controlSv.recallPaused)).toBeInTheDocument();
  });

  it("shows a failure with Try again that reads again", async () => {
    const recall = vi
      .fn<Recall>()
      .mockRejectedValueOnce(fail("unavailable"))
      .mockResolvedValueOnce(ok(sample));
    renderMemory(makeTransport(recall, vi.fn()));
    await userEvent.click(
      screen.getByRole("button", {
        name: /Visa vad Sidekick minns från Dagbok/,
      }),
    );
    expect(
      await screen.findByText(controlSv.recallUnavailableHeading),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Du ville sova längre")).toBeVisible();
    expect(recall).toHaveBeenCalledTimes(2);
  });

  it("answers a refusal calmly, without Try again", async () => {
    const recall = vi.fn<Recall>(() => Promise.reject(fail("forbidden")));
    renderMemory(makeTransport(recall, vi.fn()));
    await userEvent.click(
      screen.getByRole("button", {
        name: /Visa vad Sidekick minns från Dagbok/,
      }),
    );
    expect(
      await screen.findByText(controlSv.recallForbidden),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Försök igen" })).toBeNull();
  });
});

describe("Memory search", () => {
  it("asks recall_memory with the free text over every source", async () => {
    const recall = vi.fn<Recall>(() => Promise.resolve(ok([sample[0]!])));
    renderMemory(makeTransport(recall, vi.fn()));
    const search = within(screen.getByRole("search"));
    await userEvent.type(search.getByRole("searchbox"), "promenad{Enter}");

    expect(recall).toHaveBeenCalledWith({ query: "promenad" });
    expect(await screen.findByText("Anna föreslog en promenad")).toBeVisible();
    // A question's answer does not claim to be a sample.
    expect(screen.queryByText(controlSv.recallSample)).toBeNull();
  });

  it("refuses a query shorter than two characters without calling the tool", async () => {
    const recall = vi.fn<Recall>(() => Promise.resolve(ok([])));
    renderMemory(makeTransport(recall, vi.fn()));
    await userEvent.type(screen.getByRole("searchbox"), "a");
    await userEvent.click(screen.getByRole("button", { name: "Sök" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      controlSv.searchTooShort,
    );
    expect(recall).not.toHaveBeenCalled();
  });

  it("says nothing was found", async () => {
    const recall = vi.fn<Recall>(() => Promise.resolve(ok([])));
    renderMemory(makeTransport(recall, vi.fn()));
    await userEvent.type(screen.getByRole("searchbox"), "hund{Enter}");
    expect(
      await screen.findByText(controlSv.recallNothing),
    ).toBeInTheDocument();
  });
});

describe("Forget this", () => {
  async function openSample(forget: Forget, labels = controlSv) {
    const recall = vi.fn<Recall>(() => Promise.resolve(ok(sample)));
    renderMemory(makeTransport(recall, forget), labels);
    await userEvent.click(
      screen.getAllByRole("button", {
        name: /Visa vad Sidekick minns|Show what/,
      })[0]!,
    );
    await screen.findByText("Anna föreslog en promenad");
  }

  it("asks first with what happens and sends nothing until confirmed; Cancel returns focus", async () => {
    const forget = vi.fn<Forget>(() => Promise.resolve({}));
    await openSample(forget);

    const button = screen.getByRole("button", {
      name: "Glöm anteckningen: Söndag",
    });
    await userEvent.click(button);

    const confirm = screen.getByRole("group", {
      name: "Glöm anteckningen ”Söndag”?",
    });
    expect(confirm).toHaveClass("control-confirm");
    expect(confirm).toHaveTextContent(
      "Allt Sidekick minns från anteckningen, inte bara det här faktumet, tas bort ur Sidekicks minne. Själva anteckningen ändras inte.",
    );
    expect(forget).not.toHaveBeenCalled();

    await userEvent.click(
      within(confirm).getByRole("button", { name: "Avbryt" }),
    );
    expect(forget).not.toHaveBeenCalled();
    expect(screen.queryByRole("group", { name: /Glöm/ })).toBeNull();
    await waitFor(() => expect(button).toHaveFocus());
  });

  it("forgets the whole source record after the confirmation and shows a short status", async () => {
    const forget = vi.fn<Forget>(() => Promise.resolve({}));
    await openSample(forget);

    await userEvent.click(
      screen.getByRole("button", { name: "Glöm anteckningen: Söndag" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Ja, glöm anteckningen" }),
    );

    await waitFor(() => expect(forget).toHaveBeenCalledWith(sample[0]));
    await waitFor(() =>
      expect(screen.queryByText("Anna föreslog en promenad")).toBeNull(),
    );
    expect(
      screen.getByText(
        "Sidekick har glömt ”Söndag”. Själva anteckningen ändras inte. Det kan ta några minuter innan det försvinner ur sökningen.",
      ),
    ).toBeInTheDocument();
    // The other record's fact stays.
    expect(screen.getByText("Du ville sova längre")).toBeInTheDocument();
  });

  it("says a failed forget failed and keeps the row", async () => {
    const forget = vi.fn<Forget>(() => Promise.reject(fail("unavailable")));
    await openSample(forget);

    await userEvent.click(
      screen.getByRole("button", { name: "Glöm anteckningen: Söndag" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Ja, glöm anteckningen" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      controlSv.forgetFailed,
    );
    expect(screen.getByText("Anna föreslog en promenad")).toBeInTheDocument();
  });

  it("reads in English", async () => {
    const forget = vi.fn<Forget>(() => Promise.resolve({}));
    await openSample(forget, controlEn);
    await userEvent.click(
      screen.getByRole("button", { name: "Forget the entry: Söndag" }),
    );
    expect(
      screen.getByRole("group", { name: "Forget the entry “Söndag”?" }),
    ).toHaveTextContent(
      "Everything Sidekick remembers from this entry, not just this fact, is removed from Sidekick’s memory. The entry itself won’t change.",
    );
  });

  it("tells in English that search can lag a few minutes after a forget", async () => {
    const forget = vi.fn<Forget>(() => Promise.resolve({}));
    await openSample(forget, controlEn);
    await userEvent.click(
      screen.getByRole("button", { name: "Forget the entry: Söndag" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Yes, forget the entry" }),
    );
    expect(
      await screen.findByText(
        "Sidekick has forgotten “Söndag”. The entry itself won’t change. It can take a few minutes before it stops showing up in search.",
      ),
    ).toBeInTheDocument();
  });
});
