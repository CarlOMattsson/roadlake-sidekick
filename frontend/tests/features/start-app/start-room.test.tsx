import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { StartRoom } from "@/features/start-app/room";
import {
  details,
  emptyPage,
  inboxPage,
  sid,
} from "../../e2e/suggestions-fixtures";

type Answers = Record<string, (args: Record<string, unknown>) => unknown>;

function transportOf(answers: Answers) {
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

afterEach(() => {
  document.head
    .querySelectorAll('meta[name="sidekick-app-locale"]')
    .forEach((meta) => meta.remove());
});

describe("the Start room's inbox", () => {
  it("reads the inbox when nothing came with it, and shows the group and the cards", async () => {
    const { transport, call } = transportOf({
      list_suggestions: () => inboxPage,
    });
    render(
      <StartRoom
        mode="full"
        view="suggestions"
        transport={transport}
        onNavigate={vi.fn()}
      />,
    );
    expect(await screen.findByText("Säkra förslag (4)")).toBeTruthy();
    expect(screen.getByText("Att granska (3)")).toBeTruthy();
    expect(call).toHaveBeenCalledWith("list_suggestions", { limit: 25 });
    // A suspicious card offers Granska, never Godkänn.
    expect(screen.getAllByRole("button", { name: "Granska" })).toHaveLength(1);
  });

  it("says when there is nothing to decide", () => {
    const { transport } = transportOf({ list_suggestions: () => emptyPage });
    render(<StartRoom mode="full" transport={transport} initial={emptyPage} />);
    expect(screen.getByText("Inga förslag just nu.")).toBeTruthy();
  });

  it("shows a failed read with Försök igen, which reads again", async () => {
    let calls = 0;
    const { transport } = transportOf({
      list_suggestions: () => {
        calls += 1;
        if (calls === 1) throw new Error("down");
        return inboxPage;
      },
    });
    render(<StartRoom mode="full" view="suggestions" transport={transport} />);
    expect(await screen.findByText("Förslagen kunde inte hämtas")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Säkra förslag (4)")).toBeTruthy();
  });

  it("approves one card at its version and offers Ångra, which undoes it", async () => {
    const { transport, call } = transportOf({
      list_suggestions: () => inboxPage,
      decide_suggestions: () => ({
        items: [
          {
            suggestion_id: sid(7),
            state: "applied",
            version: 2,
            error_code: null,
            applied: { id: sid(707), kind: "task" },
          },
        ],
      }),
      undo_suggestion: () => ({
        suggestion_id: sid(7),
        state: "undone",
        version: 3,
        trashed: { id: sid(707), kind: "task" },
      }),
    });
    render(<StartRoom mode="full" transport={transport} initial={inboxPage} />);
    const approve = screen.getAllByRole("button", { name: "Godkänn" }).at(-1)!;
    fireEvent.click(approve);
    expect(
      await screen.findByText("Tillagd: Svara Erik om hyresgästen"),
    ).toBeTruthy();
    const decide = call.mock.calls.find(
      ([name]) => name === "decide_suggestions",
    );
    expect((decide?.[1] as { items: unknown }).items).toEqual([
      { suggestion_id: sid(7), expected_version: 1, decision: "approve" },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Ångra" }));
    await waitFor(() =>
      expect(
        call.mock.calls.find(([name]) => name === "undo_suggestion")?.[1],
      ).toMatchObject({ suggestion_id: sid(7), expected_version: 2 }),
    );
  });

  it("puts the server's words for a refused approval under the card", async () => {
    const { transport } = transportOf({
      list_suggestions: () => inboxPage,
      decide_suggestions: () => ({
        items: [
          {
            suggestion_id: sid(7),
            state: "pending",
            version: 1,
            error_code: "apply_error:conflict",
            applied: null,
          },
        ],
      }),
    });
    render(<StartRoom mode="full" transport={transport} initial={inboxPage} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Godkänn" }).at(-1)!);
    expect(
      await screen.findByText(
        "Något har ändrats sedan förslaget kom. Uppdatera och försök igen.",
      ),
    ).toBeTruthy();
  });

  it("approves at most three of a larger group, card by card at their versions", async () => {
    const { transport, call } = transportOf({
      list_suggestions: () => inboxPage,
      decide_suggestions: (args) => ({
        items: (args.items as { suggestion_id: string }[]).map((item) => ({
          suggestion_id: item.suggestion_id,
          state: "applied",
          version: 2,
          error_code: null,
          applied: null,
        })),
      }),
    });
    render(<StartRoom mode="full" transport={transport} initial={inboxPage} />);
    fireEvent.click(screen.getByRole("button", { name: "Godkänn 3" }));
    expect(await screen.findAllByText("Godkända: 3 förslag")).not.toHaveLength(
      0,
    );
    const decide = call.mock.calls.find(
      ([name]) => name === "decide_suggestions",
    )![1] as { items: unknown };
    expect(decide.items).toEqual(
      [1, 2, 3].map((n) => ({
        suggestion_id: sid(n),
        expected_version: 1,
        decision: "approve",
      })),
    );
    // Only the server's whole group goes with its digest.
    expect(
      call.mock.calls.some(([name]) => name === "approve_suggestion_group"),
    ).toBe(false);
  });

  it("sends the server's own digest when the owner approves exactly its group", async () => {
    const small = {
      ...inboxPage,
      groups: [
        {
          ...inboxPage.groups[0]!,
          count: 2,
          suggestion_ids: [sid(1), sid(2)],
        },
      ],
    };
    const { transport, call } = transportOf({
      list_suggestions: () => small,
      approve_suggestion_group: () => ({ items: [] }),
    });
    render(<StartRoom mode="full" transport={transport} initial={small} />);
    fireEvent.click(screen.getByRole("button", { name: "Godkänn alla 2" }));
    await waitFor(() =>
      expect(
        call.mock.calls.find(
          ([name]) => name === "approve_suggestion_group",
        )?.[1],
      ).toMatchObject({ group_digest: "a".repeat(64) }),
    );
  });

  it("is English where the app's language is", () => {
    setLocale("en");
    const { transport } = transportOf({ list_suggestions: () => inboxPage });
    render(<StartRoom mode="full" transport={transport} initial={inboxPage} />);
    expect(screen.getByText("Safe suggestions (4)")).toBeTruthy();
    expect(screen.getByText("To review (3)")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve 3" })).toBeTruthy();
  });
});

describe("the Start room's other views", () => {
  it("reads one suggestion by id and shows its detail with the quote", async () => {
    const { transport, call } = transportOf({
      get_suggestion: () => ({ suggestion: details[sid(5)] }),
    });
    render(
      <StartRoom
        mode="full"
        view="suggestion"
        transport={transport}
        initial={{ suggestion: { id: sid(5) } }}
      />,
    );
    expect(await screen.findByText("Skapa kontakt: Lena Holm")).toBeTruthy();
    expect(call).toHaveBeenCalledWith("get_suggestion", {
      suggestion_id: sid(5),
    });
    expect(
      screen.getByText("Ur mejlet, inte skrivet av Sidekick"),
    ).toBeTruthy();
    expect(screen.getByText("Kontrollen var osäker")).toBeTruthy();
  });

  it("shows the inline card with one group and the way to the inbox", () => {
    const { transport } = transportOf({});
    render(
      <StartRoom
        mode="inline"
        transport={transport}
        initial={inboxPage}
        fullscreenAvailable
      />,
    );
    expect(screen.getByText("4 säkra förslag")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Öppna Förslag/ })).toBeTruthy();
    expect(screen.queryByText("Att granska (3)")).toBeNull();
  });

  it("shows what Claude decided as a receipt card", () => {
    const { transport } = transportOf({});
    render(
      <StartRoom
        mode="inline"
        view="decided"
        transport={transport}
        initial={{
          items: [
            {
              suggestion_id: sid(1),
              state: "applied",
              version: 2,
              error_code: null,
              applied: null,
            },
            {
              suggestion_id: sid(2),
              state: "pending",
              version: 1,
              error_code: "needs_app",
              applied: null,
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("1 godkänt")).toBeTruthy();
    expect(screen.getByText("1 togs inte")).toBeTruthy();
  });
});
