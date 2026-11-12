import { ErrorNotice } from "../../mcp-apps/ui/states";
import { ContactBody } from "./contact-body";
import { ContactHeader } from "./contact-header";
import type { FrameProps } from "../view/parts/frame-types";
import { useContactRecord } from "./use-contact-record";
import { useDetailFrame } from "../view/parts/use-detail-frame";

export function ContactFrame({
  id,
  transport,
  labels: t,
  moves,
  onOpen,
  contactsOpen,
  refreshKey = 0,
  startEditing = false,
  onOpenJournalEntry,
  onOpenLink,
  back,
}: FrameProps & {
  id: string;
  startEditing?: boolean;
  onOpenJournalEntry?: (entry: { id: string; title: string }) => void;
  onOpenLink?: (url: string) => void;
}) {
  // A compact Contact card's "Edit" opens the frame with the existing editor already open.
  const frame = useDetailFrame({ moves, startEditing });
  const record = useContactRecord({ id, transport, frame, refreshKey });
  const { phase } = frame;
  const { contact } = record;
  function startEdit() {
    frame.setWrite({ kind: "idle" });
    frame.setEditing(true);
  }
  return (
    <article className="work-contact">
      <ContactHeader
        frame={frame}
        record={record}
        labels={t}
        back={back}
        onEdit={startEdit}
      />
      {!contactsOpen && (
        <p>
          <button
            type="button"
            className="work-nav"
            onClick={() =>
              onOpen({ kind: "contacts", q: "", includeArchived: false })
            }
          >
            {t.allContacts}
          </button>
        </p>
      )}
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "error" && (
        <section className="sk-card">
          <p className="sk-eyebrow">{t.title}</p>
          <ErrorNotice
            locale={t.dateLocale}
            cause={frame.readError}
            onRetry={record.retry}
          />
        </section>
      )}
      {phase === "gone" && <p role="status">{t.goneContact}</p>}
      {phase === "ready" && contact && (
        <ContactBody
          contact={contact}
          frame={frame}
          record={record}
          labels={t}
          transport={transport}
          onOpen={onOpen}
          onOpenJournalEntry={onOpenJournalEntry}
          onOpenLink={onOpenLink}
        />
      )}
    </article>
  );
}
