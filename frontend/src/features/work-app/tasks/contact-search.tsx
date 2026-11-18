import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { CloseIcon } from "../../mcp-apps/ui/icons";
import { contactMeta } from "../contacts/contacts-sections";
import { initialsOf } from "../../mcp-apps/ui/initials";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import type { WorkLabels } from "../shared/labels";
import { useSingleFlight } from "../shared/use-single-flight";
import {
  isForbidden,
  type WorkContactSummary,
  type WorkTransport,
} from "../transport/transport";

/** list_contacts takes q of 1 to 200 characters; the view searches from two letters on. */
const SEARCH_MIN_LENGTH = 2;
const SEARCH_MAX_LENGTH = 200;
const SEARCH_DEBOUNCE_MS = 300;

type SearchPhase = "idle" | "loading" | "ready" | "forbidden" | "error";
type MorePhase = "idle" | "busy" | "failed";

/**
 * The search over the owner's Contacts that the link sheet and the waiting-on picker share: each change of the
 * query starts a debounced search, an answer to an older query is ignored, and "Show more" pages the same search.
 */
export function useContactSearch(transport: WorkTransport) {
  const [query, setQuery] = useState("");
  const [phase, setPhase] = useState<SearchPhase>("idle");
  const [results, setResults] = useState<WorkContactSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [more, setMore] = useState<MorePhase>("idle");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // Bumped by every query change and every search request; only the newest answer is applied.
  const ticket = useRef(0);
  // One "Show more" page per query, claimed before React re-renders the button.
  const pages = useSingleFlight();
  // The trimmed query the shown results belong to, so Show more pages the same search.
  const searched = useRef("");
  useEffect(() => {
    const marker = ticket;
    const pendingSearch = timer;
    return () => {
      clearTimeout(pendingSearch.current);
      marker.current++;
    };
  }, []);

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

  function change(value: string) {
    setQuery(value);
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

  return {
    query,
    phase,
    results,
    nextCursor,
    more,
    change,
    loadMore,
    /** Runs the last search again after it failed. */
    retry: () => {
      setPhase("loading");
      runSearch(searched.current);
    },
  };
}

/** The state of a Contact search, as `useContactSearch` returns it. */
export type ContactSearch = ReturnType<typeof useContactSearch>;

/**
 * One hit of the search: a button that picks the Contact (the 32 avatar and the name). With `note` the Contact is shown, not
 * offered: a row with the note under the name.
 */
export function ContactHit({
  contact,
  note,
  disabled,
  busy,
  onPick,
}: {
  contact: WorkContactSummary;
  note?: string;
  disabled: boolean;
  busy: boolean;
  onPick: () => void;
}) {
  const avatar = (
    <span className="work-link-avatar" aria-hidden="true">
      {initialsOf(contact.display_name)}
    </span>
  );
  const profile = contactMeta(contact);
  const name = (
    <span className="work-contact-sheet-name">
      {contact.display_name}
      {profile && <span className="work-contact-sheet-meta">{profile}</span>}
      {note !== undefined && (
        <span className="work-contact-sheet-meta">{note}</span>
      )}
    </span>
  );
  if (note !== undefined)
    return (
      <div className="work-contact-sheet-row">
        {avatar}
        {name}
      </div>
    );
  return (
    <button
      type="button"
      className="work-contact-sheet-row"
      disabled={disabled}
      aria-busy={busy || undefined}
      onClick={onPick}
    >
      {avatar}
      {name}
    </button>
  );
}

/**
 * The sheet over the owner's Contacts: the title, the hits and the search field at the sheet's foot (see task-contacts.css).
 * What a hit does is the caller's (`renderHit`); `empty` is what follows "no contact matches" (a create row), and `footer`
 * is the failure line of the caller's own write. Esc and × call `onClose`.
 */
export function ContactSearchSheet({
  title,
  labels: t,
  search,
  busy,
  inputRef,
  onClose,
  renderHit,
  empty,
  footer,
}: {
  title: string;
  labels: WorkLabels;
  search: ContactSearch;
  /** The caller's write is running: the close button is off. */
  busy: boolean;
  inputRef?: RefObject<HTMLInputElement | null>;
  onClose: () => void;
  renderHit: (contact: WorkContactSummary) => ReactNode;
  empty?: (query: string) => ReactNode;
  footer?: ReactNode;
}) {
  const inputId = useId();
  const hintId = useId();
  const { query, phase, results, nextCursor, more } = search;
  const q = query.trim();
  return (
    <KeyScope
      className="work-contact-sheet"
      aria-busy={busy || undefined}
      onEscape={onClose}
    >
      <label htmlFor={inputId} className="work-contact-sheet-title">
        {title}
      </label>
      {/* The field comes before the hits for the keyboard and screen readers; the sheet draws it at its foot. */}
      <div className="sk-createfield work-contact-sheet-field">
        <input
          id={inputId}
          ref={inputRef}
          className="sk-createfield__input"
          type="search"
          enterKeyHint="search"
          autoComplete="off"
          placeholder={t.contactSearchPlaceholder}
          value={query}
          maxLength={SEARCH_MAX_LENGTH}
          aria-describedby={phase === "idle" ? hintId : undefined}
          onChange={(event) => search.change(event.target.value)}
          // The search runs as it is typed; Enter must not submit a form the sheet stands in (the Task editor's).
          onKeyDown={(event) => {
            if (event.key === "Enter") event.preventDefault();
          }}
        />
        <button
          type="button"
          className="sk-createfield__btn"
          aria-label={t.closeContactSearch}
          disabled={busy}
          onClick={onClose}
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
            onRetry={search.retry}
          />
        )}
        {phase === "ready" && results.length > 0 && (
          <ul className="work-contact-sheet-list">
            {results.map((contact) => (
              <li key={contact.id}>{renderHit(contact)}</li>
            ))}
          </ul>
        )}
        {phase === "ready" && results.length === 0 && (
          <>
            <p className="work-contact-sheet-note">{t.noContactMatches(q)}</p>
            {empty?.(q)}
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
            onRetry={search.loadMore}
          />
        )}
        {phase === "ready" && nextCursor && more !== "failed" && (
          <button
            type="button"
            className="sk-btn sk-btn--quiet"
            disabled={more === "busy"}
            onClick={search.loadMore}
          >
            {t.more}
          </button>
        )}
        {footer}
      </div>
    </KeyScope>
  );
}
