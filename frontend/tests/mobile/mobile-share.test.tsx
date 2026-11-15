import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import { PairingGate } from "@/mobile/pairing-gate";
import type { MobilePlatform } from "@/mobile/platform";
import { shareLabelsEn, shareLabelsSv } from "@/mobile/share-labels";
import { ShareSheet } from "@/mobile/share-sheet";
import type { SharedText } from "@/mobile/sidekick-native";
import { useIncomingShare } from "@/mobile/use-incoming-share";
import {
  fakeNative,
  nativeError,
  ok,
  type FakeNative,
} from "@tests/helpers/fake-native";

const ARTICLE: SharedText = {
  title: "How the harbour was built",
  text: "https://example.org/article",
  link: "https://example.org/article",
};

const TASK = {
  task: { id: "019f0000-0000-7000-8000-0000000000a2", version: 1 },
};
const ENTRY = {
  entry: { id: "019f0000-0000-7000-8000-0000000000e2", version: 1 },
};

afterEach(cleanup);

function nativeThatSaves() {
  return fakeNative((request) =>
    request.path === "/companion/v1/tasks" ? ok(TASK) : ok(ENTRY),
  );
}

function mount(
  native: FakeNative,
  share: SharedText = ARTICLE,
  locale: "sv" | "en" = "sv",
  onClose: () => void = () => undefined,
) {
  return render(
    <ShareSheet
      transport={new CompanionRoomTransport(native)}
      share={share}
      locale={locale}
      onClose={onClose}
    />,
  );
}

describe("ShareSheet", () => {
  it("saves a task with the shared title, the text (which holds the link) as its note, and one idempotency key", async () => {
    const user = userEvent.setup();
    const native = nativeThatSaves();
    mount(native);

    expect(screen.getByLabelText("Titel")).toHaveValue(
      "How the harbour was built",
    );
    expect(screen.getByText("https://example.org/article")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Spara" }));

    expect(await screen.findByText("Sparad som uppgift.")).toBeVisible();
    expect(native.requests).toHaveLength(1);
    expect(native.requests[0]).toMatchObject({
      method: "POST",
      path: "/companion/v1/tasks",
      body: {
        title: "How the harbour was built",
        description: "https://example.org/article",
      },
    });
    expect(native.requests[0]?.idempotencyKey).toBeTruthy();
  });

  it("lets the owner edit the title, which keeps the shared text as the note", async () => {
    const user = userEvent.setup();
    const native = nativeThatSaves();
    mount(native, { title: "Buy flowers", text: "Buy flowers" });

    const field = screen.getByLabelText("Titel");
    await user.clear(field);
    await user.type(field, "Buy tulips");
    await user.click(screen.getByRole("button", { name: "Spara" }));

    await screen.findByText("Sparad som uppgift.");
    expect(native.requests[0]?.body).toEqual({
      title: "Buy tulips",
      description: "Buy flowers",
    });
  });

  it("leaves out a note that only repeats the title", async () => {
    const user = userEvent.setup();
    const native = nativeThatSaves();
    mount(native, { title: "Buy flowers", text: "Buy flowers" });

    await user.click(screen.getByRole("button", { name: "Spara" }));

    await screen.findByText("Sparad som uppgift.");
    expect(native.requests[0]?.body).toEqual({ title: "Buy flowers" });
  });

  it("adds the text to today's journal as a new entry on the owner's date", async () => {
    const user = userEvent.setup();
    const native = nativeThatSaves();
    mount(native);

    await user.click(screen.getByRole("button", { name: "Dagens dagbok" }));
    await user.click(screen.getByRole("button", { name: "Spara" }));

    expect(await screen.findByText("Tillagd i dagens dagbok.")).toBeVisible();
    expect(native.requests[0]).toMatchObject({
      method: "POST",
      path: "/companion/v1/journal/entries",
      body: {
        title: "How the harbour was built",
        source_text: "https://example.org/article",
      },
    });
    expect(
      (native.requests[0]?.body as { journal_date: string }).journal_date,
    ).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("keeps the text and the choice when no answer comes and the outbox cannot keep it, and the retry sends the same key", async () => {
    const user = userEvent.setup();
    let calls = 0;
    const native = fakeNative(() => {
      calls += 1;
      if (calls === 1) throw nativeError("network", 0);
      return ok(ENTRY);
    });
    native.queueRecordWrite.mockResolvedValue({ queued: false });
    mount(native);

    await user.click(screen.getByRole("button", { name: "Dagens dagbok" }));
    await user.clear(screen.getByLabelText("Titel"));
    await user.type(screen.getByLabelText("Titel"), "Harbour notes");
    await user.click(screen.getByRole("button", { name: "Spara" }));

    expect(
      await screen.findByText("Det gick inte att spara. Texten finns kvar."),
    ).toBeVisible();
    expect(screen.getByLabelText("Titel")).toHaveValue("Harbour notes");
    expect(
      screen.getByRole("button", { name: "Dagens dagbok" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("https://example.org/article")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Spara" }));
    expect(await screen.findByText("Tillagd i dagens dagbok.")).toBeVisible();
    const keys = native.requests.map((request) => request.idempotencyKey);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });

  it("puts the entry in the phone's outbox when no answer comes, and says it waits", async () => {
    const user = userEvent.setup();
    const native = fakeNative(() => {
      throw nativeError("network", 0);
    });
    mount(native);

    await user.click(screen.getByRole("button", { name: "Dagens dagbok" }));
    await user.click(screen.getByRole("button", { name: "Spara" }));

    expect(await screen.findByText(shareLabelsSv.savedQueued)).toBeVisible();
    const [kept] = [...native.records.values()];
    expect(kept).toMatchObject({
      kind: "write_journal_entry",
      generation: 0,
      body: { source_text: "https://example.org/article" },
    });
    expect(kept?.idempotencyKey).toBe(native.requests[0]?.idempotencyKey);
  });

  it("asks for a title instead of sending an empty one", async () => {
    const user = userEvent.setup();
    const native = nativeThatSaves();
    mount(native, { title: "", text: "Something worth keeping" });

    await user.click(screen.getByRole("button", { name: "Spara" }));

    expect(await screen.findByText("Skriv en titel.")).toBeVisible();
    expect(native.requests).toEqual([]);
  });

  it("offers a text that is only a subject, and cancels without writing", async () => {
    const user = userEvent.setup();
    const native = nativeThatSaves();
    let closed = 0;
    mount(native, { title: "Meeting notes", text: "" }, "sv", () => {
      closed += 1;
    });

    expect(screen.queryByText("Delad text")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Avbryt" }));

    expect(closed).toBe(1);
    expect(native.requests).toEqual([]);
  });

  it("closes with Done after a save, and with Escape", async () => {
    const user = userEvent.setup();
    let closed = 0;
    mount(nativeThatSaves(), ARTICLE, "sv", () => {
      closed += 1;
    });

    await user.keyboard("{Escape}");
    expect(closed).toBe(1);
    await user.click(screen.getByRole("button", { name: "Spara" }));
    await user.click(await screen.findByRole("button", { name: "Klar" }));
    expect(closed).toBe(2);
  });

  it("speaks English with the same set of texts", async () => {
    expect(Object.keys(shareLabelsEn)).toEqual(Object.keys(shareLabelsSv));
    const user = userEvent.setup();
    mount(nativeThatSaves(), ARTICLE, "en");

    expect(
      screen.getByRole("heading", { name: "Share to Sidekick" }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved as a task.")).toBeVisible();
  });
});

function platform(): MobilePlatform & { pressBack: () => boolean } {
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

/** The app as main.tsx wires it: the share is held above the pairing gate and handed to the app. */
function App({
  native,
  host,
}: {
  native: FakeNative;
  host: ReturnType<typeof platform>;
}) {
  const incoming = useIncomingShare(native);
  return (
    <PairingGate
      native={native}
      platform={host}
      locale="sv"
      shareNote={incoming.share ? shareLabelsSv.needsPairing : undefined}
    >
      <MobileApp
        transport={new CompanionRoomTransport(native)}
        platform={host}
        locale="sv"
        share={incoming.share}
        onShareClosed={incoming.clear}
      />
    </PairingGate>
  );
}

const AGENDA = { items: [], filters: {}, next_cursor: null };

describe("a share into the app", () => {
  it("opens the sheet over the app for a share that was waiting at the start, and system Back leaves it", async () => {
    const native = fakeNative((request) =>
      request.path === "/companion/v1/work/agenda" ? ok(AGENDA) : ok({}),
    );
    native.receiveShare(ARTICLE);
    const host = platform();
    render(<App native={native} host={host} />);

    expect(
      await screen.findByRole("heading", { name: "Dela till Sidekick" }),
    ).toBeVisible();
    act(() => {
      expect(host.pressBack()).toBe(true);
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Dela till Sidekick" }),
      ).toBeNull(),
    );
    expect(native.requests.every((request) => request.method === "GET")).toBe(
      true,
    );
  });

  it("opens the sheet for a share that arrives while the app runs", async () => {
    const native = fakeNative((request) =>
      request.path === "/companion/v1/work/agenda" ? ok(AGENDA) : ok({}),
    );
    render(<App native={native} host={platform()} />);
    await waitFor(() => expect(native.takeShare).toHaveBeenCalled());

    act(() => native.receiveShare(ARTICLE));

    expect(
      await screen.findByRole("heading", { name: "Dela till Sidekick" }),
    ).toBeVisible();
    expect(screen.getByLabelText("Titel")).toHaveValue(
      "How the harbour was built",
    );
  });

  it("tells an unpaired phone to connect first, keeps the text, and opens the sheet once paired", async () => {
    const user = userEvent.setup();
    const native = fakeNative(
      (request) =>
        request.path === "/companion/v1/work/agenda" ? ok(AGENDA) : ok({}),
      { paired: false },
    );
    native.receiveShare(ARTICLE);
    render(<App native={native} host={platform()} />);

    expect(await screen.findByText(shareLabelsSv.needsPairing)).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "Dela till Sidekick" }),
    ).toBeNull();

    await user.type(screen.getByLabelText("Serveradress"), "sidekick.example");
    await user.type(
      screen.getByLabelText("Kopplingskod"),
      "rspair_abcdefghijklmnop",
    );
    await user.click(screen.getByRole("button", { name: "Koppla" }));

    expect(
      await screen.findByRole("heading", { name: "Dela till Sidekick" }),
    ).toBeVisible();
    expect(screen.getByLabelText("Titel")).toHaveValue(
      "How the harbour was built",
    );
  });
});
