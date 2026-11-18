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
