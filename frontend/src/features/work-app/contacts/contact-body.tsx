import { useContext, useState } from "react";
import { ContactWays } from "./contact-card";
import { contactsRoomLabelsFor } from "./contacts-room-labels";
import { PlusIcon } from "../../mcp-apps/ui/icons";
import { RoomMessageContext } from "../../mcp-apps/ui/room-context";
import { EmptyState } from "../../mcp-apps/ui/states";
import { ContactEditor } from "./contact-edit";
import { ContactProjects } from "./contact-projects";
import { hierarchyDetailLabelsFor } from "../hierarchy/hierarchy-detail-labels";
import { WriteNotice } from "../shared/manage-controls";
import { manageLabelsFor } from "../shared/manage-labels";
import type { WorkContactRecord } from "../transport/transport";
import { ContactJournalEntries } from "./contact-journal-entries";
import type { FrameProps } from "../view/parts/frame-types";
import { TaskSummaryList } from "../tasks/task-summary-list";
import type { ContactRecord } from "./use-contact-record";
import type { DetailFrame } from "../view/parts/use-detail-frame";
import { WriteStatus } from "../view/parts/write-status";
import { TagField } from "../../mcp-apps/ui/tags";
import { useTagVocabulary } from "../../mcp-apps/ui/tag-vocabulary";
import { useToolSupport } from "../../mcp-apps/tool-support";

/** What the Contact frame shows once the Contact is read: its state, details, editor, Tasks, entries and Projects. */
export function ContactBody({
  contact,
  frame,
  record,
  labels: t,
  transport,
  onOpen,
  onOpenJournalEntry,
  onOpenLink,
}: Pick<FrameProps, "labels" | "transport" | "onOpen"> & {
  contact: WorkContactRecord;
  frame: DetailFrame;
  record: ContactRecord;
  onOpenJournalEntry?: (entry: { id: string; title: string }) => void;
  onOpenLink?: (url: string) => void;
}) {
  const { write, editing, banner } = frame;
  const { tasks, journal, nextCursor, more, unlinks } = record;
  const dl = hierarchyDetailLabelsFor(t.dateLocale);
  const about = (name: string) =>
    dl.aboutContact(name.split(/\s+/u)[0] ?? name);
  const sendMessage = useContext(RoomMessageContext);
  const offers = useToolSupport(transport);
  const vocabulary = useTagVocabulary(
    offers("list_tags") ? transport.listTags : undefined,
    "contact",
  );
  // The field the editor opens on when one of a new Contact's first steps opened it.
  const [focusField, setFocusField] = useState<
    "phone" | "email" | "relationship"
  >();
  // A Contact with only its name (a new one, most often): its first steps stand where its details would,
  // so the page is never a lone heading.
  const bare =
    !contact.archived &&
    !editing &&
    ![
      contact.email,
      contact.phone,
      contact.address,
      contact.relationship,
      contact.role,
      contact.organization,
      contact.context_note,
    ].some((value) => value?.trim()) &&
    !contact.tags?.length &&
    tasks.length === 0 &&
    !nextCursor &&
    !(journal && journal.items.length > 0) &&
    record.projects.length === 0;
  const words = contactsRoomLabelsFor(t.dateLocale);
  const first = contact.display_name.split(/\s+/u)[0] ?? contact.display_name;
  const steps = [
    ["phone", words.addPhone, words.addPhoneLabel],
    ["email", words.addEmail, words.addEmailLabel],
    ["relationship", words.addRelationship, words.addRelationshipLabel],
  ] as const;
  return (
    <>
      {contact.archived && <p>{t.archivedLabel}</p>}
      {contact.archived && <p>{t.archivedReadOnly}</p>}
      <WriteStatus
        write={write}
        conflict={t.contactEditConflict}
        onReload={record.reloadContact}
        banner={banner}
        labels={t}
      />
      {write.kind === "failed" && write.action === "write" && (
        <p role="alert">
          {t.contactSaveFailed}{" "}
          <button type="button" onClick={record.retryLastWrite}>
            {t.retry}
          </button>
        </p>
      )}
      {/* "Kontaktvägar ⌄" right after the name and alias: a fold row of 48, the
          view's first content, with e-mail, phone and address closed in it. */}
      <ContactWays contact={contact} onOpenLink={onOpenLink} labels={dl} />
      {/* The tags under the ways to reach her: the pills and one quiet button that edits them in place. */}
      <TagField
        tags={contact.tags ?? []}
        suggestions={vocabulary.suggestions}
        editable={!contact.archived && offers("update_contact")}
        busy={write.kind === "busy"}
        name={contact.display_name}
        onChange={(tags, done) =>
          record.setTags(tags, () => {
            vocabulary.refresh();
            done();
          })
        }
        locale={t.dateLocale}
      />
      {/* No "Etikett:" rows (design system §3, Kontaktvyn): the note is a paragraph under "Om Anna". */}
      {contact.context_note && (
        <>
          <h3>{about(contact.display_name)}</h3>
          <p className="work-description work-contact-about">
            {contact.context_note}
          </p>
        </>
      )}
      {bare && (
        <div className="work-contact-first">
          <EmptyState
            title={words.bareTitle(first)}
            ask={{
              locale: t.dateLocale,
              example: words.bareAsk(contact.display_name),
              onSend: sendMessage
                ? () => void sendMessage(words.bareAsk(contact.display_name))
                : undefined,
            }}
          >
            {steps.map(([field, text, label]) => (
              <button
                key={field}
                type="button"
                className="sk-btn--secondary sk-btn--compact work-contact-step"
                aria-label={label}
                onClick={() => {
                  setFocusField(field);
                  frame.setWrite({ kind: "idle" });
                  frame.setEditing(true);
                }}
              >
                <PlusIcon />
                {text}
              </button>
            ))}
          </EmptyState>
        </div>
      )}
      {!contact.archived && editing && (
        <ContactEditor
          focusField={focusField}
          contact={contact}
          busy={write.kind === "busy"}
          saveFailed={write.kind === "failed" && write.action === "save"}
          onSave={record.saveContact}
          onCancel={frame.stopEdit}
          onAddAlias={record.addAlias}
          onRemoveAlias={record.removeAlias}
          labels={t}
        />
      )}
      {/* No Task can be linked from here, so an empty Tasks section is left out (design system §3, Tomt). */}
      {tasks.length > 0 && (
        <>
          <h3>{t.tasks}</h3>
          <TaskSummaryList
            tasks={tasks}
            labels={t}
            empty={t.noTasks}
            onOpen={onOpen}
            transport={transport}
            onReload={record.reloadContact}
          />
        </>
      )}
      {more === "busy" && <p role="status">{t.loading}</p>}
      {more === "failed" && <p role="alert">{t.failed}</p>}
      {nextCursor && (
        <button
          type="button"
          disabled={more === "busy"}
          onClick={record.loadMore}
        >
          {t.more}
        </button>
      )}
      {onOpenJournalEntry && journal && (
        <ContactJournalEntries
          journal={journal}
          labels={t}
          onOpen={onOpenJournalEntry}
        />
      )}
      <ContactProjects
        projects={record.projects.filter(
          (project) => unlinks.state[project.id] !== "hidden",
        )}
        gone={unlinks.state}
        busy={unlinks.busy}
        onRemove={(projectId) => unlinks.set(projectId, false)}
        onUndo={(projectId) => unlinks.set(projectId, true)}
        onExpire={unlinks.expire}
        onOpen={(projectId) => onOpen({ kind: "project", id: projectId })}
        labels={t}
      />
      <WriteNotice
        failure={unlinks.failure}
        labels={manageLabelsFor(t.dateLocale)}
        onReload={() => {
          unlinks.clear();
          record.reloadContact();
        }}
        onRetry={unlinks.retry}
      />
    </>
  );
}
