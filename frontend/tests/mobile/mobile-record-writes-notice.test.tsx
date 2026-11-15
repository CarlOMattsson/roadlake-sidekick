import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  describeWrite,
  QueueNotice,
  queueNoticeLabelsEn,
  queueNoticeLabelsSv,
  type QueueNoticeLabels,
} from "@/mobile/queue-notice";
import type { FailedWrite, RecordWriteKind } from "@/mobile/sidekick-native";
import { fakeNative, ok } from "@tests/helpers/fake-native";

// A Task, Project or journal entry that could not be sent keeps the words the user wrote on its line, so they can be copied
// away before the write is removed.

const KINDS: readonly {
  kind: RecordWriteKind;
  label: keyof QueueNoticeLabels;
}[] = [
  { kind: "create_task", label: "createTask" },
  { kind: "update_task", label: "updateTask" },
  { kind: "update_project", label: "updateProject" },
  { kind: "write_journal_entry", label: "writeJournal" },
  { kind: "update_journal_entry", label: "updateJournal" },
];

const LOCALES = [
  { locale: "sv", labels: queueNoticeLabelsSv },
  { locale: "en", labels: queueNoticeLabelsEn },
] as const;

const TITLE = "Ring revisorn";
const TEXT = "Fråga om bokslutet och be om offert.";

function failed(
  kind: RecordWriteKind,
  reason: FailedWrite["reason"],
  over: Partial<FailedWrite> = {},
): FailedWrite {
  return {
    key: `${kind}-${reason}-key`,
    kind,
    reason,
    title: TITLE,
    text: TEXT,
    queuedAt: Date.UTC(2026, 10, 14),
    ...over,
  };
}

function mount(write: FailedWrite, locale: "sv" | "en" = "sv") {
  const native = fakeNative(() => ok({}));
  native.failedWrites.set(write.key, write);
  render(<QueueNotice native={native} locale={locale} refreshKey={0} />);
  return native;
}

/** A clipboard the page can write to; it is put in place after the user-event setup, which brings its own. */
function clipboard(writeText = vi.fn(() => Promise.resolve())) {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  return writeText;
}

afterEach(() => {
  cleanup();
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("a record write that could not be sent", () => {
  describe.each(LOCALES)("in $locale", ({ locale, labels }) => {
    it.each(KINDS)(
      "names a refused $kind by what it was and its title, and keeps the words",
      async ({ kind, label }) => {
        mount(failed(kind, "rejected"), locale);

        expect(
          await screen.findByText(
            `${labels[label] as string}: ${TITLE}. ${labels.rejected}`,
          ),
        ).toBeVisible();
        expect(screen.getByText(TEXT)).toBeVisible();
      },
    );

    it.each(KINDS)(
      "says an expired $kind waited too long and keeps the words",
      async ({ kind, label }) => {
        mount(failed(kind, "expired"), locale);

        expect(
          await screen.findByText(
            `${labels[label] as string}: ${TITLE}. ${labels.expired}`,
          ),
        ).toBeVisible();
        expect(screen.getByText(TEXT)).toBeVisible();
      },
    );
  });

  describe.each(KINDS)("$kind", ({ kind, label }) => {
    it("offers only the copy and the removal of a refused write, which would be refused again", async () => {
      mount(failed(kind, "rejected"));
      const what = `${queueNoticeLabelsSv[label] as string}: ${TITLE}`;

      expect(
        await screen.findByRole("button", { name: `Kopiera texten: ${what}` }),
      ).toBeVisible();
      expect(
        screen.getByRole("button", { name: `Ta bort: ${what}` }),
      ).toBeVisible();
      expect(screen.queryByRole("button", { name: /Försök igen/ })).toBeNull();
    });

    it("offers a retry of an expired write, besides the copy and the removal", async () => {
      mount(failed(kind, "expired"));
      const what = `${queueNoticeLabelsSv[label] as string}: ${TITLE}`;

      expect(
        await screen.findByRole("button", { name: `Försök igen: ${what}` }),
      ).toBeVisible();
      expect(
        screen.getByRole("button", { name: `Kopiera texten: ${what}` }),
      ).toBeVisible();
      expect(
        screen.getByRole("button", { name: `Ta bort: ${what}` }),
      ).toBeVisible();
    });
  });

  it("offers no retry of an expired write whose key the server has forgotten", async () => {
    mount(failed("create_task", "expired", { retryable: false }));

    expect(
      await screen.findByRole("button", { name: /Ta bort/ }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /Försök igen/ })).toBeNull();
  });

  it("puts the title and the words on the clipboard and says so", async () => {
    const user = userEvent.setup();
    const writeText = clipboard();
    mount(failed("write_journal_entry", "rejected"));

    await user.click(
      await screen.findByRole("button", { name: /Kopiera texten/ }),
    );

    expect(writeText).toHaveBeenCalledWith(`${TITLE}\n\n${TEXT}`);
    expect(await screen.findByText("Kopierad.")).toBeVisible();
  });

  it("says Copied in English", async () => {
    const user = userEvent.setup();
    clipboard();
    mount(failed("update_task", "rejected"), "en");

    await user.click(
      await screen.findByRole("button", { name: /Copy the text/ }),
    );

    expect(await screen.findByText("Copied.")).toBeVisible();
  });

  it("copies the words alone when the write has no title", async () => {
    const user = userEvent.setup();
    const writeText = clipboard();
    mount(failed("update_project", "rejected", { title: undefined }));

    await user.click(
      await screen.findByRole("button", { name: /Kopiera texten/ }),
    );

    expect(writeText).toHaveBeenCalledWith(TEXT);
  });

  it("does not say it copied when the clipboard refused", async () => {
    const user = userEvent.setup();
    const writeText = clipboard(
      vi.fn(() => Promise.reject(new Error("denied"))),
    );
    mount(failed("create_task", "rejected"));

    await user.click(
      await screen.findByRole("button", { name: /Kopiera texten/ }),
    );

    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(screen.queryByText("Kopierad.")).toBeNull();
    expect(screen.getByText(TEXT)).toBeVisible();
  });

  it("puts an expired write back in the outbox with its own key", async () => {
    const user = userEvent.setup();
    const native = mount(failed("update_task", "expired"));

    await user.click(
      await screen.findByRole("button", { name: /Försök igen/ }),
    );

    expect(native.retryQueuedWrite).toHaveBeenCalledWith({
      key: "update_task-expired-key",
    });
    await waitFor(() => expect(screen.queryByText(TEXT)).toBeNull());
  });

  it("removes a refused write, and its words go with the line", async () => {
    const user = userEvent.setup();
    const native = mount(failed("update_journal_entry", "rejected"));

    await user.click(await screen.findByRole("button", { name: /Ta bort/ }));

    expect(native.removeQueuedWrite).toHaveBeenCalledWith({
      key: "update_journal_entry-rejected-key",
    });
    await waitFor(() => expect(screen.queryByText(TEXT)).toBeNull());
  });

  it("draws a write with a title but no words, with a copy of the title and no empty line of words", async () => {
    mount(failed("update_task", "rejected", { text: undefined }));

    expect(
      await screen.findByRole("button", { name: /Kopiera texten/ }),
    ).toBeVisible();
    expect(document.querySelector(".mobile-queue-notice__written")).toBeNull();
  });

  it("draws a write with neither title nor words with its label alone and no copy", async () => {
    mount(
      failed("update_project", "rejected", {
        title: undefined,
        text: undefined,
      }),
    );

    expect(
      await screen.findByText(
        `${queueNoticeLabelsSv.updateProject}. ${queueNoticeLabelsSv.rejected}`,
      ),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /Kopiera texten/ })).toBeNull();
  });
});

describe("describeWrite for a record write", () => {
  describe.each(LOCALES)("in $locale", ({ labels }) => {
    it.each(KINDS)("reads $kind as its label and title", ({ kind, label }) => {
      expect(describeWrite(failed(kind, "rejected"), labels)).toBe(
        `${labels[label] as string}: ${TITLE}`,
      );
    });

    it.each(KINDS)(
      "reads $kind without a title as its label",
      ({ kind, label }) => {
        expect(
          describeWrite(failed(kind, "rejected", { title: undefined }), labels),
        ).toBe(labels[label]);
        expect(
          describeWrite(failed(kind, "rejected", { title: "" }), labels),
        ).toBe(labels[label]);
      },
    );
  });
});
