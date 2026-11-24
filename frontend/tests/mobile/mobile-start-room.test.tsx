// The Start room in the mobile app: the home view and the suggestion inbox over the companion routes. The native plugin
// and the platform are simulated; this is not a real Android run or a real Claude host.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import { PairingGate } from "@/mobile/pairing-gate";
import type { NativeRequest } from "@/mobile/sidekick-native";
import { fakeNative, ok, type FakeNative } from "@tests/helpers/fake-native";
import { simulatedPlatform } from "@tests/helpers/mobile-platform";
import { fullStart } from "@tests/e2e/start-home-fixtures";
import {
  groupItems,
  inboxPage,
  reviewItems,
  sid,
} from "@tests/e2e/suggestions-fixtures";

const AGENDA = { items: [], filters: {}, next_cursor: null };
const DIGEST = "a".repeat(64);

/** A group of the first two safe cards, so "Godkänn alla 2" sends the server's own group. */
const SMALL_GROUP = {
  ...inboxPage,
  items: [...groupItems.slice(0, 2), ...reviewItems],
  groups: [
    {
      ...inboxPage.groups[0]!,
      count: 2,
      suggestion_ids: [sid(1), sid(2)],
    },
  ],
};

/** What the server answers; `decideRefused` is a device without `companion:suggestions:decide`. */
function server(options: { decideRefused?: boolean } = {}) {
  return (request: NativeRequest) => {
    if (request.path === "/companion/v1/work/agenda") return ok(AGENDA);
    if (request.path === "/companion/v1/start") return ok(fullStart);
    if (request.path === "/companion/v1/suggestions") return ok(SMALL_GROUP);
    if (
      options.decideRefused &&
      request.path === "/companion/v1/suggestions/decisions"
    )
      return {
        status: 403,
        body: { code: "forbidden", reason: "capability_missing" },
      };
    if (request.path === "/companion/v1/suggestions/group-approvals")
      return ok({
        items: [sid(1), sid(2)].map((id) => ({
          suggestion_id: id,
          state: "applied",
          version: 2,
          error_code: null,
          applied: null,
        })),
      });
    return { status: 404, body: { code: "not_found" } };
  };
}

function app(native: FakeNative) {
  const platform = simulatedPlatform();
  render(
    <PairingGate native={native} platform={platform} locale="sv">
      <MobileApp
        transport={new CompanionRoomTransport(native)}
        platform={platform}
        locale="sv"
        native={native}
      />
    </PairingGate>,
  );
  return platform;
}

async function openStart(user: ReturnType<typeof userEvent.setup>) {
  const strip = await screen.findByRole("navigation", { name: "Rum" });
  await user.click(
    Array.from(strip.querySelectorAll("button")).find(
      (button) => button.textContent === "Start",
    )!,
  );
}

const calls = (native: FakeNative, method: string) =>
  native.requests.filter((request) => request.method === method);

afterEach(() => cleanup());

describe("the Start room on the phone", () => {
  it("is the first cell of the room strip, before Arbete", async () => {
    app(fakeNative(server()));

    const strip = await screen.findByRole("navigation", { name: "Rum" });
    expect(
      Array.from(strip.querySelectorAll("button")).map((b) => b.textContent),
    ).toEqual(["Start", "Arbete", "Dagbok", "Inköp"]);
  });

  it("reads get_start through the transport and shows the day's rows", async () => {
    const user = userEvent.setup();
    const native = fakeNative(server());
    app(native);

    await openStart(user);

    expect(await screen.findByText("Boka tid hos tandläkaren")).toBeVisible();
    expect(screen.getByText("Skicka offerten till Lena")).toBeVisible();
    expect(calls(native, "GET").map((request) => request.path)).toContain(
      "/companion/v1/start",
    );
  });

  it("shows a ready conversation as a phrase to ask Claude, with nothing to press that fails", async () => {
    const user = userEvent.setup();
    const native = fakeNative(server());
    app(native);

    await openStart(user);
    await screen.findByText("Morgonplan");

    // The phone has no message to send and no skip tool: the card offers neither start nor skip.
    expect(screen.queryByRole("button", { name: "Starta" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Hoppa över/ })).toBeNull();
    expect(
      screen.getByText("Starta det färdiga samtalet ”Morgonplan”"),
    ).toBeVisible();
    // The automations are not on the phone: no entry to them.
    expect(screen.queryByRole("button", { name: /^Automationer/ })).toBeNull();
    expect(calls(native, "POST")).toEqual([]);
  });

  it("approves the server's group through the transport with its digest and a key", async () => {
    const user = userEvent.setup();
    const native = fakeNative(server());
    app(native);

    await openStart(user);
    await user.click(
      await screen.findByRole("button", {
        name: /^Förslag.*väntar på ditt svar$/,
      }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Godkänn alla 2" }),
    );

    await waitFor(() => expect(calls(native, "POST")).toHaveLength(1));
    const [write] = calls(native, "POST");
    expect(write?.path).toBe("/companion/v1/suggestions/group-approvals");
    expect(write?.body).toEqual({
      group_digest: DIGEST,
      suggestion_ids: [sid(1), sid(2)],
    });
    expect(write?.idempotencyKey).toBeTruthy();
  });

  it("system Back leaves the inbox for the home view, then the app's own handler", async () => {
    const user = userEvent.setup();
    const native = fakeNative(server());
    const platform = app(native);

    await openStart(user);
    await user.click(
      await screen.findByRole("button", {
        name: /^Förslag.*väntar på ditt svar$/,
      }),
    );
    await screen.findByRole("button", { name: "Godkänn alla 2" });

    expect(platform.pressBack()).toBe(true);
    expect(await screen.findByText("Boka tid hos tandläkaren")).toBeVisible();
  });

  it("shows a refused decision (no capability) as the room's own failure line, without a crash", async () => {
    const user = userEvent.setup();
    const native = fakeNative(server({ decideRefused: true }));
    app(native);

    await openStart(user);
    await user.click(
      await screen.findByRole("button", {
        name: /^Förslag.*väntar på ditt svar$/,
      }),
    );
    const approve = await screen.findAllByRole("button", { name: "Godkänn" });
    await user.click(approve.at(-1)!);

    expect(
      await screen.findByText("Det gick inte att godkänna. Försök igen."),
    ).toBeVisible();
    // The inbox is still there to try again or to dismiss.
    expect(
      screen.getAllByRole("button", { name: "Godkänn" }).length,
    ).toBeGreaterThan(0);
  });
});
