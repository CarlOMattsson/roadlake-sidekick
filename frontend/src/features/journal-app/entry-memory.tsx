import { useState } from "react";
import { ErrorNotice } from "../mcp-apps/ui/states";
import type { JournalLabels } from "./labels";
import {
  writeFailure,
  type JournalEntry,
  type JournalTransport,
  type WriteFailure,
} from "./transport";
import "./journal.css";
import "./entry.css";

/** What the entry view knows about keeping the entry out of Claude's memory. */
export type EntryMemory = {
  busy: boolean;
  /** How the last try failed, with the choice it was making; cleared by the next try. */
  failure?: { excluded: boolean; how: WriteFailure };
  /** Flips the entry's state: out of memory when it is in, back in when it is out. */
  toggle: () => void;
  /** Tries the choice that failed once more. */
  retry: () => void;
};

/**
 * Keeping one entry out of Claude's memory (exclude_from_memory), or bringing it back. The entry's version does
 * not change, so `onDone` only receives the new state; the parent shows it in the entry it holds. Undefined when
 * the transport lacks the capability, so the menu offers no item.
 */
export function useEntryMemory(
  transport: JournalTransport,
  entry: JournalEntry | undefined,
  onDone: (excluded: boolean) => void,
): EntryMemory | undefined {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<EntryMemory["failure"]>();
  const write = transport.excludeEntryFromMemory;
  if (!write || !entry) return undefined;

  function apply(excluded: boolean) {
    if (!write || !entry || busy) return;
    setBusy(true);
    setFailure(undefined);
    write(entry.id, excluded)
      .then(() => onDone(excluded))
      .catch((error: unknown) =>
        setFailure({ excluded, how: writeFailure(error) }),
      )
      .finally(() => setBusy(false));
  }

  return {
    busy,
    failure,
    toggle: () => apply(!entry.memory_excluded),
    retry: () => {
      if (failure) apply(failure.excluded);
    },
  };
}

/**
 * "Utanför minnet" as a small chip in the tag chip's shape (28 px high, the same pill), with a crossed-out eye. It is a
 * marker, not a control: nothing happens when it is pressed, the choice is made in the entry's ⋯. In a list row it is
 * drawn in the row's tag size (entry.css).
 */
export function MemoryChip({ labels: t }: { labels: JournalLabels }) {
  return (
    <span className="journal-memory-chip">
      <svg
        viewBox="0 0 24 24"
        width="14"
        height="14"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
        <circle cx="12" cy="12" r="3" />
        <path d="M4 4l16 16" />
      </svg>
      {t.entryOutOfMemory}
    </span>
  );
}

/** The line under a failed memory choice, with a retry. */
export function EntryMemoryFailure({
  labels: t,
  state,
}: {
  labels: JournalLabels;
  state: EntryMemory;
}) {
  const { failure } = state;
  if (!failure) return null;
  return (
    <ErrorNotice
      placement="row"
      locale={t.dateLocale}
      message={
        failure.how === "forbidden" ? t.forbiddenWrite : t.entryMemoryFailed
      }
      retrying={state.busy}
      onRetry={failure.how === "forbidden" ? undefined : state.retry}
    />
  );
}
