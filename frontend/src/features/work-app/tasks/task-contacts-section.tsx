import type { RefObject } from "react";
import type { WorkLabels } from "../shared/labels";
import { WriteNotice } from "../shared/manage-controls";
import { manageLabelsFor } from "../shared/manage-labels";
import { linksLabelsFor } from "../shared/links-labels";
import { initialsOf } from "../contacts/contact-card";
import { LinkedRow, LinkedRowTip, linkedRowHint } from "../shared/linked-row";
import { LinkContact, type useLinkUndo } from "./task-contacts";
import { OpenChevron, RowUndo } from "./task-detail-controls";
import type {
  WorkContact,
  WorkFrame,
  WorkTransport,
} from "../transport/transport";
import type { PagedSection } from "../view/parts/use-detail-frame";

/**
 * The Contacts section of a Task: the linked Contacts as rows that open them, "Show more", and the link
 * control. It loads and fails on its own (`contacts`), so the Task itself stays visible.
 */
export function TaskContactsSection({
  taskId,
  transport,
  labels: t,
  contacts,
  unlinks,
  unlinkOffered,
  heading,
  contactsOpen,
  linkOffered,
  createOffered,
  onOpen,
  onReloadContacts,
}: {
  taskId: string;
  transport: WorkTransport;
  labels: WorkLabels;
  contacts: PagedSection<WorkContact>;
  /** "Ta bort koppling" in a row's own menu: the row stays with its Ångra until the list is read again. */
  unlinks: ReturnType<typeof useLinkUndo>;
  /** Whether the host answers unlink and link (for its Ångra); without both, a row has no menu. */
  unlinkOffered: boolean;
  heading: RefObject<HTMLHeadingElement | null>;
  contactsOpen?: boolean;
  /** Whether the host answers link_contact_to_task; without it no link control is drawn. */
  linkOffered: boolean;
  /** Whether the host answers create_contact, so a search without a hit can create the Contact it names. */
  createOffered: boolean;
  onOpen: (frame: WorkFrame, label?: string) => void;
  /** Reads the list again after a link or unlink; the list is replaced, not appended. */
  onReloadContacts: () => void;
}) {
  const links = linksLabelsFor(t.dateLocale);
  const { phase, items, more, nextCursor } = contacts;
  return (
    <>
      <h3 ref={heading} tabIndex={-1}>
        {t.contacts}
      </h3>
      {!contactsOpen && (
        <p>
          <button
            type="button"
            className="work-nav"
            onClick={() =>
              onOpen({
                kind: "contacts",
                q: "",
                includeArchived: false,
              })
            }
          >
            {t.allContacts}
          </button>
        </p>
      )}
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "forbidden" && <p>{t.contactsForbidden}</p>}
      {phase === "error" && (
        <p role="alert">
          {t.failed}{" "}
          <button type="button" onClick={contacts.retry}>
            {t.retry}
          </button>
        </p>
      )}
      {phase === "ready" && (
        <>
          {items.length ? (
            <ul className="work-list">
              {/* A linked Contact is a row that opens it: avatar 32 in the leading column, the name on 52 and ›
                      (§3, Chevronregeln). Removing the link is in the row's own menu (long press, right click,
                      Shift+F10); the row then offers Ångra. */}
              {items.map((contact) => {
                const gone = unlinks.state[contact.id];
                return (
                  gone !== "hidden" && (
                    <LinkedRow
                      key={contact.id}
                      title={contact.display_name}
                      gone={gone === "gone"}
                      busy={unlinks.busy}
                      onRemove={
                        unlinkOffered
                          ? () => unlinks.set(contact.id, false)
                          : undefined
                      }
                      labels={t}
                    >
                      <div className="work-agenda-line">
                        <span className="work-link-avatar" aria-hidden="true">
                          {initialsOf(contact.display_name)}
                        </span>
                        <div className="work-agenda-body">
                          <button
                            type="button"
                            aria-keyshortcuts={
                              unlinkOffered && !gone ? "Shift+F10" : undefined
                            }
                            aria-description={
                              unlinkOffered && !gone
                                ? linkedRowHint(t)
                                : undefined
                            }
                            onClick={() =>
                              onOpen(
                                { kind: "contact", id: contact.id },
                                contact.display_name,
                              )
                            }
                          >
                            {contact.display_name}
                          </button>
                          {gone && (
                            <p role="status" className="work-card-meta">
                              {links.linkRemoved}
                            </p>
                          )}
                        </div>
                        {gone ? (
                          <RowUndo
                            label={t.agendaUndo}
                            disabled={unlinks.busy}
                            onUndo={() => unlinks.set(contact.id, true)}
                            onExpire={() => unlinks.expire(contact.id)}
                          />
                        ) : (
                          <OpenChevron />
                        )}
                      </div>
                    </LinkedRow>
                  )
                );
              })}
            </ul>
          ) : (
            <p>{t.noContacts}</p>
          )}
          {items.length > 0 && unlinkOffered && <LinkedRowTip labels={t} />}
          <WriteNotice
            failure={unlinks.failure}
            labels={manageLabelsFor(t.dateLocale)}
            onReload={() => {
              unlinks.clear();
              onReloadContacts();
            }}
            onRetry={unlinks.retry}
          />
          {more === "busy" && <p role="status">{t.loading}</p>}
          {more === "failed" && <p role="alert">{t.failed}</p>}
          {nextCursor && (
            <button
              type="button"
              disabled={more === "busy"}
              onClick={contacts.loadMore}
            >
              {t.more}
            </button>
          )}
          {linkOffered && (
            <LinkContact
              taskId={taskId}
              transport={transport}
              labels={t}
              linkedIds={items.map((contact) => contact.id)}
              createOffered={createOffered}
              onChanged={onReloadContacts}
            />
          )}
        </>
      )}
    </>
  );
}
