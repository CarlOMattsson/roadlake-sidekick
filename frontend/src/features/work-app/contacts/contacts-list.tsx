import {
  useContext,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import "./contacts.css";
import type { WorkLabels } from "../shared/labels";
import { EmptyState, ErrorNotice } from "../../mcp-apps/ui/states";
import { MessageBox } from "../../mcp-apps/ui/message-box";
import { useToolSupport } from "../../mcp-apps/tool-support";
import {
  RoomMessageContext,
  RoomSurfaceContext,
} from "../../mcp-apps/ui/room-context";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import { RoomHead } from "../../mcp-apps/ui/room-head";
import { useSplitList } from "../../mcp-apps/ui/split-layout";
import { contactsRoomLabelsFor } from "./contacts-room-labels";
import { useShortcuts } from "../../mcp-apps/ui/shortcuts";
import { CloseIcon, PlusIcon, SearchIcon } from "../../mcp-apps/ui/icons";
import { controlEntry } from "../../mcp-apps/ui/control-entry";
import { appLocale } from "../../mcp-apps/app-locale";
import { roomEnabled } from "../../mcp-apps/enabled-rooms";
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
import {
  ContactsMenu,
  ContactsMoreButton,
  useContactsMore,
} from "./contacts-more";
import { NewContact } from "./new-contact";
import type { CreateRequest, HeadPress } from "./new-contact-state";
import { useContactListKeys } from "./use-contact-list-keys";
import { useArchivedMatches } from "./use-archived-matches";
import { useContactsList } from "./use-contacts-list";
import { TagFilter } from "../../mcp-apps/ui/tags";
import { useWorkTags } from "../shared/work-tags";
import { tagLabelsFor } from "../../mcp-apps/ui/tag-labels";
import { tagLabelOf } from "../../mcp-apps/ui/tag-vocabulary";

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
 *
 * In a wide frame (the shell offers a place for the room head, `headSlot`) the room head (ui/room-head.tsx) holds the
 * tools at their fixed places: search (its key "/" puts the focus in the field), + (key "n") and ⋯; the field then
 * stands alone at the top of the list. Without that place (a phone, a narrow frame, an inline card) the field
 * carries its own + and ⋯ as before.
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
  /** `label` is the opened record's name, for the shell's Back ("‹ Anna") and the host's model-context line. */
  onOpen: (frame: WorkFrame, label?: string) => void;
  /** Turns on "/" for the search field; only a fullscreen caller passes true (design language 3.8). */
  shortcuts?: boolean;
  /** Reads the list again in place when it changes; the value at mount is not a request. Search and archive switch stay. */
  refreshKey?: number;
  /** Opens another room; the ⋯ menu then ends with the Control room's entry (design system §3, room head). Absent: no entry. */
  onRoute?: (target: RoomTarget) => void;
}) {
  // The host's message function: the empty list's example sends itself to Claude.
  const sendMessage = useContext(RoomMessageContext);
  const words = contactsRoomLabelsFor(t.dateLocale);
  const list = useContactsList({ frame, onChange, transport, refreshKey });
  const { error, cause, more } = list;
  // `createNamed` under a search with no match: each press is a new request, so the field opens again.
  const [createRequest, setCreateRequest] = useState<CreateRequest>();
  const offers = useToolSupport(transport);
  const heading = useRef<HTMLHeadingElement>(null);
  const searchField = useRef<HTMLInputElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  // The "⋯" menu holds the archive switch; it stays mounted (hidden) while closed.
  const moreButton = useRef<HTMLButtonElement>(null);
  const moreMenu = useContactsMore(t.moreActions, moreButton);
  // In a wide frame the room head holds search, + and ⋯ in the shell's row; otherwise the field carries + and ⋯.
  const inBar = Boolean(useContext(RoomSurfaceContext).headSlot);
  const [createPress, setCreatePress] = useState<HeadPress>();
  const [createOpen, setCreateOpen] = useState(false);
  const pressAdd = (key: boolean) =>
    setCreatePress((last) => ({ n: (last?.n ?? 0) + 1, key }));
  const focusSearch = () => searchField.current?.focus();
  // "/" moves to the search field, as in the fullscreen shortcut map (design language 3.8); the room head binds it
  // itself when it is drawn.
  useShortcuts({ "/": focusSearch }, { enabled: shortcuts && !inBar });
  useEffect(() => {
    if (moves > 0) heading.current?.focus({ preventScroll: true });
  }, [moves]);
  const { page } = frame;
  // Beside its Contact (a wide frame), stepping through the rows opens each Contact there.
  const splitList = useSplitList();
  const onKeyDown = useContactListKeys({
    root,
    search: searchField,
    shortcuts,
    locale: t.dateLocale,
    title: t.contacts,
    follow: splitList
      ? (id) => {
          const contact = page?.items.find((item) => item.id === id);
          if (contact) onOpen({ kind: "contact", id }, contact.display_name);
        }
      : undefined,
  });
  const query = frame.q.trim();
  const chosenTags = frame.tags ?? [];
  const fresh = pageMatches(page, query, frame.includeArchived, chosenTags);
  // The tags in use on Contacts, for the filter row; none (or no list_tags on the host) draws no row.
  const vocabulary = useWorkTags(transport, "contact");
  const tagWords = tagLabelsFor(t.dateLocale);
  // A search with no live hit may still have archived ones: the empty list offers to show them.
  const archivedMatches = useArchivedMatches(
    transport,
    query,
    fresh &&
      page.items.length === 0 &&
      !frame.includeArchived &&
      chosenTags.length === 0,
  );

  function created(contact: WorkContactRecord) {
    list.forgetPage();
    onOpen({ kind: "contact", id: contact.id }, contact.display_name);
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
      onOpen={() =>
        onOpen({ kind: "contact", id: contact.id }, contact.display_name)
      }
    />
  );
  // The ⋯ menu, drawn under the field (a phone's panel) or inside the room head's ⋯ (a popover in a wide frame).
  const menu = (
    <ContactsMenu
      more={moreMenu}
      buttonRef={moreButton}
      labels={t}
      includeArchived={frame.includeArchived}
      onArchived={list.changeArchived}
      control={
        onRoute && controlOn
          ? { label: control.label, onOpen: () => onRoute(control.target) }
          : undefined
      }
    />
  );
  return (
    <article className="work-contacts">
      <KeyScope ref={root} onKeyDown={onKeyDown}>
        {/* The room's name is in the room strip, so the heading is for assistive technology only (and the focus
          target after a move). The room head is the search field, then + and ⋯ (design system §3, Rumshuvud). */}
        <h2 ref={heading} tabIndex={-1} className="work-visually-hidden">
          {t.contacts}
        </h2>
        {inBar && (
          // The room head in the shell's row: no tabs (one view), then search, + and ⋯ at their fixed places.
          <RoomHead
            scope="sidekick-work"
            keysTitle={t.contacts}
            tabs={<span className="sk-shell-tabs-fill" aria-hidden="true" />}
            search={{ label: t.searchContacts, onPress: focusSearch }}
            add={{
              label: t.newContact,
              expanded: createOpen,
              onPress: () => pressAdd(false),
              onKey: () => pressAdd(true),
            }}
            addRef={addButton}
            more={
              <>
                <ContactsMoreButton
                  more={moreMenu}
                  buttonRef={moreButton}
                  className="sk-iconbtn sk-room-head__tool"
                />
                {menu}
              </>
            }
          />
        )}
        <div className="work-contacts-head" data-in-bar={inBar || undefined}>
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
            head={
              inBar
                ? {
                    button: addButton,
                    press: createPress,
                    onOpenChange: setCreateOpen,
                  }
                : undefined
            }
            onCreated={created}
            onOpenExisting={(id, name) => onOpen({ kind: "contact", id }, name)}
          />
          {!inBar && (
            <ContactsMoreButton
              more={moreMenu}
              buttonRef={moreButton}
              className="sk-iconbtn work-contacts-more"
            />
          )}
        </div>
        {!inBar && menu}
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
            chosenTags.length > 0 ? (
              // The list is narrowed by tags: it is not empty, so no introduction and no first steps, only the way out.
              <EmptyState
                title={words.noContactsWithTags(
                  chosenTags.map((slug) =>
                    tagLabelOf(slug, vocabulary.suggestions),
                  ),
                  query,
                )}
              >
                <button
                  type="button"
                  className="work-add-row sk-action-row"
                  onClick={() => list.changeTags([])}
                >
                  <CloseIcon />
                  {tagWords.clearLabel}
                </button>
              </EmptyState>
            ) : (
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
                {archivedMatches !== undefined && (
                  <button
                    type="button"
                    className="work-add-row sk-action-row"
                    onClick={() => list.changeArchived(true)}
                  >
                    {words.showArchivedMatches(archivedMatches)}
                  </button>
                )}
                {query && (
                  <button
                    type="button"
                    className="work-add-row sk-action-row"
                    onClick={() => {
                      list.changeQuery("");
                      searchField.current?.focus();
                    }}
                  >
                    <CloseIcon />
                    {words.clearSearch}
                  </button>
                )}
                {/* The hand-made way next to the ask-Claude line: with a search text it creates that Contact at once; without one it opens the create field as + does. */}
                {offers("create_contact") && (
                  <button
                    type="button"
                    className="work-add-row sk-action-row"
                    onClick={() =>
                      setCreateRequest((last) => ({
                        name: query,
                        n: (last?.n ?? 0) + 1,
                        // A named create is made at once (the name is already typed); without a name the field opens.
                        immediate: query !== "",
                      }))
                    }
                  >
                    <PlusIcon />
                    {query ? words.createNamed(query) : words.addContact}
                  </button>
                )}
              </EmptyState>
            )
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
        {fresh && more === "failed" && (
          <MessageBox
            severity="error"
            title={words.moreFailed}
            action={{ label: t.retry, onClick: list.loadMore }}
          />
        )}
        {fresh && page.next_cursor && (
          <button
            type="button"
            className="sk-more"
            disabled={more === "busy"}
            onClick={list.loadMore}
          >
            {t.more}
          </button>
        )}
      </KeyScope>
    </article>
  );
}
