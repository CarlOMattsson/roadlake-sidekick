import {
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import "./contacts.css";
import type { WorkLabels } from "../shared/labels";
import { EmptyState, ErrorNotice } from "../../mcp-apps/ui/states";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { RoomMessageContext } from "../../mcp-apps/ui/room-context";
import { contactsRoomLabelsFor } from "./contacts-room-labels";
import { useShortcuts } from "../../mcp-apps/ui/shortcuts";
import { MoreIcon, PlusIcon, SearchIcon } from "../../mcp-apps/ui/icons";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import { controlEntry } from "../../mcp-apps/ui/control-entry";
import { appLocale } from "../../mcp-apps/app-locale";
import { roomEnabled } from "../../mcp-apps/enabled-rooms";
import {
  MenuUpdateReminder,
  useMoreMark,
} from "../../mcp-apps/update-reminder";
import { MenuLicenseRow, useLicenseMenu } from "../../mcp-apps/license-mark";
import type { RoomTarget } from "../../mcp-apps/room-types";
import type {
  WorkContactRecord,
  WorkContactsFrame,
  WorkContactSummary,
  WorkFrame,
  WorkTransport,
} from "../transport/transport";
import { ContactRow } from "./contact-row";
import {
  LETTER_HEADINGS_ABOVE,
  sectionsOf,
  sortedByName,
} from "./contacts-sections";
import { pageMatches } from "./contacts-list-state";
import { NewContact } from "./new-contact";
import type { CreateRequest } from "./new-contact-state";
import { useContactsList } from "./use-contacts-list";
import { TagFilter } from "../../mcp-apps/ui/tags";
import { useTagVocabulary } from "../../mcp-apps/ui/tag-vocabulary";
import { tagLabelsFor } from "../../mcp-apps/ui/tag-labels";

/** list_contacts takes q of 1 to 200 characters; an empty search lists every Contact. */
const SEARCH_MAX_LENGTH = 200;

const stickyLetter: CSSProperties = {
  position: "sticky",
  top: "var(--sk-sticky-top, 0px)",
  // Over the rows' open covers (positioned), so a tap on the letter never opens the contact scrolled under it.
  zIndex: 1,
  margin: 0,
  padding: "0.25rem 0",
  background: "var(--work-bg)",
};

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
  const list = useContactsList({ frame, onChange, transport, refreshKey });
  const { error, cause, more } = list;
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
  useEffect(() => {
    if (moves > 0) heading.current?.focus({ preventScroll: true });
  }, [moves]);
  const { page } = frame;
  const query = frame.q.trim();
  const chosenTags = frame.tags ?? [];
  const fresh = pageMatches(page, query, frame.includeArchived, chosenTags);
  // The tags in use on Contacts, for the filter row; none (or no list_tags on the host) draws no row.
  const vocabulary = useTagVocabulary(
    offers("list_tags") ? transport.listTags : undefined,
    "contact",
  );
  const tagWords = tagLabelsFor(t.dateLocale);

  function created(contact: WorkContactRecord) {
    list.forgetPage();
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
      knownTags={vocabulary.suggestions}
      locale={t.dateLocale}
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
          onChange={(event) => list.changeQuery(event.target.value)}
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
      <KeyScope
        id={panelId}
        className="work-contacts-panel work-contact-menu"
        hidden={!menuOpen}
        onEscape={() => {
          setMenuOpen(false);
          moreButton.current?.focus();
        }}
      >
        <label className="work-toggle work-contact-menu-item">
          <input
            type="checkbox"
            checked={frame.includeArchived}
            onChange={(event) => list.changeArchived(event.target.checked)}
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
      </KeyScope>
      <TagFilter
        options={vocabulary.options}
        selected={chosenTags}
        onChange={list.changeTags}
        locale={t.dateLocale}
      />
      {fresh && chosenTags.length > 0 && (
        <p role="status" className="work-visually-hidden">
          {tagWords.filtered(chosenTags)}
        </p>
      )}
      {loading && <p role="status">{t.loading}</p>}
      {error === "forbidden" && <p>{t.contactsForbidden}</p>}
      {error === "error" && (
        // The family's read error, as in every room: what could not be read, what the failure says, and Retry.
        <ErrorNotice
          locale={t.dateLocale}
          subject="contacts"
          cause={cause}
          onRetry={() => list.read()}
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
        <button
          type="button"
          disabled={more === "busy"}
          onClick={list.loadMore}
        >
          {t.more}
        </button>
      )}
    </article>
  );
}
