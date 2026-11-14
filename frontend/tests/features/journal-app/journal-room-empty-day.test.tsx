// The journal room reads today's day on its own (mount, and Retry). The server refuses a day without
// entries as not_found: the room shows that day as empty, with no error notice. Any other failure still
// shows the error notice, and Retry can recover from it. The room is driven with a plain RoomTransport;
// no bridge is mocked.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HostToolError } from "@/features/mcp-apps/bridge";
import { shiftDate } from "@/features/journal-app/dates";
import { journalEn } from "@/features/journal-app/labels";
import { JournalRoom } from "@/features/journal-app/room";
import { ownerToday } from "@/features/mcp-apps/app-timezone";
import type { RoomTransport } from "@/features/mcp-apps/room-types";

/** A host whose get_journal_day answers come from `getDay`; any other tool is refused. */
function hostWith(getDay: () => Promise<unknown>): {
  call: ReturnType<typeof vi.fn>;
  transport: RoomTransport;
} {
  const call = vi.fn((name: string) =>
    name === "get_journal_day"
      ? getDay()
      : Promise.reject(new Error(`unexpected ${name}`)),
  );
  const transport = {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("inline"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
  } as unknown as RoomTransport;
  return { call, transport };
}

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

describe("journal room: a day without entries", () => {
  it("shows the day as empty, with no error notice, when the read says not_found", async () => {
    const { call, transport } = hostWith(() =>
      Promise.reject(new HostToolError("not_found")),
    );
    render(<JournalRoom mode="full" transport={transport} />);

    expect(
      await screen.findByText(journalEn.noEntriesToday),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Try again" }),
    ).not.toBeInTheDocument();
    expect(call).toHaveBeenCalledWith("get_journal_day", {
      journal_date: ownerToday(),
      include_content: true,
      limit: 50,
    });
  });

  it("shows another empty day with the other text, not the today text", async () => {
    const user = userEvent.setup();
    const { call, transport } = hostWith(() =>
      Promise.reject(new HostToolError("not_found")),
    );
    render(<JournalRoom mode="full" transport={transport} />);
    await screen.findByText(journalEn.noEntriesToday);

    // Yesterday is in the week that ends on today, so its day button is in the strip.
    const yesterday = document.querySelector<HTMLButtonElement>(
      `button[data-date="${shiftDate(ownerToday(), -1)}"]`,
    );
    if (!yesterday) throw new Error("No day button for yesterday");
    await user.click(yesterday);

    expect(await screen.findByText(journalEn.noEntries)).toBeInTheDocument();
    expect(
      screen.queryByText(journalEn.noEntriesToday),
    ).not.toBeInTheDocument();
    expect(call).toHaveBeenLastCalledWith("get_journal_day", {
      journal_date: shiftDate(ownerToday(), -1),
      include_content: true,
      limit: 50,
    });
  });

  it("shows the empty day inline as the glance, with no error notice", async () => {
    const { transport } = hostWith(() =>
      Promise.reject(new HostToolError("not_found")),
    );
    render(<JournalRoom mode="inline" transport={transport} />);

    // One line for an empty today, with no "0 entries" count and no "no summary" line beside it.
    expect(
      await screen.findByText("Nothing written yet today."),
    ).toBeInTheDocument();
    expect(screen.queryByText("0 entries")).not.toBeInTheDocument();
    expect(screen.queryByText(journalEn.noSummary)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the error notice for any other failure of the read", async () => {
    const { transport } = hostWith(() =>
      Promise.reject(new HostToolError("internal_error")),
    );
    render(<JournalRoom mode="full" transport={transport} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn’t load this right now");
    expect(screen.queryByText(journalEn.noEntries)).not.toBeInTheDocument();
  });

  it("Try again shows the empty day when the retry says not_found", async () => {
    const user = userEvent.setup();
    const getDay = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("internal_error"))
      .mockRejectedValueOnce(new HostToolError("not_found"));
    const { transport } = hostWith(getDay);
    render(<JournalRoom mode="full" transport={transport} />);

    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() =>
      expect(screen.getByText(journalEn.noEntriesToday)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(getDay).toHaveBeenCalledTimes(2);
  });
});

describe("journal room: an empty day asks Claude", () => {
  it("offers the example as a button when the host can send messages, and sends it on press", async () => {
    const user = userEvent.setup();
    const { transport } = hostWith(() =>
      Promise.reject(new HostToolError("not_found")),
    );
    const sendMessage = vi.fn().mockResolvedValue(true);
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        sendMessage={sendMessage}
      />,
    );

    await user.click(
      await screen.findByRole("button", {
        name: `Send to Claude: ${journalEn.tellClaudeMessage}`,
      }),
    );
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith(journalEn.tellClaudeMessage);
  });

  it("shows the example as text, with nothing to press, when the host offers no message function", async () => {
    const { transport } = hostWith(() =>
      Promise.reject(new HostToolError("not_found")),
    );
    render(<JournalRoom mode="full" transport={transport} />);

    expect(
      await screen.findByText(journalEn.noEntriesToday),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Send to Claude:/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(`“${journalEn.tellClaudeMessage}”`),
    ).toBeInTheDocument();
  });
});
