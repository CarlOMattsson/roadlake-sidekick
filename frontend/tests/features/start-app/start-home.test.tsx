import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { StartRoom } from "@/features/start-app/room";
import {
  fullStart,
  homeIds,
  partlyStart,
  quietStart,
  skipped,
} from "../../e2e/start-home-fixtures";
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

function setLocale(locale: "sv" | "en") {
  document.head
    .querySelectorAll('meta[name="sidekick-app-locale"]')
    .forEach((meta) => meta.remove());
  const meta = document.createElement("meta");
  meta.name = "sidekick-app-locale";
  meta.content = locale;
  document.head.append(meta);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-23T08:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
  document.head
    .querySelectorAll('meta[name="sidekick-app-locale"]')
    .forEach((meta) => meta.remove());
});

const headingTexts = () =>
  screen
    .getAllByRole("heading")
    .map((heading) => heading.textContent ?? "")
    .filter(Boolean);

describe("the Start room's home view", () => {
  it("reads get_start at the root and shows its parts in their order", async () => {
    const { transport, call } = transportOf({ get_start: () => fullStart });
    render(
      <StartRoom
        mode="full"
        transport={transport}
        onNavigate={vi.fn()}
        sendMessage={vi.fn(() => Promise.resolve(true))}
      />,
    );
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Måndag 23 november",
      }),
    ).toBeTruthy();
    expect(call).toHaveBeenCalledWith("get_start", {});
    expect(call).not.toHaveBeenCalledWith(
      "list_suggestions",
      expect.anything(),
    );
    expect(headingTexts()).toEqual([
      "Måndag 23 november",
      "Redo att prata",
      "Morgonplan",
      "Idag (4)",
      "Väntar på andra (3)",
    ]);
    expect(
      screen.getByText("Du har väntat på Erik Sjöstrand i 10 dagar."),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: /^Förslag.*5 väntar på ditt svar$/,
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: /^Automationer.*Sedan sist: 3 körningar · 5 nya förslag/,
      }),
    ).toBeTruthy();
    expect(screen.getByText("8 dagar försenad")).toBeTruthy();
    expect(screen.getByText("Erik Sjöstrand · sedan 13 nov")).toBeTruthy();
    expect(screen.getByText("1 till väntar")).toBeTruthy();
    // No count of nothing anywhere on the page.
    expect(document.body.textContent).not.toMatch(/\(0\)|\b0 /);
  });

  it("opens the inbox, the automations, the agenda and a task from its rows", async () => {
    const onNavigate = vi.fn();
    const { transport } = transportOf({ get_start: () => fullStart });
    render(
      <StartRoom mode="full" transport={transport} onNavigate={onNavigate} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /^Förslag/ }));
    expect(onNavigate).toHaveBeenLastCalledWith({
      room: "start",
      view: "suggestions",
      label: "Förslag",
    });
    fireEvent.click(screen.getByRole("button", { name: /^Automationer/ }));
    expect(onNavigate).toHaveBeenLastCalledWith(
      expect.objectContaining({ room: "start", view: "automations" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Öppna Agenda · 1 till" }),
    );
    expect(onNavigate).toHaveBeenLastCalledWith({
      room: "work",
      view: "agenda",
    });
    fireEvent.click(
      screen.getByRole("button", { name: /^Boka tid hos tandläkaren/ }),
    );
    expect(onNavigate).toHaveBeenLastCalledWith({
      room: "work",
      view: "task",
      id: homeIds.overdueOld,
      label: "Boka tid hos tandläkaren",
    });
  });

  it("opens on the inbox where the host cannot answer get_start", async () => {
    const { transport, call } = transportOf(
      { list_suggestions: () => inboxPage },
      (name) => name !== "get_start",
    );
    render(<StartRoom mode="full" transport={transport} />);
    expect(await screen.findByText("Säkra förslag (4)")).toBeTruthy();
    expect(call).not.toHaveBeenCalledWith("get_start", expect.anything());
  });

  it("keeps a suggestion page that opened the room on the inbox", () => {
    const { transport, call } = transportOf({ get_start: () => fullStart });
    render(<StartRoom mode="full" transport={transport} initial={inboxPage} />);
    expect(screen.getByText("Säkra förslag (4)")).toBeTruthy();
    expect(call).not.toHaveBeenCalledWith("get_start", expect.anything());
  });

  it("starts a ready conversation in the chat with a phrase that names it", async () => {
    const sendMessage = vi.fn(() => Promise.resolve(true));
    const { transport, call } = transportOf({ get_start: () => fullStart });
    render(
      <StartRoom mode="full" transport={transport} sendMessage={sendMessage} />,
    );
    const card = (
      await screen.findByRole("heading", { level: 3, name: "Morgonplan" })
    ).closest("article")!;
    expect(within(card).getByText("Redo sedan 07:00")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Starta" }));
    expect(sendMessage).toHaveBeenCalledWith(
      `Starta det färdiga samtalet ”Morgonplan” (${homeIds.evening}).`,
    );
    expect(await screen.findByText("Skickat till Claude")).toBeTruthy();
    // The app starts nothing itself: Claude does, with start_ready_conversation.
    expect(call).not.toHaveBeenCalledWith(
      "start_ready_conversation",
      expect.anything(),
    );
  });

  it("shows the phrase as text, with nothing to press, where the host has no messages", async () => {
    const { transport } = transportOf({ get_start: () => fullStart });
    render(<StartRoom mode="full" transport={transport} />);
    const card = (
      await screen.findByRole("heading", { level: 3, name: "Morgonplan" })
    ).closest("article")!;
    expect(within(card).queryByRole("button", { name: "Starta" })).toBeNull();
    expect(within(card).getByText("Be Claude i Claude-appen:")).toBeTruthy();
    expect(
      within(card).getByText("Starta det färdiga samtalet ”Morgonplan”"),
    ).toBeTruthy();
    expect(
      within(card).getByRole("button", { name: "Hoppa över idag" }),
    ).toBeTruthy();
  });

  it("skips a conversation once per press, and Ångra takes the skip back", async () => {
    let reads = 0;
    const { transport, call } = transportOf({
      get_start: () => {
        reads += 1;
        return reads === 1 ? fullStart : { ...fullStart, ready: undefined };
      },
      skip_ready_conversation: () => skipped,
    });
    render(<StartRoom mode="full" transport={transport} />);
    const skip = await screen.findByRole("button", { name: "Hoppa över idag" });
    fireEvent.click(skip);
    fireEvent.click(skip);
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Redo att prata" }),
      ).toBeNull(),
    );
    const skips = call.mock.calls.filter(
      ([name]) => name === "skip_ready_conversation",
    );
    expect(skips).toHaveLength(1);
    expect(skips[0]![1]).toMatchObject({ conversation_id: homeIds.evening });
    expect(skips[0]![1]).not.toHaveProperty("undo");
    expect(
      (skips[0]![1] as { idempotency_key: string }).idempotency_key,
    ).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.getByText("Hoppas över idag: Morgonplan")).toBeTruthy();
    expect(
      screen.getByRole("heading", { level: 2, name: "Måndag 23 november" }),
    ).toBe(document.activeElement);

    fireEvent.click(screen.getByRole("button", { name: "Ångra" }));
    await waitFor(() =>
      expect(
        call.mock.calls.filter(([name]) => name === "skip_ready_conversation"),
      ).toHaveLength(2),
    );
    const undo = call.mock.calls.filter(
      ([name]) => name === "skip_ready_conversation",
    )[1]![1];
    expect(undo).toMatchObject({
      conversation_id: homeIds.evening,
      undo: true,
    });
  });

  it("says a skip that failed under the card and keeps it", async () => {
    const { transport } = transportOf({
      get_start: () => fullStart,
      skip_ready_conversation: () => {
        throw new Error("down");
      },
    });
    render(<StartRoom mode="full" transport={transport} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Hoppa över idag" }),
    );
    expect(
      await screen.findByText("Det gick inte att hoppa över. Försök igen."),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Morgonplan" })).toBeTruthy();
  });

  it("offers no skip where the host has no skip tool", async () => {
    const { transport } = transportOf(
      { get_start: () => fullStart },
      (name) => name !== "skip_ready_conversation",
    );
    render(<StartRoom mode="full" transport={transport} />);
    await screen.findByRole("heading", { name: "Morgonplan" });
    expect(
      screen.queryByRole("button", { name: "Hoppa över idag" }),
    ).toBeNull();
  });

  it("shows a failed read with Försök igen, which reads again", async () => {
    let reads = 0;
    const { transport } = transportOf({
      get_start: () => {
        reads += 1;
        if (reads === 1) throw new Error("down");
        return fullStart;
      },
    });
    render(<StartRoom mode="full" transport={transport} />);
    expect(await screen.findByText("Startvyn kunde inte hämtas")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Idag")).toBeTruthy();
  });

  it("names a part that failed and says who wrote an insight a model wrote", async () => {
    const { transport } = transportOf({ get_start: () => partlyStart });
    render(
      <StartRoom mode="full" transport={transport} onNavigate={vi.fn()} />,
    );
    expect(
      await screen.findByText("Kunde inte uppdatera dagens uppgifter"),
    ).toBeTruthy();
    expect(screen.getByText("Skrivet av AI i en automation")).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: /^Automationer.*1 misslyckades idag/,
      }),
    ).toBeTruthy();
    expect(screen.queryByText("Inget som väntar på dig just nu.")).toBeNull();
  });

  it("says a quiet day once, and still leads to the agenda and the suggestions", async () => {
    const onNavigate = vi.fn();
    const { transport } = transportOf({ get_start: () => quietStart });
    render(
      <StartRoom mode="full" transport={transport} onNavigate={onNavigate} />,
    );
    expect(
      await screen.findByText("Inget som väntar på dig just nu."),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Öppna Agenda" }));
    expect(onNavigate).toHaveBeenLastCalledWith({
      room: "work",
      view: "agenda",
    });
    expect(screen.getByRole("button", { name: /^Förslag/ })).toBeTruthy();
  });

  it("reads in English", async () => {
    setLocale("en");
    const { transport } = transportOf({ get_start: () => fullStart });
    render(
      <StartRoom mode="full" transport={transport} onNavigate={vi.fn()} />,
    );
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Monday 23 November",
      }),
    ).toBeTruthy();
    expect(screen.getByText("Ready to talk")).toBeTruthy();
    expect(screen.getByText("Waiting on others")).toBeTruthy();
    expect(screen.getByText("Ask Claude in the Claude app:")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Skip today" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Open Agenda · 1 more" }),
    ).toBeTruthy();
  });
});
