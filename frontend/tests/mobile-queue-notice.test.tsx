import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import type { FailedWrite } from "@/mobile/sidekick-native";
import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import type { MobilePlatform } from "@/mobile/platform";
import { SidekickNativeWeb } from "@/mobile/sidekick-native-web";
import {
  describeWrite,
  QueueNotice,
  queueNoticeLabelsEn,
  queueNoticeLabelsSv,
} from "@/mobile/queue-notice";
import { fakeNative, ok, type FakeNative } from "./helpers/fake-native";

const LIST_ID = "019f0000-0000-7000-8000-0000000000b1";
const ITEM_ID = "019f0000-0000-7000-8000-0000000000c1";

const REJECTED_ADD: FailedWrite = {
  key: "add-key-0001",
  kind: "add",
  reason: "rejected",
  queuedAt: Date.UTC(2026, 10, 1),
  listId: LIST_ID,
  items: [{ name: "Mjölk" }, { name: "Ost" }],
};
const EXPIRED_ADD: FailedWrite = {
  key: "add-key-0002",
  kind: "add",
  reason: "expired",
  queuedAt: Date.UTC(2026, 9, 1),
  listId: LIST_ID,
  items: [{ name: "Bröd" }],
};
const REJECTED_PURCHASE: FailedWrite = {
  key: "shop-key-0001",
  kind: "purchase",
  reason: "rejected",
  queuedAt: Date.UTC(2026, 10, 2),
  itemId: ITEM_ID,
  purchased: true,
};

function mount(native: FakeNative, locale: "sv" | "en" = "sv", key = 0) {
  return render(
    <QueueNotice native={native} locale={locale} refreshKey={key} />,
  );
}

function nativeWith(...failed: FailedWrite[]) {
  const native = fakeNative(() => ok({}));
  for (const write of failed) native.failedWrites.set(write.key, write);
  return native;
}

afterEach(cleanup);

describe("QueueNotice", () => {
  it("draws nothing when no write failed, and when the outbox cannot be read", async () => {
    const native = nativeWith();
    const { container } = mount(native);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    cleanup();

    const broken = nativeWith(REJECTED_ADD);
    broken.queuedWrites = () => Promise.reject(new Error("unavailable"));
    const second = mount(broken);
    await act(() => Promise.resolve());
    expect(second.container).toBeEmptyDOMElement();
  });

  it("says in Swedish which add could not be sent and why", async () => {
    mount(nativeWith(REJECTED_ADD, EXPIRED_ADD));
    expect(
      await screen.findByText(/Kunde inte skickas: Mjölk, Ost/),
    ).toBeVisible();
    expect(screen.getByText(/Servern tog inte emot den\./)).toBeVisible();
    expect(screen.getByText(/Kunde inte skickas: Bröd/)).toBeVisible();
    expect(screen.getByText(/Den låg i kön i över 7 dagar\./)).toBeVisible();
  });

  it("has an English text of its own", async () => {
    mount(nativeWith(REJECTED_ADD), "en");
    expect(
      await screen.findByText(/Could not be sent: Mjölk, Ost/),
    ).toBeVisible();
    expect(screen.getByText(/The server did not accept it\./)).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Try again: Mjölk, Ost" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Remove: Mjölk, Ost" }),
    ).toBeVisible();
  });

  it("retries a write: it goes back to the outbox and the line goes", async () => {
    const user = userEvent.setup();
    const native = nativeWith(REJECTED_ADD, EXPIRED_ADD);
    mount(native);
    await user.click(
      await screen.findByRole("button", { name: "Försök igen: Bröd" }),
    );
    expect(native.retryQueuedWrite).toHaveBeenCalledWith({
      key: "add-key-0002",
    });
    await waitFor(() =>
      expect(screen.queryByText(/Kunde inte skickas: Bröd/)).toBeNull(),
    );
    expect(screen.getByText(/Kunde inte skickas: Mjölk, Ost/)).toBeVisible();
  });

  it("removes a write for good", async () => {
    const user = userEvent.setup();
    const native = nativeWith(REJECTED_ADD);
    const { container } = mount(native);
    await user.click(
      await screen.findByRole("button", { name: "Ta bort: Mjölk, Ost" }),
    );
    expect(native.removeQueuedWrite).toHaveBeenCalledWith({
      key: "add-key-0001",
    });
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("offers only 'Ta bort' for a refused purchase, which would be refused again", async () => {
    mount(nativeWith(REJECTED_PURCHASE));
    expect(
      await screen.findByText(/Kunde inte skickas: en vara markerad som köpt/),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /Försök igen/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Ta bort/ })).toBeVisible();
  });

  it("offers only 'Ta bort' for a write whose key is older than the server's idempotency window", async () => {
    mount(nativeWith({ ...EXPIRED_ADD, retryable: false }));
    expect(await screen.findByText(/Kunde inte skickas: Bröd/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /Försök igen/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Ta bort/ })).toBeVisible();
  });

  it("says so when the phone answers that the write was not put back (retried: false)", async () => {
    const user = userEvent.setup();
    const native = nativeWith(REJECTED_ADD);
    native.retryQueuedWrite.mockResolvedValueOnce({ retried: false });
    mount(native);
    await user.click(
      await screen.findByRole("button", { name: /Försök igen/ }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      queueNoticeLabelsSv.notRetried,
    );
    expect(screen.getByText(/Kunde inte skickas: Mjölk, Ost/)).toBeVisible();
  });

  it("says so, in English, when the phone answers that the write was not removed (removed: false)", async () => {
    const user = userEvent.setup();
    const native = nativeWith(REJECTED_ADD);
    native.removeQueuedWrite.mockResolvedValueOnce({ removed: false });
    mount(native, "en");
    await user.click(
      await screen.findByRole("button", { name: /Remove: Mjölk, Ost/ }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      queueNoticeLabelsEn.notRemoved,
    );
  });

  it("has a short alert text in both languages for a retry or remove that did not happen", () => {
    for (const labels of [queueNoticeLabelsSv, queueNoticeLabelsEn]) {
      expect(labels.notRetried).toMatch(/\.$/);
      expect(labels.notRemoved).toMatch(/\.$/);
      expect(labels.notRetried).not.toBe(labels.notRemoved);
    }
  });

  it("says so, and keeps the line, when the retry is refused", async () => {
    const user = userEvent.setup();
    const native = nativeWith(REJECTED_ADD);
    native.retryQueuedWrite.mockRejectedValueOnce(new Error("internal"));
    mount(native);
    await user.click(
      await screen.findByRole("button", { name: /Försök igen/ }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      queueNoticeLabelsSv.actionFailed,
    );
    expect(screen.getByText(/Kunde inte skickas: Mjölk, Ost/)).toBeVisible();
    expect(screen.getByRole("button", { name: /Försök igen/ })).toBeEnabled();
  });

  it("shows a write that fails while the app is open, when a run of the outbox ends", async () => {
    const native = nativeWith();
    mount(native);
    await act(() => Promise.resolve());
    expect(screen.queryByRole("status")).toBeNull();

    native.failedWrites.set(REJECTED_ADD.key, REJECTED_ADD);
    act(() => native.runOutbox([]));

    expect(
      await screen.findByText(/Kunde inte skickas: Mjölk, Ost/),
    ).toBeVisible();
  });

  it("reads again when the app comes back", async () => {
    const native = nativeWith();
    const view = mount(native);
    await act(() => Promise.resolve());
    native.failedWrites.set(REJECTED_ADD.key, REJECTED_ADD);

    view.rerender(<QueueNotice native={native} locale="sv" refreshKey={1} />);

    expect(
      await screen.findByText(/Kunde inte skickas: Mjölk, Ost/),
    ).toBeVisible();
  });

  it("names a long add by three items and the count of the rest", () => {
    const write: FailedWrite = {
      ...REJECTED_ADD,
      items: ["A", "B", "C", "D", "E"].map((name) => ({ name })),
    };
    expect(describeWrite(write, queueNoticeLabelsSv)).toBe(
      "A, B, C och 2 till",
    );
    expect(describeWrite(write, queueNoticeLabelsEn)).toBe(
      "A, B, C and 2 more",
    );
    expect(
      describeWrite({ ...write, items: [{ name: " " }] }, queueNoticeLabelsSv),
    ).toBe("varor");
  });

  it("keeps the Swedish and English texts in step", () => {
    expect(Object.keys(queueNoticeLabelsEn)).toEqual(
      Object.keys(queueNoticeLabelsSv),
    );
  });
});

describe("the web implementation", () => {
  it("has no failed writes and nothing to retry or remove", async () => {
    const web = new SidekickNativeWeb();
    await expect(web.queuedWrites()).resolves.toMatchObject({ failed: [] });
    await expect(web.retryQueuedWrite()).resolves.toEqual({ retried: false });
    await expect(web.removeQueuedWrite()).resolves.toEqual({ removed: false });
  });
});

describe("QueueNotice in the mobile app", () => {
  it("is drawn over the rooms while a write has failed", async () => {
    const native = nativeWith(REJECTED_ADD);
    const platform: MobilePlatform = {
      onBack: () => () => undefined,
      launchSearch: () => "",
      onLaunchSearch: () => () => undefined,
      onResume: () => () => undefined,
      safeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }),
    };
    render(
      <MobileApp
        transport={new CompanionRoomTransport(native)}
        platform={platform}
        locale="sv"
        native={native}
      />,
    );
    expect(
      await screen.findByText(/Kunde inte skickas: Mjölk, Ost/),
    ).toBeVisible();
  });
});
