/**
 * The phone's trash (ADR-005): one screen over the settings, opened from their "Papperskorgen" row. It reads the first
 * page of `list_trash` and then shows Control's own trash view in full, over the phone's transport: the rows and their
 * Restore, and, when the device holds `companion:work:erase` (the first page says so with `can_erase`) and the phone
 * answers `erase_trashed_task` and `empty_trash`, the permanent removal of a Task with its question first. Without that
 * right the view has no "delete for good" and no "empty". The view and its texts are Control's; this file only reads, mounts it and tells the shell when a
 * write changed what the rooms show. Nothing here reaches the network but through the transport.
 */
import { useCallback, useEffect, useMemo, useRef } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import { dirtyDomains } from "@/features/mcp-apps/dirty-domains";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { BackHeader } from "@/features/mcp-apps/ui/back-header";
import { AppFrame } from "@/features/mcp-apps/ui/layout";
import { ErrorNotice } from "@/features/mcp-apps/ui/states";
import { useRead } from "@/features/mcp-apps/ui/use-read";
import { controlLabels } from "@/features/control-app/labels";
import { createTrashTransport } from "@/features/control-app/trash-transport";
import { TrashView } from "@/features/control-app/trash-view";
import "@/features/mcp-apps/ui/tokens.css";
import "@/features/control-app/control.css";
import { settingsLabelsFor } from "./settings-labels";
import "./settings-panel.css";

export type PhoneTrashProps = {
  transport: RoomTransport;
  locale: AppLocale;
  /** "‹ Inställningar" and system Back. */
  onBack: () => void;
  /** A write changed what the rooms show (a record came back): the rooms read again. Must be stable across renders. */
  onChanged: () => void;
};

export function PhoneTrash({
  transport,
  locale,
  onBack,
  onChanged,
}: PhoneTrashProps) {
  const labels = settingsLabelsFor(locale);
  const control = controlLabels[locale];
  const root = useRef<HTMLElement>(null);
  const { call, supportsTool } = transport;
  // `onChanged` is the caller's stable callback, so the transport stays the same object across renders.
  /** The transport's call, telling the shell after every write that the rooms may show something else now. */
  const noting = useCallback(
    async <T,>(name: string, args: object): Promise<T> => {
      const answer = await call<T>(name, args);
      if (dirtyDomains(name).length > 0) onChanged();
      return answer;
    },
    [call, onChanged],
  );
  // Reading and restoring need no more than the rights the rooms have; removing for good is added below.
  const reading = useMemo(() => createTrashTransport(noting), [noting]);
  const readFirstPage = useCallback(() => reading.trash(), [reading]);
  const [first, retry] = useRead(readFirstPage);
  const mayErase = first.phase === "ready" && first.value.can_erase === true;
  const trash = useMemo(
    () => (mayErase ? createTrashTransport(noting, supportsTool) : reading),
    [mayErase, noting, supportsTool, reading],
  );

  // The screen covers the settings: the focus moves to it, as it does to the settings over the rooms.
  useEffect(() => {
    root.current?.focus();
  }, []);

  return (
    <AppFrame mode="full">
      <section
        ref={root}
        className="mobile-settings"
        aria-label={labels.trash}
        tabIndex={-1}
        lang={locale}
      >
        <BackHeader label={labels.title} onBack={onBack} title={labels.trash} />
        {first.phase === "reading" ? (
          <p role="status" className="mobile-settings__meta">
            {labels.loading}
          </p>
        ) : first.phase === "failed" ? (
          <ErrorNotice
            locale={locale}
            message={labels.trashFailed}
            cause={first.cause}
            placement="row"
            onRetry={retry}
          />
        ) : (
          <section className="sidekick-control" aria-label={control.title}>
            <div className="control-card sk-card">
              <TrashView
                initial={first.value}
                transport={trash}
                labels={control}
                full
              />
            </div>
          </section>
        )}
      </section>
    </AppFrame>
  );
}
