import { workDate } from "../../mcp-apps/ui/due";
import { contactMeta } from "./contacts-sections";
import type { WorkLabels } from "../shared/labels";
import { OpenChevron } from "../tasks/task-detail-controls";
import type {
  WorkContactRecord,
  WorkJournalEntries,
} from "../transport/transport";

/**
 * The Contact's profile line under the name (§3, Kontaktvyn): the list row's meta, "Leverantör · Säljare ·
 * Flyttfirman Väst AB", built by the same function, on one muted line cut at the end. No fields, no line.
 */
export function ContactProfileLine({
  contact,
}: {
  contact: WorkContactRecord;
}) {
  const line = contactMeta(contact);
  return line ? <p className="work-contact-profile">{line}</p> : null;
}

/**
 * The Contact's newest linked Journal entries, under the Tasks, as note rows (design system §3, Anteckningsrad):
 * no leading icon (the heading says what they are, and the title starts on the content edge), the
 * title first as the button that opens the entry in the journal room, the date
 * under it as the muted meta line ("tis 3 nov"), and the shared chevron (›) at the right. An empty readable list shows nothing. When the
 * session may not read the journal, a calm line says so, with no button and no retry.
 */
export function ContactJournalEntries({
  journal,
  labels: t,
  onOpen,
}: {
  journal: WorkJournalEntries;
  labels: WorkLabels;
  onOpen: (entry: { id: string; title: string }) => void;
}) {
  if (journal.readable && journal.items.length === 0) return null;
  return (
    <>
      <h3>{t.journalEntries}</h3>
      {journal.readable ? (
        <ul className="work-list">
          {journal.items.slice(0, 10).map((entry) => (
            <li key={entry.id} className="work-agenda-row work-open-row">
              <div className="work-agenda-line">
                <div className="work-agenda-body">
                  <button
                    type="button"
                    onClick={() => onOpen({ id: entry.id, title: entry.title })}
                  >
                    {entry.title}
                  </button>
                  <p className="work-card-meta">
                    <time dateTime={entry.journal_date}>
                      {workDate(entry.journal_date, new Date(), t.dateLocale, {
                        inline: true,
                        relative: false,
                      }) || entry.journal_date}
                    </time>
                  </p>
                </div>
                <OpenChevron />
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p>{t.journalUnavailable}</p>
      )}
    </>
  );
}
