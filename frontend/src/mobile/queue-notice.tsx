/**
 * What the phone could not send of what the user did without a network: a shopping write that waited longer than
 * seven days, or that the server refused. They stand in a card headed "Inköp som inte skickades", each as a short
 * line, "Mjölk, Ost. Den låg i kön i över 7 dagar.", with the way out: "Försök igen" puts it back in the outbox, "Ta bort" removes it. Nothing the user queued disappears
 * unseen. Drawn over the rooms (it is the phone's own, like the push note), only while something failed. A refused read
 * draws nothing; a refused retry or remove says so on its line and leaves it where it is.
 */
import { useCallback, useEffect, useState } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import { Button } from "@/features/mcp-apps/ui/button";
import type { FailedWrite, SidekickNativePlugin } from "./sidekick-native";
import "./queue-notice.css";

export type QueueNoticeLabels = {
  /** The heading of the card: what kind of writes these are. */
  failed: string;
  /** What an add of items without a name reads as. */
  items: string;
  /** "Mjölk, Ost och 2 till". */
  more: (names: string, count: number) => string;
  /** A purchase, by the state it asked for. */
  bought: string;
  putBack: string;
  /** Why, in a sentence of its own. Ends with a full stop (designsystem §1.6). */
  expired: string;
  rejected: string;
  retry: string;
  remove: string;
  /** The retry or remove was refused. */
  actionFailed: string;
  /** The phone answered, but the write was not put back in the queue (it was gone, or too old to send safely). */
  notRetried: string;
  /** The phone answered, but the write was not removed (it was already gone, or the queue could not be saved). */
  notRemoved: string;
};

export const queueNoticeLabelsSv: QueueNoticeLabels = {
  failed: "Inköp som inte skickades",
  items: "varor",
  more: (names, count) => `${names} och ${count} till`,
  bought: "Köp av en vara",
  putBack: "En vara som lades tillbaka på listan",
  expired: "Den låg i kön i över 7 dagar.",
  rejected: "Servern tog inte emot den.",
  retry: "Försök igen",
  remove: "Ta bort",
  actionFailed: "Det gick inte. Försök igen om en stund.",
  notRetried:
    "Den kunde inte läggas i kön igen. Ta bort den och lägg till på nytt.",
  notRemoved: "Den kunde inte tas bort. Försök igen om en stund.",
};

export const queueNoticeLabelsEn: QueueNoticeLabels = {
  failed: "Shopping items that weren’t sent",
  items: "items",
  more: (names, count) => `${names} and ${count} more`,
  bought: "Marking an item as bought",
  putBack: "Putting an item back on the list",
  expired: "It waited in the queue for over 7 days.",
  rejected: "The server didn’t accept it.",
  retry: "Try again",
  remove: "Remove",
  actionFailed: "That didn’t work. Try again in a moment.",
  notRetried:
    "It couldn’t be put back in the queue. Remove it and add it again.",
  notRemoved: "It couldn’t be removed. Try again in a moment.",
};

export function queueNoticeLabelsFor(locale: AppLocale): QueueNoticeLabels {
  return locale === "en" ? queueNoticeLabelsEn : queueNoticeLabelsSv;
}

const HEADING_ID = "mobile-queue-notice-heading";

/** At most this many names are listed; the rest are counted. */
const NAMES_SHOWN = 3;

function nameOf(item: Record<string, unknown>): string | undefined {
  return typeof item.name === "string" && item.name.trim() !== ""
    ? item.name.trim()
    : undefined;
}

/** What the write was, in the user's words: the names of the added items, or the purchase. */
export function describeWrite(
  write: FailedWrite,
  labels: QueueNoticeLabels,
): string {
  if (write.kind === "purchase")
    return write.purchased ? labels.bought : labels.putBack;
  const names = (write.items ?? []).flatMap((item) => nameOf(item) ?? []);
  if (names.length === 0) return labels.items;
  if (names.length <= NAMES_SHOWN) return names.join(", ");
  return labels.more(
    names.slice(0, NAMES_SHOWN).join(", "),
    names.length - NAMES_SHOWN,
  );
}

/**
 * A refused purchase was written against a version that has since changed, so sending it again would be refused
 * again: it can only be removed. So can a write whose key is older than the server's idempotency window: sent again
 * it would be a new write (a second add). Everything else can be tried again.
 */
function canRetry(write: FailedWrite): boolean {
  if (write.retryable === false) return false;
  return !(write.kind === "purchase" && write.reason === "rejected");
}

export type QueueNoticeProps = {
  native: Pick<
    SidekickNativePlugin,
    "queuedWrites" | "retryQueuedWrite" | "removeQueuedWrite" | "addListener"
  >;
  locale: AppLocale;
  /** Changes when the app comes back to the foreground: a run of the outbox may have ended meanwhile. */
  refreshKey: number;
};

export function QueueNotice({ native, locale, refreshKey }: QueueNoticeProps) {
  const [failed, setFailed] = useState<FailedWrite[]>([]);
  const [busy, setBusy] = useState<string | undefined>();
  const [refused, setRefused] = useState<
    { key: string; message: keyof QueueNoticeLabels } | undefined
  >();
  const [tick, setTick] = useState(0);

  // A run of the outbox ending (it may have refused something) reads again.
  useEffect(() => {
    const handle = native.addListener("queueChanged", () =>
      setTick((n) => n + 1),
    );
    return () => {
      void handle.then((h) => h.remove()).catch(() => undefined);
    };
  }, [native]);

  useEffect(() => {
    let live = true;
    native.queuedWrites().then(
      (writes) => {
        if (live) setFailed(writes.failed ?? []);
      },
      () => {
        if (live) setFailed([]);
      },
    );
    return () => {
      live = false;
    };
  }, [native, refreshKey, tick]);

  /**
   * Runs a retry or a remove. The plugin answers `done: false` when it did not do it (the write was gone, too old to
   * send safely, or the queue could not be saved): that is said on the line too, then the list is read again.
   */
  const perform = useCallback(
    (
      key: string,
      run: () => Promise<boolean>,
      notDone: "notRetried" | "notRemoved",
    ) => {
      setBusy(key);
      setRefused(undefined);
      run().then(
        (done) => {
          setBusy(undefined);
          if (!done) setRefused({ key, message: notDone });
          setTick((n) => n + 1);
        },
        () => {
          setBusy(undefined);
          setRefused({ key, message: "actionFailed" });
        },
      );
    },
    [],
  );

  if (failed.length === 0) return null;
  const labels = queueNoticeLabelsFor(locale);
  return (
    <div className="mobile-queue-notice" lang={locale} role="status">
      <p id={HEADING_ID} className="mobile-queue-notice__heading">
        {labels.failed}
      </p>
      <ul className="mobile-queue-notice__list" aria-labelledby={HEADING_ID}>
        {failed.map((write) => {
          const what = describeWrite(write, labels);
          return (
            <li key={write.key} className="mobile-queue-notice__row">
              <p className="mobile-queue-notice__text">
                {what}.{" "}
                {write.reason === "expired" ? labels.expired : labels.rejected}
              </p>
              {refused?.key === write.key ? (
                <p role="alert" className="mobile-queue-notice__text">
                  {labels[refused.message] as string}
                </p>
              ) : null}
              <div className="mobile-queue-notice__actions">
                {canRetry(write) ? (
                  <Button
                    variant="quiet"
                    disabled={busy === write.key}
                    aria-label={`${labels.retry}: ${what}`}
                    onClick={() =>
                      perform(
                        write.key,
                        () =>
                          native
                            .retryQueuedWrite({ key: write.key })
                            .then((result) => result.retried === true),
                        "notRetried",
                      )
                    }
                  >
                    {labels.retry}
                  </Button>
                ) : null}
                <Button
                  variant="quiet"
                  disabled={busy === write.key}
                  aria-label={`${labels.remove}: ${what}`}
                  onClick={() =>
                    perform(
                      write.key,
                      () =>
                        native
                          .removeQueuedWrite({ key: write.key })
                          .then((result) => result.removed === true),
                      "notRemoved",
                    )
                  }
                >
                  {labels.remove}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
