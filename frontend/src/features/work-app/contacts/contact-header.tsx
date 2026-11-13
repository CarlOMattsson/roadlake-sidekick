import { useId, useRef, useState } from "react";
import { ContactAliasSummary } from "./contact-aliases";
import { ContactMenu } from "./contact-edit";
import type { WorkLabels } from "../shared/labels";
import { MoreIcon } from "../tasks/task-detail-controls";
import { ContactProfileLine } from "./contact-journal-entries";
import { DetailBar } from "../view/parts/detail-bar";
import { DetailTitle } from "../view/parts/detail-title";
import type { BackTarget } from "../view/parts/frame-types";
import type { DetailFrame } from "../view/parts/use-detail-frame";
import type { ContactRecord } from "./use-contact-record";

/**
 * The top of the Contact frame: the Back row with its ⋯, the name (a tap edits too), the profile line, the
 * nicknames, and the ⋯ panel (Edit, Archive). The panel is open or closed here; every action goes back to the
 * frame through `onEdit` and the record. Nicknames are added and removed in the editor.
 */
export function ContactHeader({
  frame,
  record,
  labels: t,
  back,
  onEdit,
}: {
  frame: DetailFrame;
  record: ContactRecord;
  labels: WorkLabels;
  back?: BackTarget;
  /** Opens the editor. */
  onEdit: () => void;
}) {
  const { phase, write, editing, heading } = frame;
  const { contact, unlinks } = record;
  // The ⋯ panel under the title.
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();
  const moreButton = useRef<HTMLButtonElement>(null);
  const ready = phase === "ready" ? contact : undefined;
  const busy = write.kind === "busy";
  function edit() {
    setMenuOpen(false);
    onEdit();
  }
  // Archive (Restore for an archived Contact) writes at once; the page shows the receipt with Undo.
  function archive() {
    if (!ready) return;
    setMenuOpen(false);
    record.setArchived(!ready.archived);
  }
  function closeMenu() {
    setMenuOpen(false);
    moreButton.current?.focus();
  }
  return (
    <>
      {/* The Back row carries only ⋯ (Redigera, Archive); a tap on the name edits too (§3). */}
      <DetailBar
        back={back}
        kicker={phase !== "gone" ? t.contact : undefined}
        actions={
          ready ? (
            <button
              ref={moreButton}
              type="button"
              className="sk-iconbtn work-detail-action"
              aria-label={t.moreActions}
              aria-expanded={menuOpen}
              aria-controls={menuOpen ? menuId : undefined}
              disabled={busy || editing}
              onClick={() => setMenuOpen(!menuOpen)}
            >
              <MoreIcon />
            </button>
          ) : undefined
        }
      />
      <DetailTitle
        heading={heading}
        onEdit={
          ready && !ready.archived && !editing && !busy ? edit : undefined
        }
      >
        {ready ? ready.display_name : t.contact}
      </DetailTitle>
      {/* The profile line of the list row, 4 under the name as the Task's meta line; the nicknames under it.
          While the editor is open it is the page's content: the values it edits are not drawn twice above it. */}
      {ready && !editing && <ContactProfileLine contact={ready} />}
      {ready && !editing && (
        <ContactAliasSummary aliases={ready.aliases} labels={t} />
      )}
      {ready && menuOpen && (
        <ContactMenu
          id={menuId}
          busy={busy || editing || unlinks.busy}
          edit={ready.archived ? undefined : { label: t.edit, onChoose: edit }}
          archive={{
            label: ready.archived ? t.restoreContact : t.archiveContact,
            onChoose: archive,
          }}
          onClose={closeMenu}
        />
      )}
    </>
  );
}
