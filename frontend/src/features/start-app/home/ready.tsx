import { useRef, useState, type RefObject } from "react";

import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { DecisionCard } from "../../mcp-apps/ui/decision-card";
import type { useReceipt } from "../../mcp-apps/ui/receipt";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import type { HomeLabels } from "./labels";
import { phraseTitle, readyTime, type StartReadyRow } from "./model";
import type { HomeTransport } from "./transport";

export type ReadyState = ReturnType<typeof useReady>;

/**
 * The ready conversations' answers. Skipping is the one write: it is sent once per press (a retry of the same press
 * reuses its idempotency key), the card leaves at once, and the receipt offers Ångra. Starting sends the phrase; where
 * the host could not send it the card shows the phrase as text instead.
 */
export function useReady({
  api,
  t,
  receipt,
  reload,
  titleRef,
}: {
  api: HomeTransport;
  t: HomeLabels;
  receipt: ReturnType<typeof useReceipt>;
  reload: () => void;
  titleRef: RefObject<HTMLHeadingElement | null>;
}) {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [failed, setFailed] = useState<ReadonlySet<string>>(new Set());
  const [unsent, setUnsent] = useState<ReadonlySet<string>>(new Set());
  const keys = useRef(new Map<string, PendingKey>());
  const running = useRef(new Set<string>());

  const write = (
    row: StartReadyRow,
    undo: boolean,
    done: () => void,
    fail: () => void,
  ) => {
    const skip = api.skip;
    if (!skip || running.current.has(row.id)) return;
    const signature = `${row.id}:${undo ? "undo" : "skip"}:${row.version}`;
    const pending = keyFor(keys.current.get(signature), signature);
    keys.current.set(signature, pending);
    running.current.add(row.id);
    setBusy((now) => with_(now, row.id));
    skip(row.id, undo, pending.key).then(
      () => {
        running.current.delete(row.id);
        keys.current.delete(signature);
        setBusy((now) => without(now, row.id));
        done();
      },
      () => {
        running.current.delete(row.id);
        setBusy((now) => without(now, row.id));
        fail();
      },
    );
  };

  const unskip = (row: StartReadyRow) =>
    write(
      row,
      true,
      () => {
        setHidden((now) => without(now, row.id));
        receipt.show({ message: t.unskipped(row.title) });
        reload();
      },
      () => receipt.show({ message: t.skipFailed }),
    );

  const skip = (row: StartReadyRow) => {
    setFailed((now) => without(now, row.id));
    write(
      row,
      false,
      () => {
        setHidden((now) => with_(now, row.id));
        // The card leaves: the focus goes to the page's title rather than to nothing.
        titleRef.current?.focus();
        receipt.show({
          message: t.skipped(row.title),
          undo: { label: t.undo, onUndo: () => unskip(row) },
        });
        reload();
      },
      () => setFailed((now) => with_(now, row.id)),
    );
  };

  const start = (
    row: StartReadyRow,
    sendMessage: (text: string) => Promise<boolean>,
  ) => {
    sendMessage(t.startMessage(phraseTitle(row.title), row.id)).then(
      (sent) => {
        if (sent) receipt.show({ message: t.sent });
        else setUnsent((now) => with_(now, row.id));
      },
      () => setUnsent((now) => with_(now, row.id)),
    );
  };

  return {
    hidden,
    busy,
    failed,
    unsent,
    skip: api.skip ? skip : undefined,
    start,
  };
}

function with_(set: ReadonlySet<string>, id: string): ReadonlySet<string> {
  return new Set([...set, id]);
}
function without(set: ReadonlySet<string>, id: string): ReadonlySet<string> {
  if (!set.has(id)) return set;
  const next = new Set(set);
  next.delete(id);
  return next;
}

/**
 * One conversation that is ready now, as a decision card: when it became ready, its title, and "Hoppa över idag" and
 * "Starta". Without the host's messages (or after a send that failed) the phrase to say stands as text under it.
 */
export function ReadyCard({
  row,
  t,
  ready,
  sendMessage,
}: {
  row: StartReadyRow;
  t: HomeLabels;
  ready: ReadyState;
  sendMessage?: (text: string) => Promise<boolean>;
}) {
  const send =
    sendMessage && !ready.unsent.has(row.id) ? sendMessage : undefined;
  const phrase = t.startPhrase(phraseTitle(row.title));
  return (
    <div aria-busy={ready.busy.has(row.id) || undefined}>
      <DecisionCard
        locale={t.dateLocale}
        density="full"
        kicker={t.readySince(readyTime(row.local_time))}
        title={row.title}
        actions={{
          approve: send ? () => ready.start(row, send) : undefined,
          dismiss: ready.skip ? () => ready.skip?.(row) : undefined,
        }}
        answerLabels={{ approve: t.start, dismiss: t.skip }}
      >
        {send ? null : (
          <p className="start-home-say">
            <span className="start-home-say-lead">{t.sayInClaude}</span>{" "}
            <span className="start-home-say-phrase">{phrase}</span>
          </p>
        )}
      </DecisionCard>
      {ready.failed.has(row.id) ? (
        <ErrorNotice
          locale={t.dateLocale}
          placement="row"
          message={t.skipFailed}
          onRetry={() => ready.skip?.(row)}
        />
      ) : null}
    </div>
  );
}
