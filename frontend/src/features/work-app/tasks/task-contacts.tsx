import { useEffect, useId, useRef, useState } from "react";
import type { WorkLabels } from "../shared/labels";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { useSingleFlight } from "../shared/use-single-flight";
import { useWorkWrite } from "../shared/use-work-write";
import { CloseIcon, PlusIcon } from "../../mcp-apps/ui/icons";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { WriteFailureRow } from "../shared/write-failure-row";
import { initialsOf } from "../../mcp-apps/ui/initials";
import {
  isForbidden,
  writeFailure,
  type WorkContact,
  type WorkTransport,
  type WriteFailure,
} from "../transport/transport";
import "./task-contacts.css";

/** list_contacts takes q of 1 to 200 characters; the view searches from two letters on. */
const SEARCH_MIN_LENGTH = 2;
const SEARCH_MAX_LENGTH = 200;
const SEARCH_DEBOUNCE_MS = 300;
/** The busy marker of the `createContact` row; a Contact id is never this. */
const CREATE_ROW = "create";

type SearchPhase = "idle" | "loading" | "ready" | "forbidden" | "error";
type MorePhase = "idle" | "busy" | "failed";
/** A refused write and what it was, so the calm line names it. */
type Failed = { failure: WriteFailure; action: "link" | "create" };

/** A write refused with a notice; retry runs the same action again with the same key. */
function ContactFailure({
  failure,
  message,
  labels: t,
  onReload,
  onRetry,
}: {
  failure: WriteFailure;
  /** The line for a failed write; `retry` is the notice's own button. */
  message: string;
  labels: WorkLabels;
  onReload: () => void;
  onRetry: () => void;
}) {
  const banner = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (failure === "conflict") banner.current?.focus();
  }, [failure]);
  if (failure === "conflict")
    return (
      <div role="alert" tabIndex={-1} ref={banner} className="work-banner">
        <p>{t.contactConflict}</p>
        <button type="button" onClick={onReload}>
          {t.reload}
        </button>
      </div>
    );
  return (
    <WriteFailureRow
      failure={failure}
      failedMessage={message}
      labels={t}
      onRetry={onRetry}
    />
  );
}

/**
 * `linkContact` opens a search sheet over the owner's Contacts for the Task. The sheet sticks to the foot of the
 * visible window above the host's reply field (and the on-screen keyboard, which shrinks that window), with the field
 * at its foot and the hits growing upwards over it, so what is typed and what it finds are always in view. Each
 * change of the query starts a debounced search, and an answer to an older query is ignored. A hit that is not linked
 * yet links on a tap; a linked hit is shown, not offered. When nothing matches, `createContact` with the typed name creates the
 * Contact with that name and links it. After a link the parent reads the contact list again. Esc and × close the
 * sheet and return the focus to `linkContact`.
 */
export function LinkContact({
  taskId,
  transport,
  labels: t,
  linkedIds,
  createOffered,
  onChanged,
}: {
  taskId: string;
  transport: WorkTransport;
  labels: WorkLabels;
  linkedIds: readonly string[];
  /** Whether the host answers create_contact; without it a search with no hit offers no create row. */
  createOffered: boolean;
  onChanged: () => void;
}) {
  const [query, setQuery] = useState("");
  const [phase, setPhase] = useState<SearchPhase>("idle");
  const [results, setResults] = useState<WorkContact[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [more, setMore] = useState<MorePhase>("idle");
  const [busyId, setBusyId] = useState<string>();
  const [failed, setFailed] = useState<Failed>();
  // Closed, the section shows one quiet `linkContact` line; opening it puts the focus in the search.
  const [open, setOpen] = useState(false);
  const inputElement = useRef<HTMLInputElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  // Set by a close, so the focus goes back to `linkContact` and not on the first render.
  const returnFocus = useRef(false);
  const inputId = useId();
  const hintId = useId();
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // Bumped by every query change and every search request; only the newest answer is applied.
  const ticket = useRef(0);
  // One "Show more" page per query, claimed before React re-renders the button.
  const pages = useSingleFlight();
  // The trimmed query the shown results belong to, so Show more pages the same search.
  const searched = useRef("");
  // The last write, run again by Försök igen with the same key.
  const again = useRef<() => void>(undefined);
  // A Contact created here whose link has not gone through yet: a retry links it instead of creating a second one.
  const created = useRef<{ name: string; contact: WorkContact }>(undefined);
  // One link or create at a time, claimed before React re-renders.
  const writes = useSingleFlight();
  const pending = useRef(new Map<string, PendingKey>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const marker = ticket;
    const pendingSearch = timer;
    return () => {
      mounted.current = false;
      clearTimeout(pendingSearch.current);
      marker.current++;
    };
  }, []);
  useEffect(() => {
    if (open) inputElement.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      addButton.current?.focus();
    }
  }, [open]);

  function runSearch(q: string) {
    const current = ++ticket.current;
    searched.current = q;
    transport
      .searchContacts(q)
      .then((page) => {
        if (current !== ticket.current) return;
        setResults(page.items);
        setNextCursor(page.next_cursor);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (current !== ticket.current) return;
        setPhase(isForbidden(error) ? "forbidden" : "error");
      });
  }

  function changeQuery(value: string) {
    setQuery(value);
    setFailed(undefined);
    setMore("idle");
    setResults([]);
    setNextCursor(null);
    // An answer to the previous query, or a Show more of it, is now old.
    ticket.current++;
    clearTimeout(timer.current);
    const q = value.trim();
    if (Array.from(q).length < SEARCH_MIN_LENGTH) {
      setPhase("idle");
      return;
    }
    setPhase("loading");
    timer.current = setTimeout(() => runSearch(q), SEARCH_DEBOUNCE_MS);
  }

  function loadMore() {
    const current = ticket.current;
    if (!nextCursor || !pages.enter(current)) return;
    setMore("busy");
    transport
      .searchContacts(searched.current, nextCursor)
      .then((page) => {
        if (current !== ticket.current) return;
        setResults((known) => {
          const seen = new Set(known.map((contact) => contact.id));
          return [
            ...known,
            ...page.items.filter((contact) => !seen.has(contact.id)),
          ];
        });
        setNextCursor(page.next_cursor);
        setMore("idle");
      })
      .catch(() => {
        if (current === ticket.current) setMore("failed");
      })
      .finally(() => pages.leave(current));
  }

  function link(contact: WorkContact) {
    if (!writes.enter()) return;
    again.current = () => link(contact);
    const signature = JSON.stringify(["link", taskId, contact.id]);
    const pendingKey = keyFor(pending.current.get(contact.id), signature);
    pending.current.set(contact.id, pendingKey);
    setBusyId(contact.id);
    setFailed(undefined);
    transport
      .linkContactToTask(taskId, contact.id, pendingKey.key)
      .then(() => {
        pending.current.delete(contact.id);
        created.current = undefined;
        if (mounted.current) onChanged();
      })
      .catch((error: unknown) => {
        if (mounted.current)
          setFailed({ failure: writeFailure(error), action: "link" });
      })
      .finally(() => {
        writes.leave();
        if (mounted.current) setBusyId(undefined);
      });
  }

  function createAndLink(name: string) {
    if (writes.isRunning()) return;
    if (created.current?.name === name) {
      link(created.current.contact);
      return;
    }
    again.current = () => createAndLink(name);
    const signature = JSON.stringify(["create", name]);
    const pendingKey = keyFor(pending.current.get(signature), signature);
    pending.current.set(signature, pendingKey);
    writes.enter();
    setBusyId(CREATE_ROW);
    setFailed(undefined);
    transport.createContact({ display_name: name }, pendingKey.key).then(
      ({ contact }) => {
        pending.current.delete(signature);
        created.current = { name, contact };
        writes.leave();
        // Linked even when the view has gone meanwhile, so the new Contact does not end up unlinked.
        link(contact);
      },
      (error: unknown) => {
        writes.leave();
        if (!mounted.current) return;
        setBusyId(undefined);
        setFailed({ failure: writeFailure(error), action: "create" });
      },
    );
  }

  function close() {
    if (writes.isRunning()) return;
    // Closing drops the search, so the next opening starts clean.
    changeQuery("");
    returnFocus.current = true;
    setOpen(false);
  }

  if (!open)
    return (
      <div>
        <button
          ref={addButton}
          type="button"
          className="work-add-row sk-action-row"
          onClick={() => setOpen(true)}
        >
          <PlusIcon />
          {t.linkContact}
        </button>
      </div>
    );
  const linked = new Set(linkedIds);
  const busy = busyId !== undefined;
  const q = query.trim();
  return (
    <KeyScope
      className="work-contact-sheet"
      aria-busy={busy || undefined}
      onEscape={close}
    >
      <label htmlFor={inputId} className="work-contact-sheet-title">
        {t.linkContact}
      </label>
      {/* The field comes before the hits for the keyboard and screen readers; the sheet draws it at its foot. */}
      <div className="sk-createfield work-contact-sheet-field">
        <input
          id={inputId}
          ref={inputElement}
          className="sk-createfield__input"
          type="search"
          enterKeyHint="search"
          autoComplete="off"
          placeholder={t.contactSearchPlaceholder}
          value={query}
          maxLength={SEARCH_MAX_LENGTH}
          aria-describedby={phase === "idle" ? hintId : undefined}
          onChange={(event) => changeQuery(event.target.value)}
        />
        <button
          type="button"
          className="sk-createfield__btn"
          aria-label={t.closeContactSearch}
          disabled={busy}
          onClick={close}
        >
          <CloseIcon />
        </button>
      </div>
      <div className="work-contact-sheet-results">
        {phase === "idle" && (
          <p id={hintId} className="work-contact-sheet-note">
            {t.contactSearchHint}
          </p>
        )}
        {phase === "loading" && (
          <p role="status" className="work-contact-sheet-note">
            {t.loading}
          </p>
        )}
        {phase === "forbidden" && (
          <p className="work-contact-sheet-note">{t.contactsForbidden}</p>
        )}
        {phase === "error" && (
          <ErrorNotice
            placement="row"
            locale={t.dateLocale}
            onRetry={() => {
              setPhase("loading");
              runSearch(searched.current);
            }}
          />
        )}
        {phase === "ready" && results.length > 0 && (
          <ul className="work-contact-sheet-list">
            {results.map((contact) => (
              <li key={contact.id}>
                {linked.has(contact.id) ? (
                  <div className="work-contact-sheet-row">
                    <span className="work-link-avatar" aria-hidden="true">
                      {initialsOf(contact.display_name)}
                    </span>
                    <span className="work-contact-sheet-name">
                      {contact.display_name}
                      <span className="work-contact-sheet-meta">
                        {t.contactAlreadyLinked}
                      </span>
                    </span>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="work-contact-sheet-row"
                    disabled={busy}
                    aria-busy={busyId === contact.id || undefined}
                    onClick={() => link(contact)}
                  >
                    <span className="work-link-avatar" aria-hidden="true">
                      {initialsOf(contact.display_name)}
                    </span>
                    <span className="work-contact-sheet-name">
                      {contact.display_name}
                    </span>
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {phase === "ready" && results.length === 0 && (
          <>
            <p className="work-contact-sheet-note">{t.noContactMatches(q)}</p>
            {createOffered && (
              <button
                type="button"
                className="sk-action-row work-contact-sheet-create"
                disabled={busy}
                aria-busy={busyId === CREATE_ROW || undefined}
                onClick={() => createAndLink(q)}
              >
                <PlusIcon />
                {t.createAndLinkContact(q)}
              </button>
            )}
          </>
        )}
        {phase === "ready" && more === "busy" && (
          <p role="status" className="work-contact-sheet-note">
            {t.loading}
          </p>
        )}
        {phase === "ready" && more === "failed" && (
          <ErrorNotice
            placement="row"
            locale={t.dateLocale}
            onRetry={loadMore}
          />
        )}
        {phase === "ready" && nextCursor && more !== "failed" && (
          <button
            type="button"
            className="sk-btn sk-btn--quiet"
            disabled={more === "busy"}
            onClick={loadMore}
          >
            {t.more}
          </button>
        )}
        {failed && (
          <ContactFailure
            failure={failed.failure}
            message={
              failed.action === "create"
                ? t.contactCreateFailed
                : t.contactWriteFailed
            }
            labels={t}
            onReload={onChanged}
            onRetry={() => again.current?.()}
          />
        )}
      </div>
    </KeyScope>
  );
}

/**
 * `removeLink` from a detail view's ⋯ (design system §3, Tillbakarad and Ångra): one entry per link, no
 * confirmation. The row stays where it was with `linkRemoved` and Ångra (the agenda's UndoMeta) while Ångra
 * holds; then it leaves (`hidden`). Ångra links it back. `send` writes the link (`link` true) or removes it, with the
 * action's idempotency key.
 */
export function useLinkUndo(
  send: (id: string, link: boolean, key: string) => Promise<unknown>,
) {
  const write = useWorkWrite();
  // "gone": removed, Ångra offered; "hidden": removed and the time to undo is up.
  const [state, setState] = useState<
    Record<string, "gone" | "hidden" | undefined>
  >({});
  const again = useRef<() => void>(undefined);
  function set(id: string, link: boolean) {
    again.current = () => set(id, link);
    void write
      .run(JSON.stringify([id, link]), (key) => send(id, link, key))
      .then((done) => {
        if (done !== undefined)
          setState((all) => ({ ...all, [id]: link ? undefined : "gone" }));
      });
  }
  return {
    ...write,
    state,
    set,
    expire: (id: string) => setState((all) => ({ ...all, [id]: "hidden" })),
    retry: () => again.current?.(),
  };
}
