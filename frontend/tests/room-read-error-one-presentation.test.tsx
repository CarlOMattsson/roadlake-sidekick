// One read-error presentation for a whole room. Journal, Shopping and Contacts show the shared notice under the
// room's own chrome (no card with an eyebrow), always with the cause line and "Try again"; the place picker uses the
// notice's row variant. These are simulated-host tests (the room components with a plain transport), not a real Claude host.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { JournalRoom } from "@/features/journal-app/room";
import { ShoppingRoom } from "@/features/shopping-app/room";
import { ContactsRoom } from "@/features/work-app/contacts/contacts-room";
import { GroupSelect } from "@/features/work-app/hierarchy/group-select";
import {
  groupSelectLabelsEn,
  groupSelectLabelsFor,
  groupSelectLabelsSv,
} from "@/features/work-app/hierarchy/group-select-labels";
import type { RoomProps } from "@/features/mcp-apps/room-types";
import { toolResultCause } from "@/features/mcp-apps/ui/states";

const transport = {
  call: vi.fn(() => new Promise(() => undefined)),
  requestDisplayMode: vi.fn().mockResolvedValue("inline"),
  updateModelContext: vi.fn().mockResolvedValue(undefined),
} as unknown as RoomProps["transport"];

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

/** The failed first result a host hands a room: an error result that names no Sidekick code. */
const failedResult = { initial: undefined, initialError: true, resultId: 1 };

describe("toolResultCause", () => {
  it("shapes an error result as the bridge throws it, keeping Sidekick's closed code", () => {
    const cause = toolResultCause({ code: "not_found" });
    expect(cause).toBeInstanceOf(Error);
    expect(cause.name).toBe("HostToolError");
    expect((cause as Error & { code?: string }).code).toBe("not_found");
    expect(toolResultCause(undefined).name).toBe("HostToolError");
  });
});

describe.each([
  ["Journal", JournalRoom],
  ["Shopping", ShoppingRoom],
  ["Contacts", ContactsRoom],
] as const)("%s room, full view, first result is an error", (_name, Room) => {
  it("shows the notice with the cause line and Try again, without a card or eyebrow around it", async () => {
    render(<Room mode="full" transport={transport} {...failedResult} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveClass("sk-error--card");
    expect(alert.querySelector(".sk-error-hint")).toHaveTextContent(
      "Sidekick didn’t respond.",
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
    // Under the room's chrome: no card box and no room-name eyebrow of its own.
    expect(alert.closest(".sk-card")).toBeNull();
    expect(document.querySelector(".sk-eyebrow")).toBeNull();
  });
});

describe("Journal and Shopping inline", () => {
  it("keep the card that names the room around the same notice", async () => {
    render(
      <JournalRoom mode="inline" transport={transport} {...failedResult} />,
    );
    const alert = await screen.findByRole("alert");
    expect(alert.closest(".sk-card")).not.toBeNull();
    expect(document.querySelector(".sk-eyebrow")).toHaveTextContent("Journal");
    expect(alert.querySelector(".sk-error-hint")).not.toBeNull();
  });
});

describe("the place picker's failed read", () => {
  it.each([
    ["en", groupSelectLabelsEn, "Try again"],
    ["sv", groupSelectLabelsSv, "Försök igen"],
  ] as const)(
    "is the notice's row variant with a retry button (%s)",
    async (_lang, labels, retryName) => {
      const retry = vi.fn();
      render(
        <GroupSelect
          label="Place"
          value={null}
          choices={{ phase: "error", retry }}
          labels={labels}
          onChange={vi.fn()}
        />,
      );
      const alert = screen.getByRole("alert");
      expect(alert).toHaveClass("sk-error--row");
      expect(alert).toHaveTextContent(labels.failed);
      await userEvent.click(screen.getByRole("button", { name: retryName }));
      expect(retry).toHaveBeenCalledTimes(1);
    },
  );

  it("keeps the same keys in both languages and resolves them by locale", () => {
    expect(Object.keys(groupSelectLabelsSv).sort()).toEqual(
      Object.keys(groupSelectLabelsEn).sort(),
    );
    expect(groupSelectLabelsFor("sv-SE")).toBe(groupSelectLabelsSv);
    expect(groupSelectLabelsFor("en-GB")).toBe(groupSelectLabelsEn);
  });
});
