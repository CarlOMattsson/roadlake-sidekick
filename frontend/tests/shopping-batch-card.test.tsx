import { act, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;

// The bridge is the only thing mocked: sidekick-entry runs at import time and binds its listeners here.
const host = vi.hoisted(() => ({
  toolResult: [] as ToolResultListener[],
  initialize: vi.fn(),
}));

vi.mock("@/features/mcp-apps/bridge", () => ({
  createHostBridge: () => ({
    getFeatures: () => ({
      serverTools: false,
      message: false,
      openLinks: false,
    }),
    sendMessage: vi.fn().mockResolvedValue(false),
    initialize: host.initialize,
    call: vi.fn(() => new Promise(() => undefined)),
    requestDisplayMode: vi.fn(() => Promise.resolve("inline")),
    updateModelContext: vi.fn(),
    onToolResult: (listener: ToolResultListener) => {
      host.toolResult.push(listener);
    },
    onHostContext: () => undefined,
    onTeardown: () => undefined,
  }),
}));

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Veckohandel",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

const milk = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  list_id: list.id,
  name: "Milk",
  version: 1,
  purchased: false,
};

afterAll(() => {
  document.head.innerHTML = "";
});

beforeAll(async () => {
  // The app reads its language once, when sidekick-entry is imported, so the Sidekick setting goes in first.
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  document.body.innerHTML = '<div id="root"></div>';
  host.initialize.mockResolvedValue({ locale: "en-GB" });
  await import("@/features/mcp-apps/sidekick-entry");
});

/** Delivers one tool result to the mounted app, as the host does after a model tool call. */
function deliver(structuredContent: unknown) {
  act(() => {
    for (const listener of host.toolResult)
      listener({ structuredContent, isError: false });
  });
}

/** The batch row with this full text. The prefix is a span of its own, so the row's text is matched whole. */
function batchRow(text: string) {
  return screen.getByText(
    (_content, element) =>
      element?.tagName === "LI" && element.textContent === text,
  );
}

describe("batch card names the list", () => {
  it("an add result names the list in the heading", () => {
    deliver({
      items: [
        { client_ref: "0", item: milk },
        {
          client_ref: "1",
          item: {
            ...milk,
            id: "019f0000-0000-7000-8000-0000000000a2",
            name: "Bread",
          },
        },
      ],
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    expect(
      screen.getByRole("heading", { name: "Veckohandel" }),
    ).toBeInTheDocument();
    expect(batchRow("Added: Milk")).toBeInTheDocument();
    expect(screen.getByText(shoppingEn.updatedKicker())).toBeInTheDocument();
    expect(batchRow("Added: Bread")).toBeInTheDocument();
  });

  it("an update result names the list in the heading", () => {
    deliver({
      item: { ...milk, name: "Eggs", version: 2 },
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    expect(
      screen.getByRole("heading", { name: "Veckohandel" }),
    ).toBeInTheDocument();
    expect(batchRow("Updated: Eggs")).toBeInTheDocument();
  });

  it("without list_name the heading falls back to Shopping list", () => {
    deliver({
      items: [{ client_ref: "0", item: milk }],
      evaluated_on: "2026-10-24",
    });
    expect(
      screen.getByRole("heading", { name: "Shopping list" }),
    ).toBeInTheDocument();
  });

  it("a blank list_name is ignored", () => {
    deliver({
      items: [{ client_ref: "0", item: milk }],
      evaluated_on: "2026-10-24",
      list_name: "   ",
    });
    expect(
      screen.getByRole("heading", { name: "Shopping list" }),
    ).toBeInTheDocument();
  });

  it("the kicker names the newest updated_at of the items in Stockholm time, with its day", () => {
    const written = [
      {
        client_ref: "0",
        item: { ...milk, updated_at: "2026-10-24T10:00:00Z" },
      },
      {
        client_ref: "1",
        item: {
          ...milk,
          id: "019f0000-0000-7000-8000-0000000000a2",
          name: "Bread",
          updated_at: "2026-10-24T12:00:00Z",
        },
      },
    ];
    // 12:00 UTC is 14:00 in Stockholm (summer time on this date). The day word is read against the clock of the card.
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.setSystemTime(new Date("2026-10-24T18:00:00Z"));
      deliver({
        items: written,
        evaluated_on: "2026-10-24",
        list_name: "Veckohandel",
      });
      expect(
        screen.getByText("Shopping · updated today 14:00"),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("the kicker says yesterday, or the date, when the list was written on an earlier day", () => {
    const written = [
      {
        client_ref: "0",
        item: { ...milk, updated_at: "2026-10-24T12:00:00Z" },
      },
    ];
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.setSystemTime(new Date("2026-10-25T08:00:00Z"));
      deliver({
        items: written,
        evaluated_on: "2026-10-25",
        list_name: "Veckohandel",
      });
      expect(
        screen.getByText("Shopping · updated yesterday 14:00"),
      ).toBeInTheDocument();
      vi.setSystemTime(new Date("2026-10-27T08:00:00Z"));
      deliver({
        items: written,
        evaluated_on: "2026-10-27",
        list_name: "Veckohandel",
      });
      expect(
        screen.getByText("Shopping · updated Sat 24 Oct 14:00"),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("each item with an amount shows it after its name", () => {
    deliver({
      items: [
        {
          client_ref: "0",
          item: { ...milk, name: "Potatis", quantity: "2", unit: "kg" },
        },
        {
          client_ref: "1",
          item: { ...milk, name: "Mjölk", quantity: "1.5", unit: "l" },
        },
      ],
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    expect(batchRow("Added: Potatis, 2 kg")).toBeInTheDocument();
    expect(batchRow("Added: Mjölk, 1.5 l")).toBeInTheDocument();
  });

  it("an item without an amount is named alone, never as 1 or 1.000", () => {
    deliver({
      items: [
        {
          client_ref: "0",
          item: { ...milk, name: "Bread", quantity: "1.000", unit: null },
        },
        {
          client_ref: "1",
          item: { ...milk, name: "Eggs", quantity: 1, unit: null },
        },
      ],
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    expect(batchRow("Added: Bread")).toBeInTheDocument();
    expect(batchRow("Added: Eggs")).toBeInTheDocument();
  });

  it("an update result shows the item's amount", () => {
    deliver({
      item: { ...milk, name: "Eggs", quantity: "12", unit: "st", version: 2 },
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    expect(batchRow("Updated: Eggs, now 12 st")).toBeInTheDocument();
  });

  it("an update names the outcome with the item first, the label and the line in their own elements", () => {
    deliver({
      item: { ...milk, name: "Mjölk", quantity: "2", unit: "l", version: 2 },
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    const line = batchRow("Updated: Mjölk, now 2 l");
    expect(line).toHaveClass("shopping-receipt-line");
    expect(line.querySelector(".shopping-receipt-label")).toHaveTextContent(
      /^Updated:$/,
    );
    expect(screen.queryByText(/Changed:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/merged/)).not.toBeInTheDocument();
  });

  it("an added item keeps Added: in a label element of its own", () => {
    deliver({
      items: [{ client_ref: "0", item: milk }],
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    const line = batchRow("Added: Milk");
    expect(line).toHaveClass("shopping-receipt-line");
    expect(line.querySelector(".shopping-receipt-label")).toHaveTextContent(
      /^Added:$/,
    );
  });

  it("the labels give the kicker and the fallback title in English and Swedish", () => {
    expect(shoppingEn.updatedKicker()).toBe("Shopping · updated");
    expect(shoppingEn.updatedKicker("13:00")).toBe("Shopping · updated 13:00");
    expect(shoppingSv.updatedKicker()).toBe("Inköp · uppdaterad");
    expect(shoppingSv.updatedKicker("13:00")).toBe("Inköp · uppdaterad 13:00");
    expect(shoppingEn.listFallback).toBe("Shopping list");
    expect(shoppingSv.listFallback).toBe("Inköpslista");
    expect(shoppingEn.newItemPrefix).toBe("Added:");
    expect(shoppingSv.newItemPrefix).toBe("Tillagd:");
    // The outcome first, then the item and its amount: "Uppdaterad: Mjölk, nu 2 l"; a merged item
    // without an amount is "Fanns redan: Mjölk".
    expect(shoppingSv.updatedPrefix).toBe("Uppdaterad:");
    expect(shoppingEn.updatedPrefix).toBe("Updated:");
    expect(shoppingSv.existedPrefix).toBe("Fanns redan:");
    expect(shoppingEn.existedPrefix).toBe("Already there:");
    expect(shoppingSv.nowAmount("2 l")).toBe("nu 2 l");
    expect(shoppingEn.nowAmount("2 l")).toBe("now 2 l");
    expect(shoppingSv).not.toHaveProperty("updatedValue");
    expect(shoppingSv).not.toHaveProperty("mergedValue");
  });
});

describe("batch card separates new items from merged ones", () => {
  const row = (n: number, merged: boolean) => ({
    client_ref: String(n),
    merged,
    item: {
      ...milk,
      id: `019f0000-0000-7000-8000-0000000000${n.toString(16).padStart(2, "0")}`,
      name: `Item ${n}`,
    },
  });

  it("a batch with merged inputs marks each changed row with its own prefix", () => {
    deliver({
      items: [row(1, false), row(2, true), row(3, true)],
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    expect(
      screen.getByRole("heading", {
        name: "Veckohandel",
      }),
    ).toBeInTheDocument();
    // The changed rows carry their own prefix; no separate line names them.
    expect(screen.queryByText(/Increased:/)).not.toBeInTheDocument();
    expect(batchRow("Added: Item 1")).toBeInTheDocument();
    // A merged input without an amount: whether it grew cannot be told, so it says the item was already there.
    expect(batchRow("Already there: Item 2")).toBeInTheDocument();
    expect(batchRow("Already there: Item 3")).toBeInTheDocument();
  });

  it("a merged input with an amount says Updated and the amount it has now", () => {
    deliver({
      items: [
        {
          ...row(1, true),
          item: {
            ...row(1, true).item,
            name: "Mjölk",
            quantity: "2",
            unit: "l",
          },
        },
      ],
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    const line = batchRow("Updated: Mjölk, now 2 l");
    expect(line.querySelector(".shopping-receipt-label")).toHaveTextContent(
      /^Updated:$/,
    );
    expect(screen.queryByText(/Already there/)).not.toBeInTheDocument();
  });

  it("one new item and one changed quantity give one row each", () => {
    deliver({
      items: [row(1, false), row(2, true)],
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    expect(
      screen.getByRole("heading", {
        name: "Veckohandel",
      }),
    ).toBeInTheDocument();
  });

  it("a batch without merged inputs keeps the plain heading and no marker", () => {
    deliver({
      items: [row(1, false), row(2, false)],
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    expect(
      screen.getByRole("heading", { name: "Veckohandel" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Increased:/)).not.toBeInTheDocument();
  });

  it("a long batch shows two names and counts the rest as +N more", () => {
    deliver({
      items: Array.from({ length: 10 }, (_, n) => row(n + 1, false)),
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    expect(batchRow("Added: Item 1")).toBeInTheDocument();
    expect(batchRow("Added: Item 2")).toBeInTheDocument();
    expect(screen.getByText("+8 more")).toBeInTheDocument();
    expect(screen.queryByText(/Item 3/)).not.toBeInTheDocument();
  });

  it("a short batch shows every name and no +N more", () => {
    deliver({
      items: [row(1, false), row(2, false), row(3, false)],
      evaluated_on: "2026-10-24",
      list_name: "Veckohandel",
    });
    expect(batchRow("Added: Item 3")).toBeInTheDocument();
    expect(screen.queryByText(/more$/)).not.toBeInTheDocument();
  });
});
