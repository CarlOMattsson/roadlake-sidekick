import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HostToolError } from "@/features/mcp-apps/bridge";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { StartRoom } from "@/features/start-app/room";
import {
  approvedOf,
  automationsPage,
  evening,
  invoices,
  morning,
  report,
} from "../../e2e/automations-fixtures";
import { inboxPage } from "../../e2e/suggestions-fixtures";

type Answers = Record<string, (args: Record<string, unknown>) => unknown>;

function transportOf(answers: Answers, offered?: (name: string) => boolean) {
  const call = vi.fn((name: string, args: object) =>
    Promise.resolve().then(() => {
      const answer = answers[name];
      if (!answer) throw new Error(`no answer for ${name}`);
      return answer(args as Record<string, unknown>);
    }),
  );
  const transport = {
    call,
    requestDisplayMode: vi.fn(() => Promise.resolve("fullscreen" as const)),
    updateModelContext: vi.fn(() => Promise.resolve()),
    ...(offered ? { supportsTool: offered } : {}),
  } as unknown as RoomTransport;
  return { transport, call };
}

const byId =
  (records: (typeof morning)[]) => (args: Record<string, unknown>) => {
    const found = records.find((record) => record.id === args.automation_id);
    if (!found) throw new Error("unknown automation");
    return { automation: found };
  };

const approvals = (call: ReturnType<typeof transportOf>["call"]) =>
  call.mock.calls.filter(([name]) => name === "approve_automation");

function openDetail(answers: Answers, record: typeof morning) {
  const both = transportOf({
    get_automation: byId([record]),
    get_automation_report: () => report,
    ...answers,
  });
  render(
    <StartRoom
      mode="full"
      view="automation"
      transport={both.transport}
      initial={{ automation: { id: record.id } }}
    />,
  );
  return both;
}

describe("an automation's approval", () => {
  it("approves a spec that only proposes with the digest as shown, and no confirmation", async () => {
    const { call } = openDetail(
      {
        get_automation: byId([evening]),
        approve_automation: () => ({ automation: approvedOf(evening) }),
      },
      evening,
    );
    expect(
      await screen.findByRole("heading", { level: 2, name: "Kvällsgenomgång" }),
    ).toBeTruthy();
    // Said where it stands, and as the warning at the top of the view.
    expect(screen.getAllByText("Ändrad sedan du godkände den")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Godkänn" }));
    await waitFor(() => expect(approvals(call)).toHaveLength(1));
    const args = approvals(call)[0]![1] as Record<string, unknown>;
    expect(args).toMatchObject({
      automation_id: evening.id,
      spec_digest: evening.spec_digest,
    });
    expect(args).not.toHaveProperty("auto_apply_confirmed");
    expect(typeof args.idempotency_key).toBe("string");
    expect(await screen.findByText("Godkänd: Kvällsgenomgång")).toBeTruthy();
  });

  it("asks for the separate confirmation before it sends auto_apply_confirmed", async () => {
    const { call } = openDetail(
      { approve_automation: () => ({ automation: approvedOf(invoices) }) },
      invoices,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Godkänn…" }));
    // The first press only opens the step: nothing is sent.
    expect(approvals(call)).toHaveLength(0);
    const step = screen.getByRole("group", {
      name: "Den lägger in förslag utan att fråga dig",
    });
    expect(step.textContent).toMatch(/minst 95 % säker/);
    expect(step.textContent).toMatch(/Högst 10 per körning och 25 per dag/);
    await waitFor(() =>
      expect(document.activeElement?.textContent).toBe(
        "Den lägger in förslag utan att fråga dig",
      ),
    );

    // Godkänn without the box ticked sends nothing and points at the box.
    fireEvent.click(screen.getByRole("button", { name: "Godkänn" }));
    expect(approvals(call)).toHaveLength(0);
    expect(screen.getByText("Kryssa i rutan först")).toBeTruthy();
    const box = screen.getByRole("checkbox", {
      name: "Jag vill att den lägger in de här förslagen utan att fråga mig",
    });
    expect(document.activeElement).toBe(box);

    fireEvent.click(box);
    fireEvent.click(screen.getByRole("button", { name: "Godkänn" }));
    await waitFor(() => expect(approvals(call)).toHaveLength(1));
    expect(approvals(call)[0]![1]).toMatchObject({
      automation_id: invoices.id,
      spec_digest: invoices.spec_digest,
      auto_apply_confirmed: true,
    });
    expect(
      await screen.findByText("Den får lägga in förslag utan att fråga."),
    ).toBeTruthy();
  });

  it("names the caps the server sent, not its own copy", async () => {
    const limited = {
      ...invoices,
      auto_apply_limits: { per_run: 4, per_day: 9 },
    };
    openDetail({ get_automation: byId([limited]) }, limited);
    fireEvent.click(await screen.findByRole("button", { name: "Godkänn…" }));
    const step = screen.getByRole("group", {
      name: "Den lägger in förslag utan att fråga dig",
    });
    expect(step.textContent).toMatch(/Högst 4 per körning och 9 per dag/);
  });

  it("Avbryt closes the step, forgets the tick and returns the focus", async () => {
    const { call } = openDetail(
      { approve_automation: () => ({ automation: approvedOf(invoices) }) },
      invoices,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Godkänn…" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    const start = screen.getByRole("button", { name: "Godkänn…" });
    await waitFor(() => expect(document.activeElement).toBe(start));
    fireEvent.click(start);
    expect(screen.getByRole<HTMLInputElement>("checkbox").checked).toBe(false);
    expect(approvals(call)).toHaveLength(0);
  });

  it("reads the automation again when the server says it changed since it was shown", async () => {
    let reads = 0;
    const changed = { ...invoices, spec_digest: "c".repeat(64), version: 3 };
    const { call } = openDetail(
      {
        get_automation: () => {
          reads += 1;
          return { automation: reads === 1 ? invoices : changed };
        },
        approve_automation: () => {
          throw new HostToolError("conflict", "automation_changed");
        },
      },
      invoices,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Godkänn…" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Godkänn" }));
    expect(
      await screen.findByText(
        "Automationen ändrades medan du tittade. Läs igenom den igen.",
      ),
    ).toBeTruthy();
    await waitFor(() => expect(reads).toBe(2));
    // The step starts over on the new spec: its confirmation is asked again.
    expect(screen.getByRole("button", { name: "Godkänn…" })).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(approvals(call)).toHaveLength(1);
  });

  it("says so when the approval fails, and keeps the step for a retry with the same key", async () => {
    let attempt = 0;
    const { call } = openDetail(
      {
        approve_automation: () => {
          attempt += 1;
          if (attempt === 1) throw new Error("down");
          return { automation: approvedOf(invoices) };
        },
      },
      invoices,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Godkänn…" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Godkänn" }));
    expect(
      await screen.findByText("Det gick inte att godkänna. Försök igen."),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Godkänn" }));
    await waitFor(() => expect(approvals(call)).toHaveLength(2));
    const [first, second] = approvals(call).map(
      ([, args]) => (args as { idempotency_key: string }).idempotency_key,
    );
    expect(second).toBe(first);
  });

  it("offers no approval where the host has no approve_automation", async () => {
    const { transport } = transportOf(
      { get_automation: byId([invoices]), get_automation_report: () => report },
      (name) => name !== "approve_automation",
    );
    render(
      <StartRoom
        mode="full"
        view="automation"
        transport={transport}
        initial={{ automation: { id: invoices.id } }}
      />,
    );
    expect(
      await screen.findByRole("heading", { level: 2, name: "Fakturakoll" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Godkänn/ })).toBeNull();
  });

  it("shows an approved automation's runs from the report", async () => {
    openDetail({}, morning);
    expect(
      await screen.findByText(
        /3 körningar · 1 misslyckades · 7 förslag · 3 väntar · 0,09 USD/,
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("Körningen misslyckades: budgeten tog slut"),
    ).toBeTruthy();
    expect(screen.getByText(/^Godkänd /)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Godkänn/ })).toBeNull();
  });
});

describe("the way to the automations", () => {
  it("leads from the inbox with how many wait for approval, and lists them", async () => {
    const onNavigate = vi.fn();
    const { transport } = transportOf({
      list_suggestions: () => inboxPage,
      list_automations: () => automationsPage,
    });
    render(
      <StartRoom
        mode="full"
        transport={transport}
        initial={inboxPage}
        onNavigate={onNavigate}
      />,
    );
    const entry = await screen.findByRole("button", {
      name: /Automationer.*2 väntar på ditt godkännande/,
    });
    fireEvent.click(entry);
    expect(onNavigate).toHaveBeenCalledWith(
      expect.objectContaining({ room: "start", view: "automations" }),
    );
  });

  it("draws no entry where the host cannot read automations", async () => {
    const { transport, call } = transportOf(
      { list_suggestions: () => inboxPage },
      (name) => !name.includes("automation"),
    );
    render(
      <StartRoom
        mode="full"
        transport={transport}
        initial={inboxPage}
        onNavigate={vi.fn()}
      />,
    );
    expect(await screen.findByText("Säkra förslag (4)")).toBeTruthy();
    expect(screen.queryByText("Automationer")).toBeNull();
    expect(call.mock.calls.some(([name]) => name === "list_automations")).toBe(
      false,
    );
  });

  it("lists the ones that wait first, and opens one", async () => {
    const onNavigate = vi.fn();
    const { transport } = transportOf({
      list_automations: () => automationsPage,
    });
    render(
      <StartRoom
        mode="full"
        view="automations"
        transport={transport}
        onNavigate={onNavigate}
      />,
    );
    const rows = await screen.findAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringMatching(/^Fakturakoll/),
      expect.stringMatching(/^Kvällsgenomgång/),
      expect.stringMatching(/^Morgonmejl/),
      expect.stringMatching(/^Veckorapport/),
    ]);
    fireEvent.click(screen.getByRole("button", { name: /^Fakturakoll/ }));
    expect(onNavigate).toHaveBeenCalledWith({
      room: "start",
      view: "automation",
      id: invoices.id,
      label: "Fakturakoll",
    });
  });

  it("says when there are none, in English too", async () => {
    document.head.insertAdjacentHTML(
      "beforeend",
      '<meta name="sidekick-app-locale" content="en">',
    );
    const { transport } = transportOf({
      list_automations: () => ({ items: [], next_cursor: null }),
    });
    render(<StartRoom mode="full" view="automations" transport={transport} />);
    expect(await screen.findByText("No automations yet.")).toBeTruthy();
    document.head
      .querySelectorAll('meta[name="sidekick-app-locale"]')
      .forEach((meta) => meta.remove());
  });
});
