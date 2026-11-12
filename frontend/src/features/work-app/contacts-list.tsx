import {
  useContext,
  useEffect,
  useEffectEvent,
  useId,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import "./contacts.css";
import type { WorkLabels } from "./labels";
import { initialsOf } from "./contact-card";
import { titleProblem } from "./fields";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { Row } from "../mcp-apps/ui/row";
import { EmptyState, ErrorNotice } from "../mcp-apps/ui/states";
import { useToolSupport } from "../mcp-apps/tool-support";
import { RoomMessageContext } from "../mcp-apps/ui/room-context";
import { contactsRoomLabelsFor } from "./contacts-room-labels";
import { useShortcuts } from "../mcp-apps/ui/shortcuts";
import { MoreIcon, PlusIcon, SearchIcon } from "../mcp-apps/ui/icons";
import { CreateField } from "../mcp-apps/ui/create-field";
import { hierarchyDetailLabelsFor } from "./hierarchy-detail-labels";
import { controlEntry } from "../mcp-apps/ui/control-entry";
import { appLocale } from "../mcp-apps/app-locale";
import { roomEnabled } from "../mcp-apps/enabled-rooms";
import { MenuUpdateReminder, useMoreMark } from "../mcp-apps/update-reminder";
import { MenuLicenseRow, useLicenseMenu } from "../mcp-apps/license-mark";
import type { RoomTarget } from "../mcp-apps/room-types";
import {
  isForbidden,
  writeFailure,
  type WorkContactRecord,
  type WorkContactsFrame,
  type WorkContactSummary,
  type WorkContactsPage,
  type WorkFrame,
  type WorkTransport,
  type WriteFailure,
} from "./transport";

/** list_contacts takes q of 1 to 200 characters; an empty search lists every Contact. */
const SEARCH_MAX_LENGTH = 200;
const SEARCH_DEBOUNCE_MS = 300;
/** Letter headings show only when the list holds more Contacts than this; a shorter list is one flat list. */
const LETTER_HEADINGS_ABOVE = 15;

type MorePhase = "idle" | "busy" | "failed";

/** A request to open the create field with a name in it; `n` makes a repeated request with the same name new. */
type CreateRequest = { name: string; n: number };

/** Swedish order: Å, Ä and Ö come after Z. */
let swedishCollator: Intl.Collator | undefined;
function swedish(): Intl.Collator {
  swedishCollator ??= new Intl.Collator("sv");
  return swedishCollator;
}
const LETTER = /^\p{L}$/u;
const stickyLetter: CSSProperties = {
  position: "sticky",
  top: "var(--sk-sticky-top, 0px)",
  // Over the rows' open covers (positioned), so a tap on the letter never opens the contact scrolled under it.
  zIndex: 1,
  margin: 0,
  padding: "0.25rem 0",
  background: "var(--work-bg)",
};

function matches(
  page: WorkContactsPage | undefined,
  q: string,
  includeArchived: boolean,
): page is WorkContactsPage {
  return page?.q === q && page.includeArchived === includeArchived;
}

/** The section letter of a name: its first letter in upper case, or "#" when it does not start with one. */
function sectionOf(name: string): string {
  const first = Array.from(name.trim())[0]?.toLocaleUpperCase("sv") ?? "";
  return LETTER.test(first) ? first : "#";
}

/** The Contacts by name, in Swedish order. */
function sortedByName(items: WorkContactSummary[]): WorkContactSummary[] {
  return [...items].sort((a, b) =>
    swedish().compare(a.display_name, b.display_name),
  );
}

/** Groups Contacts into sections by name, each section sorted by name in Swedish order. */
function sectionsOf(
  items: WorkContactSummary[],
): { letter: string; contacts: WorkContactSummary[] }[] {
  const byLetter = new Map<string, WorkContactSummary[]>();
  for (const contact of sortedByName(items)) {
    const letter = sectionOf(contact.display_name);
    byLetter.set(letter, [...(byLetter.get(letter) ?? []), contact]);
  }
  return [...byLetter]
    .map(([letter, contacts]) => ({ letter, contacts }))
    .sort((a, b) => swedish().compare(a.letter, b.letter));
}

/**
 * The profile line of a Contact: "relationship · role · organization" of the fields that are set, or ""
 * when none is. The list row's meta line and the line under the name in the Contact's own view both use
 * it, so the two say the same; each cuts the last part with an ellipsis. The address is never shown.
 */
export function contactMeta(
  contact: Pick<WorkContactSummary, "relationship" | "role" | "organization">,
): string {
  return [contact.relationship, contact.role, contact.organization]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(" · ");
}

/**
 * One Contact in the list. A round grey avatar with the initials leads the row, hidden from assistive
 * tech because the name is read out. The name opens it; an archived Contact shows its label as a chip
 * in the same row, so the chip is part of the row's accessible name.
 */
function ContactRow({
  contact,
  archivedLabel,
  onOpen,
}: {
  contact: WorkContactSummary;
  archivedLabel: string;
  onOpen: () => void;
}) {
  return (
    <Row
      leading={
        <span aria-hidden="true" className="work-contact-avatar">
          {initialsOf(contact.display_name)}
        </span>
      }
      primary={contact.display_name}
      secondary={contactMeta(contact) || undefined}
      trailing={
        contact.archived ? (
          <span className="work-chip">{archivedLabel}</span>
        ) : undefined
      }
      navigates
      onOpen={onOpen}
    />
  );
}

/**
 * The Contact list: a search field (debounced, an answer to an older search is ignored), a switch
 * for archived Contacts, rows that open a Contact, Show more and a form for a new Contact. The
 * search and the page live in the frame, so coming back from a Contact shows the same list.
 */
export function ContactsView({
  frame,
  onChange,
  transport,
  labels: t,
  moves,
  onOpen,
  shortcuts = false,
  refreshKey,
  onRoute,
}: {
  frame: WorkContactsFrame;
  onChange: (before: WorkContactsFrame, next: WorkContactsFrame) => void;
  transport: WorkTransport;
  labels: WorkLabels;
  moves: number;
  onOpen: (frame: WorkFrame) => void;
  /** Turns on "/" for the search field; only a fullscreen caller passes true (design language 3.8). */
  shortcuts?: boolean;
  /** Reads the list again in place when it changes; the value at mount is not a request. Search and archive switch stay. */
  refreshKey?: number;
  /** Opens another room; the ⋯ menu then ends with "Kontroll" (design system §3, Rumshuvud). Absent: no entry. */
  onRoute?: (target: RoomTarget) => void;
}) {
  // The host's message function: the empty list's example sends itself to Claude.
  const sendMessage = useContext(RoomMessageContext);
  const words = contactsRoomLabelsFor(t.dateLocale);
  const [error, setError] = useState<"forbidden" | "error">();
  // What the failed read threw, for the error notice's second line.
  const [cause, setCause] = useState<unknown>();
  const [more, setMore] = useState<MorePhase>("idle");
  // "Skapa kontakt "Zlatan"" under a search with no match: each press is a new request, so the field opens again.
  const [createRequest, setCreateRequest] = useState<CreateRequest>();
  const offers = useToolSupport(transport);
  const heading = useRef<HTMLHeadingElement>(null);
  const searchField = useRef<HTMLInputElement>(null);
  const moreButton = useRef<HTMLButtonElement>(null);
  const moreMark = useMoreMark(t.moreActions);
  // The "⋯" panel holds the archive switch; it stays mounted (hidden) while closed.
  const [menuOpen, setMenuOpen] = useState(false);
  useLicenseMenu(moreButton, () => setMenuOpen(true));
  const panelId = useId();
  // "/" moves to the search field, as in the fullscreen shortcut map (design language 3.8).
  useShortcuts(
    { "/": () => searchField.current?.focus() },
    { enabled: shortcuts },
  );
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // Bumped by every change of the search and every read; only the newest answer is applied.
  const ticket = useRef(0);
  // The newest frame this view has emitted, so two changes in one event do not use a stale base.
  const latest = useRef(frame);
  const { page } = frame;
  const query = frame.q.trim();
  const fresh = matches(page, query, frame.includeArchived);

  function emit(patch: Partial<WorkContactsFrame>) {
    const next = { ...latest.current, ...patch };
    onChange(latest.current, next);
    latest.current = next;
  }
  /** Reads the first page; the answer replaces the page unless a newer search has started. */
  function fetchFirst(q: string, includeArchived: boolean, current: number) {
    transport
      .listContacts({ q, includeArchived })
      .then((result) => {
        if (current !== ticket.current) return;
        emit({
          page: {
            items: result.items,
            next_cursor: result.next_cursor,
            q,
            includeArchived,
          },
        });
      })
      .catch((failure: unknown) => {
        if (current !== ticket.current) return;
        setCause(failure);
        setError(isForbidden(failure) ? "forbidden" : "error");
      });
  }
  function read(q: string, includeArchived: boolean) {
    setError(undefined);
    setMore("idle");
    fetchFirst(q, includeArchived, ++ticket.current);
  }

  // A frame without a page, or whose search was interrupted before it was read, reads on mount.
  const readIfMissing = useEffectEvent(() => {
    const start = latest.current;
    if (!matches(start.page, start.q.trim(), start.includeArchived))
      fetchFirst(start.q.trim(), start.includeArchived, ++ticket.current);
  });
  useEffect(() => {
    const marker = ticket;
    const pendingSearch = timer;
    readIfMissing();
    return () => {
      clearTimeout(pendingSearch.current);
      marker.current++;
    };
  }, [transport]);
  useEffect(() => {
    if (moves > 0) heading.current?.focus({ preventScroll: true });
  }, [moves]);
  // A changed refreshKey reads the list again with the same search and archive switch, in place.
  const seenRefreshKey = useRef(refreshKey);
  const readAgain = useEffectEvent(() =>
    read(frame.q.trim(), frame.includeArchived),
  );
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === seenRefreshKey.current)
      return;
    seenRefreshKey.current = refreshKey;
    readAgain();
  }, [refreshKey]);

  function changeQuery(value: string) {
    emit({ q: value });
    // An answer to the previous search, or a Show more of it, is now old.
    ticket.current++;
    clearTimeout(timer.current);
    setError(undefined);
    setMore("idle");
    const q = value.trim();
    if (matches(latest.current.page, q, latest.current.includeArchived)) return;
    timer.current = setTimeout(
      () => read(q, latest.current.includeArchived),
      SEARCH_DEBOUNCE_MS,
    );
  }
  function changeArchived(includeArchived: boolean) {
    emit({ includeArchived });
    clearTimeout(timer.current);
    ticket.current++;
    setError(undefined);
    setMore("idle");
    const q = latest.current.q.trim();
    if (matches(latest.current.page, q, includeArchived)) return;
    read(q, includeArchived);
  }
  function loadMore() {
    const shown = latest.current.page;
    if (!shown?.next_cursor || more === "busy") return;
    const current = ticket.current;
    setMore("busy");
    transport
      .listContacts(
        { q: shown.q, includeArchived: shown.includeArchived },
        shown.next_cursor,
      )
      .then((result) => {
        const base = latest.current.page;
        if (current !== ticket.current || !base) return;
        const seen = new Set(base.items.map((contact) => contact.id));
        emit({
          page: {
            ...base,
            items: [
              ...base.items,
              ...result.items.filter((contact) => !seen.has(contact.id)),
            ],
            next_cursor: result.next_cursor,
          },
        });
        setMore("idle");
      })
      .catch(() => {
        if (current === ticket.current) setMore("failed");
      });
  }
  function created(contact: WorkContactRecord) {
    // The list read before does not have the new Contact: it is read again when it is shown next.
    emit({ page: undefined });
    onOpen({ kind: "contact", id: contact.id });
  }

  const loading = !fresh && !error;
  const control = controlEntry(appLocale());
  const controlOn = roomEnabled("control");
  const rowOf = (contact: WorkContactSummary) => (
    <ContactRow
      key={contact.id}
      contact={contact}
      archivedLabel={t.archivedLabel}
      onOpen={() => onOpen({ kind: "contact", id: contact.id })}
    />
  );
  return (
    <article className="work-contacts">
      {/* The room's name is in the room strip, so the heading is for assistive technology only (and the focus
          target after a move). The room head is the search field, then + and ⋯ (design system §3, Rumshuvud). */}
      <h2 ref={heading} tabIndex={-1} className="work-visually-hidden">
        {t.contacts}
      </h2>
      <div className="work-contacts-head">
        {/* The one standing field of the app means search, with the magnifier at its left edge (§3, Skapa). */}
        <SearchIcon />
        <input
          ref={searchField}
          type="search"
          className="work-contacts-search"
          aria-label={t.searchContacts}
          placeholder={t.searchContacts}
          enterKeyHint="search"
          value={frame.q}
          maxLength={SEARCH_MAX_LENGTH}
          onChange={(event) => changeQuery(event.target.value)}
        />
        <NewContact
          transport={transport}
          labels={t}
          request={createRequest}
          onCreated={created}
        />
        <button
          ref={moreButton}
          type="button"
          className="sk-iconbtn work-contacts-more"
          aria-label={moreMark.label}
          aria-expanded={menuOpen}
          aria-controls={panelId}
          onClick={() => setMenuOpen(!menuOpen)}
        >
          <MoreIcon />
          {moreMark.dot}
        </button>
      </div>
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- a container-level handler for keys bubbling up from the focusable controls inside it (Escape closes); the container itself is not a control. */}
      <div
        id={panelId}
        className="work-contacts-panel work-contact-menu"
        hidden={!menuOpen}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.stopPropagation();
          setMenuOpen(false);
          moreButton.current?.focus();
        }}
      >
        <label className="work-toggle work-contact-menu-item">
          <input
            type="checkbox"
            checked={frame.includeArchived}
            onChange={(event) => changeArchived(event.target.checked)}
          />
          {t.showArchived}
        </label>
        {onRoute && controlOn && (
          <button
            type="button"
            className="work-contact-menu-item"
            onClick={() => onRoute(control.target)}
          >
            {control.label}
          </button>
        )}
        <MenuUpdateReminder />
        <MenuLicenseRow />
      </div>
      {loading && <p role="status">{t.loading}</p>}
      {error === "forbidden" && <p>{t.contactsForbidden}</p>}
      {error === "error" && (
        // The family's read error, as in every room: what could not be read, what the failure says, and Retry.
        <ErrorNotice
          locale={t.dateLocale}
          subject="contacts"
          cause={cause}
          onRetry={() => read(query, frame.includeArchived)}
        />
      )}
      {fresh &&
        (page.items.length === 0 ? (
          <EmptyState
            title={query ? t.noContactMatches(query) : t.noAnyContacts}
            hint={query ? undefined : words.emptyHint}
            ask={{
              locale: t.dateLocale,
              example: query ? words.createNamedAsk(query) : words.emptyAsk,
              onSend: sendMessage
                ? () =>
                    void sendMessage(
                      query ? words.createNamedAsk(query) : words.emptyAsk,
                    )
                : undefined,
            }}
          >
            {query && offers("create_contact") && (
              <button
                type="button"
                className="work-add-row sk-action-row"
                onClick={() =>
                  setCreateRequest((last) => ({
                    name: query,
                    n: (last?.n ?? 0) + 1,
                  }))
                }
              >
                <PlusIcon />
                {words.createNamed(query)}
              </button>
            )}
          </EmptyState>
        ) : page.items.length > LETTER_HEADINGS_ABOVE ? (
          <div role="group" aria-label={t.contacts}>
            {sectionsOf(page.items).map((section) => (
              // The letter heading and its rows are a plain block with a list of its own; the block is not a
              // list item, so no list holds a non-listitem child.
              <div key={section.letter} className="work-contact-letter">
                <h3 style={stickyLetter}>{section.letter}</h3>
                <ul className="work-contact-list">
                  {section.contacts.map(rowOf)}
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <ul className="work-contact-list" aria-label={t.contacts}>
            {sortedByName(page.items).map(rowOf)}
          </ul>
        ))}
      {fresh && more === "busy" && <p role="status">{t.loading}</p>}
      {fresh && more === "failed" && <p role="alert">{t.failed}</p>}
      {fresh && page.next_cursor && (
        <button type="button" disabled={more === "busy"} onClick={loadMore}>
          {t.more}
        </button>
      )}
    </article>
  );
}

/**
 * "Ny kontakt" behind + in the room head (design system §3, Skapa): + opens the shared create field under the head,
 * and a new Contact needs only its name. The same name sends one key, so a retry after a lost answer replays the result
 * instead of creating a second Contact. The created Contact is handed to the parent, which opens it. Esc and × close
 * the field and return the focus to +.
 */
function NewContact({
  transport,
  labels: t,
  request,
  onCreated,
}: {
  transport: WorkTransport;
  labels: WorkLabels;
  /** Opens the field with this name in it (a search with no match); a new request opens it again. */
  request?: CreateRequest;
  onCreated: (contact: WorkContactRecord) => void;
}) {
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<WriteFailure>();
  const openButton = useRef<HTMLButtonElement>(null);
  const lastName = useRef("");
  // Synchronous guard against a second create before React re-renders.
  const writing = useRef(false);
  // The key of each name whose delivery is not settled: the same name again reuses its own key.
  const pendingWrite = useRef(new Map<string, PendingKey>());
  // What the create field holds now: a retry that succeeds empties it only if it still holds the retried name.
  const draft = useRef("");
  // Bumped when Retry succeeds and the field still holds that name: it then remounts empty.
  const [fieldKey, setFieldKey] = useState(0);
  const mounted = useRef(true);
  const dl = hierarchyDetailLabelsFor(t.dateLocale);
  // A new request opens the field afresh with its name; derived while rendering, as the room does for a new result.
  const [seenRequest, setSeenRequest] = useState(request);
  const [prefill, setPrefill] = useState("");
  if (request !== seenRequest) {
    setSeenRequest(request);
    if (request) {
      setPrefill(request.name);
      setFieldKey((key) => key + 1);
      setOpen(true);
    }
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // The field holds the prefilled name before any typing, so the draft follows it.
  useEffect(() => {
    draft.current = prefill;
  }, [prefill, fieldKey]);

  function retry() {
    const name = lastName.current;
    void submit(name).then((created) => {
      if (created && mounted.current && draft.current.trim() === name.trim()) {
        draft.current = "";
        setPrefill("");
        setFieldKey((key) => key + 1);
      }
    });
  }

  function close() {
    draft.current = "";
    setPrefill("");
    setOpen(false);
    setProblem(undefined);
    setFailure(undefined);
    openButton.current?.focus();
  }
  /** true when the Contact was created; false when the write was refused or failed (the create field keeps the name). */
  function submit(name: string): Promise<boolean> {
    if (writing.current) return Promise.resolve(false);
    lastName.current = name;
    if (titleProblem(name) === "tooLong") {
      setProblem(t.nameTooLong);
      return Promise.resolve(false);
    }
    const pendingKey = keyFor(
      pendingWrite.current.get(name),
      JSON.stringify([name]),
    );
    pendingWrite.current.set(name, pendingKey);
    writing.current = true;
    setBusy(true);
    setProblem(undefined);
    setFailure(undefined);
    return transport
      .createContact({ display_name: name }, pendingKey.key)
      .then((result) => {
        if (mounted.current) {
          pendingWrite.current.delete(name);
          onCreated(result.contact);
        }
        return true;
      })
      .catch((error: unknown) => {
        if (mounted.current) setFailure(writeFailure(error));
        return false;
      })
      .finally(() => {
        writing.current = false;
        if (mounted.current) setBusy(false);
      });
  }

  return (
    <>
      <button
        ref={openButton}
        type="button"
        className="sk-iconbtn sk-iconbtn--primary work-contacts-add"
        aria-label={t.newContact}
        title={t.newContact}
        aria-expanded={open}
        onClick={() => {
          if (open) close();
          else {
            setPrefill("");
            setOpen(true);
          }
        }}
      >
        <PlusIcon />
      </button>
      {open && (
        <div
          className="work-contacts-create"
          aria-busy={busy}
          onChange={(event) => {
            draft.current = (event.target as HTMLInputElement).value;
          }}
        >
          <CreateField
            key={fieldKey}
            initialText={prefill}
            label={t.newContact}
            placeholder={dl.newContactExample}
            closeLabel={dl.close}
            addLabel={dl.add}
            onCreate={(text) =>
              submit(text).then((ok) => {
                // The field empties itself on success: the draft follows it.
                if (ok && draft.current.trim() === text.trim())
                  draft.current = "";
                return ok;
              })
            }
            onClose={close}
          />
          {problem && <p role="alert">{problem}</p>}
          {failure === "conflict" && <p role="alert">{t.createConflict}</p>}
          {failure === "forbidden" && <p>{t.forbiddenWrite}</p>}
          {failure === "invalid" && <p role="alert">{t.invalidChange}</p>}
          {failure === "not_found" && <p role="alert">{t.notFound}</p>}
          {failure === "failed" && (
            <p role="alert">
              {t.contactCreateFailed}{" "}
              <button
                type="button"
                className="sk-btn--quiet sk-btn--compact"
                disabled={busy}
                onClick={retry}
              >
                {t.retry}
              </button>
            </p>
          )}
        </div>
      )}
    </>
  );
}
