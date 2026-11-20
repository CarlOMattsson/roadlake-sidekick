import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import { PairingGate } from "@/mobile/pairing-gate";
import { PhoneTrash } from "@/mobile/phone-trash";
import type { MobilePlatform } from "@/mobile/platform";
import type { NativeRequest } from "@/mobile/sidekick-native";
import { fakeNative, ok, type FakeNative } from "@tests/helpers/fake-native";

const TASK_ID = "019f0000-0000-7000-8000-000000000101";
const NOTE_ID = "019f0000-0000-7000-8000-000000000102";

const AGENDA = {
  items: [
    {
      kind: "task",
      id: "019f0000-0000-7000-8000-0000000000a1",
      title: "Skicka offert",
      status: "todo",
      due_at: null,
      version: 1,
      agenda_group: "overdue",
    },
  ],
  filters: {},
  next_cursor: null,
};

const TRASH = {
  items: [
    {
      kind: "task",
      id: TASK_ID,
      label: "Förbered pitchen",
      trashed_at: "2026-11-07T13:30:00Z",
      version: 4,
    },
    {
      kind: "journal_entry",
      id: NOTE_ID,
      label: "Kort dagbok",
      trashed_at: "2026-11-07T13:30:00Z",
      version: 2,
    },
  ],
  has_more: false,
  next_cursor: null,
  can_erase: true,
};

/**
 * What the server answers; `trashFails` makes the first read of the trash fail, and `mayErase: false` is a device
 * without `companion:work:erase`.
 */
function server(options: { trashFails?: boolean; mayErase?: boolean } = {}) {
  let failed = false;
  return (request: NativeRequest) => {
    if (request.path === "/companion/v1/work/agenda") return ok(AGENDA);
    if (request.path === "/companion/v1/trash") {
      if (options.trashFails && !failed) {
        failed = true;
        return { status: 503, body: { code: "unavailable" } };
      }
      return ok({ ...TRASH, can_erase: options.mayErase ?? true });
    }
    if (request.path === `/companion/v1/tasks/${TASK_ID}/untrash`)
      return ok({ kind: "task", id: TASK_ID, version: 5 });
    if (request.path === `/companion/v1/tasks/${TASK_ID}/erase`)
      return ok({ removed: true });
    if (request.path === "/companion/v1/trash/empty")
      return ok({ removed: 1, kept: 0 });
    return { status: 404, body: { code: "not_found" } };
  };
}

function platformFor(): MobilePlatform & { pressBack: () => boolean } {
  let back: (() => boolean) | undefined;
  return {
    onBack: (handler) => {
      back = handler;
      // Like the native stack: leaving removes only what this call registered.
      return () => {
        if (back === handler) back = undefined;
      };
    },
    launchSearch: () => "",
    onLaunchSearch: () => () => undefined,
    onResume: () => () => undefined,
    safeAreaInsets: () => undefined,
    pressBack: () => back?.() ?? false,
  };
}

function app(native: FakeNative) {
  const platform = platformFor();
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

async function openTrash(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("Skicka offert");
  await user.click(screen.getByRole("button", { name: "Fler val" }));
  await user.click(screen.getByRole("button", { name: "Inställningar" }));
  await user.click(
    await screen.findByRole("button", { name: "Papperskorgen" }),
  );
}

const writes = (native: FakeNative) =>
  native.requests.filter((request) => request.method === "POST");

afterEach(() => cleanup());

describe("the phone's trash screen", () => {
  it("opens from a row in the settings and reads the trash", async () => {
    const user = userEvent.setup();
    const native = fakeNative(server());
    app(native);

    await openTrash(user);

    expect(await screen.findByText("Förbered pitchen")).toBeVisible();
    expect(screen.getByText("Kort dagbok")).toBeVisible();
    expect(
      native.requests.some((request) => request.path === "/companion/v1/trash"),
    ).toBe(true);
    // Back names where it leads.
    expect(
      screen.getByRole("button", { name: /Inställningar$/ }),
    ).toBeVisible();
  });

  it("offers deleting for good for the task only, and Töm papperskorgen", async () => {
    const user = userEvent.setup();
    app(fakeNative(server()));

    await openTrash(user);
    await screen.findByText("Förbered pitchen");

    expect(
      screen.getByRole("button", { name: "Radera Förbered pitchen för gott" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /Radera Kort dagbok/ }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "Töm papperskorgen" }),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Dagboksinlägg och varor kan inte raderas för gott, bara återställas.",
      ),
    ).toBeVisible();
  });

  it("offers no deleting for good or emptying to a device without the right", async () => {
    const user = userEvent.setup();
    app(fakeNative(server({ mayErase: false })));

    await openTrash(user);
    await screen.findByText("Förbered pitchen");

    expect(
      screen.getByRole("button", { name: "Återställ Förbered pitchen" }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /Radera / })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Töm papperskorgen" }),
    ).toBeNull();
  });

  it("restores a row with the version the list showed", async () => {
    const user = userEvent.setup();
    const native = fakeNative(server());
    app(native);

    await openTrash(user);
    await user.click(
      await screen.findByRole("button", { name: "Återställ Förbered pitchen" }),
    );

    await waitFor(() =>
      expect(writes(native).map((request) => request.path)).toEqual([
        `/companion/v1/tasks/${TASK_ID}/untrash`,
      ]),
    );
    expect(writes(native)[0]?.body).toEqual({ version: 4 });
    expect(
      await screen.findByText("Återställd: Förbered pitchen"),
    ).toBeVisible();
  });

  it("sends nothing to delete until the owner says yes, then sends confirm", async () => {
    const user = userEvent.setup();
    const native = fakeNative(server());
    app(native);

    await openTrash(user);
    await user.click(
      await screen.findByRole("button", {
        name: "Radera Förbered pitchen för gott",
      }),
    );
    expect(writes(native)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(writes(native)).toEqual([]);

    await user.click(
      screen.getByRole("button", { name: "Radera Förbered pitchen för gott" }),
    );
    await user.click(screen.getByRole("button", { name: "Radera" }));

    await waitFor(() => expect(writes(native)).toHaveLength(1));
    expect(writes(native)[0]).toMatchObject({
      path: `/companion/v1/tasks/${TASK_ID}/erase`,
      body: { version: 4, confirm: true },
    });
  });

  it("shows a failed first read with Försök igen", async () => {
    const user = userEvent.setup();
    app(fakeNative(server({ trashFails: true })));

    await openTrash(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Papperskorgen kunde inte läsas.",
    );
    await user.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Förbered pitchen")).toBeVisible();
  });

  it("closes with system Back first, then the settings, then the rooms", async () => {
    const user = userEvent.setup();
    const platform = app(fakeNative(server()));
    await openTrash(user);
    await screen.findByText("Förbered pitchen");

    await waitFor(() => expect(platform.pressBack()).toBe(true));
    // The settings stand again, the trash is gone.
    expect(
      await screen.findByRole("button", { name: "Papperskorgen" }),
    ).toBeVisible();
    expect(screen.queryByText("Förbered pitchen")).toBeNull();
    expect(
      screen.getByRole("heading", { name: "Inställningar" }),
    ).toBeVisible();

    await waitFor(() => expect(platform.pressBack()).toBe(true));
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Inställningar" }),
      ).toBeNull(),
    );
    expect(screen.getByText("Skicka offert")).toBeVisible();
  });

  it("closes with ‹ Inställningar and gives the focus back to its row", async () => {
    const user = userEvent.setup();
    app(fakeNative(server()));
    await openTrash(user);
    await screen.findByText("Förbered pitchen");

    await user.click(screen.getByRole("button", { name: /Inställningar$/ }));

    const row = await screen.findByRole("button", { name: "Papperskorgen" });
    await waitFor(() => expect(row).toHaveFocus());
  });

  it("is in English with an English app", async () => {
    // The screen on its own: the rooms' menu words follow the document, the screen follows the app's language.
    const native = fakeNative(server());
    render(
      <PhoneTrash
        transport={new CompanionRoomTransport(native)}
        locale="en"
        onBack={() => undefined}
        onChanged={() => undefined}
      />,
    );

    expect(screen.getByRole("heading", { name: "Trash" })).toBeVisible();
    expect(
      await screen.findByRole("button", {
        name: "Delete Förbered pitchen permanently",
      }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Empty the trash" }),
    ).toBeVisible();
  });
});
