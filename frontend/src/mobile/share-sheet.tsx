/**
 * The share sheet: what the phone shows when another app shares text or a link to Sidekick (ADR-005, "Amendment
 * 2026-11-15"). It is a small full-frame form, not a room: the shared text, a title the owner may edit, a choice between a
 * Task and a new entry in today's journal, and Save or Cancel. Nothing is written before Save.
 *
 * It writes through the rooms' own tools over the transport (`create_task`, `write_journal_entry`), so the companion
 * routes, their scopes and their idempotency are the ones the Work and Journal forms already use: a second Save of the
 * same text sends the same key, so a lost answer never writes twice. When no answer comes the sheet says so and keeps
 * everything that was typed; nothing is queued, and the journal text is never stored on the phone. A phone that is not
 * paired never reaches this sheet: the pairing screen says the text waits (pairing-gate.tsx).
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import { ownerToday } from "@/features/mcp-apps/app-timezone";
import { roomEnabled } from "@/features/mcp-apps/enabled-rooms";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { toolOffered } from "@/features/mcp-apps/tool-support";
import { Button } from "@/features/mcp-apps/ui/button";
import { KeyScope } from "@/features/mcp-apps/ui/key-scope";
import { AppFrame } from "@/features/mcp-apps/ui/layout";
import { Segmented } from "@/features/mcp-apps/ui/segmented";
import { ErrorNotice } from "@/features/mcp-apps/ui/states";
import { useMounted } from "@/features/mcp-apps/ui/use-mounted";
import { shareLabelsFor } from "./share-labels";
import type { SharedText } from "./sidekick-native";
import "./share-sheet.css";

type Kind = "task" | "journal";

/** A title takes 200 characters, for a task and for a journal entry alike. */
const TITLE_MAX = 200;

export type ShareSheetProps = {
  transport: RoomTransport;
  share: SharedText;
  locale: AppLocale;
  /** Cancel, Done after a save, and system Back. */
  onClose: () => void;
};

export function ShareSheet({
  transport,
  share,
  locale,
  onClose,
}: ShareSheetProps) {
  const labels = shareLabelsFor(locale);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const mounted = useMounted();
  const journalOffered =
    roomEnabled("journal") && toolOffered(transport, "write_journal_entry");
  const [kind, setKind] = useState<Kind>("task");
  const [title, setTitle] = useState(share.title);
  const [phase, setPhase] = useState<"editing" | "saving" | "saved">("editing");
  const [failure, setFailure] = useState<{ cause: unknown } | undefined>();
  const [missingTitle, setMissingTitle] = useState(false);

  // The sheet replaces the room on screen: the focus moves to it, as it does for the settings.
  useEffect(() => {
    root.current?.focus();
  }, []);

  async function save() {
    const trimmed = title.trim();
    if (!trimmed) {
      setMissingTitle(true);
      return;
    }
    setMissingTitle(false);
    setFailure(undefined);
    setPhase("saving");
    try {
      if (kind === "journal") {
        await transport.call("write_journal_entry", {
          journal_date: ownerToday(),
          title: trimmed,
          source_text: share.text || trimmed,
        });
      } else {
        await transport.call("create_task", {
          title: trimmed,
          // The shared text carries its own link; a text that only repeats the title adds nothing.
          ...(share.text && share.text !== trimmed
            ? { description: share.text }
            : {}),
        });
      }
      if (mounted.current) setPhase("saved");
    } catch (cause) {
      if (!mounted.current) return;
      setFailure({ cause });
      setPhase("editing");
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (phase === "editing") void save();
  }

  if (phase === "saved")
    return (
      <AppFrame mode="full">
        <KeyScope
          ref={root}
          role="region"
          className="mobile-share"
          aria-label={labels.title}
          tabIndex={-1}
          lang={locale}
          onEscape={onClose}
        >
          <h1 className="mobile-share__title">{labels.title}</h1>
          <p role="status" className="mobile-share__saved">
            {kind === "journal" ? labels.savedJournal : labels.savedTask}
          </p>
          <div className="mobile-share__actions">
            <Button variant="primary" onClick={onClose}>
              {labels.done}
            </Button>
          </div>
        </KeyScope>
      </AppFrame>
    );

  const saving = phase === "saving";
  return (
    <AppFrame mode="full">
      <KeyScope
        ref={root}
        role="region"
        className="mobile-share"
        aria-label={labels.title}
        tabIndex={-1}
        lang={locale}
        onEscape={saving ? undefined : onClose}
      >
        <h1 className="mobile-share__title">{labels.title}</h1>
        <form className="mobile-share__form" onSubmit={submit} noValidate>
          {journalOffered ? (
            <Segmented
              label={labels.kindLabel}
              options={[
                { value: "task", label: labels.kindTask },
                { value: "journal", label: labels.kindJournal },
              ]}
              value={kind}
              onChange={setKind}
              disabled={saving}
            />
          ) : null}
          <div className="mobile-share__field">
            <label className="mobile-share__label" htmlFor={`${id}-title`}>
              {labels.titleLabel}
            </label>
            <input
              id={`${id}-title`}
              className="mobile-share__input"
              type="text"
              maxLength={TITLE_MAX}
              enterKeyHint="done"
              autoComplete="off"
              aria-invalid={missingTitle || undefined}
              aria-describedby={missingTitle ? `${id}-title-error` : undefined}
              value={title}
              disabled={saving}
              onChange={(event) => {
                setTitle(event.target.value);
                setMissingTitle(false);
              }}
            />
            {missingTitle ? (
              <p
                id={`${id}-title-error`}
                role="alert"
                className="mobile-share__error"
              >
                {labels.titleRequired}
              </p>
            ) : null}
          </div>
          {share.text ? (
            <div
              className="mobile-share__field"
              role="group"
              aria-labelledby={`${id}-text-label`}
            >
              <span className="mobile-share__label" id={`${id}-text-label`}>
                {labels.sharedLabel}
              </span>
              <p className="mobile-share__text">{share.text}</p>
            </div>
          ) : null}
          {failure ? (
            <ErrorNotice
              locale={locale}
              message={labels.failed}
              cause={failure.cause}
              placement="row"
            />
          ) : null}
          <div className="mobile-share__actions">
            <Button
              type="submit"
              variant="primary"
              aria-disabled={saving || undefined}
            >
              {saving ? labels.saving : labels.save}
            </Button>
            <Button variant="quiet" disabled={saving} onClick={onClose}>
              {labels.cancel}
            </Button>
          </div>
        </form>
      </KeyScope>
    </AppFrame>
  );
}
