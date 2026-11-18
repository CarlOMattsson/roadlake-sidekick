import { useEffect, useId, useRef, useState } from "react";
import type { WorkLabels } from "../shared/labels";
import { waitingLabelsFor } from "../shared/waiting";
import type { WorkContact, WorkTransport } from "../transport/transport";
import {
  ContactHit,
  ContactSearchSheet,
  useContactSearch,
} from "./contact-search";
import "./task-waiting.css";

/** The waiting fields of the editor as the draft holds them: owner-zone `YYYY-MM-DD` days and a Contact id, "" for none. */
export type WaitingDraft = {
  waitingSince: string;
  followUp: string;
  waitingContact: string;
};

/** The search sheet of the Contact field; mounted only while open, so the editor reads no Contacts until asked. */
function ContactPicker({
  transport,
  labels: t,
  onPick,
  onClose,
}: {
  transport: WorkTransport;
  labels: WorkLabels;
  onPick: (contact: WorkContact) => void;
  onClose: () => void;
}) {
  const search = useContactSearch(transport);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    input.current?.focus();
  }, []);
  return (
    <ContactSearchSheet
      title={waitingLabelsFor(t.dateLocale).pickWho}
      labels={t}
      search={search}
      busy={false}
      inputRef={input}
      onClose={onClose}
      renderHit={(contact) => (
        <ContactHit
          contact={contact}
          disabled={false}
          busy={false}
          onPick={() => onPick(contact)}
        />
      )}
    />
  );
}

/**
 * The editor's waiting fields: the Contact the Task waits on, since when, and the day to follow up. A Contact or a
 * follow-up day only exists while the Task waits, so choosing either starts the wait (the caller sets today) and
 * "no longer waiting" empties all three. Without a `transport` the Contact is shown, not changed.
 */
export function EditWaiting({
  values,
  contactName,
  transport,
  disabled,
  invalid,
  labels: t,
  onSince,
  onFollowUp,
  onContact,
  onStop,
}: {
  values: WaitingDraft;
  /** The name of the Contact in `values.waitingContact`. */
  contactName: string | null;
  transport: WorkTransport | undefined;
  disabled: boolean;
  /** A date field holds a partial entry; the message stands under the fields. */
  invalid: boolean;
  labels: WorkLabels;
  onSince: (day: string, incomplete: boolean) => void;
  onFollowUp: (day: string, incomplete: boolean) => void;
  /** A chosen Contact, or null when the Contact is taken off. */
  onContact: (contact: WorkContact | null) => void;
  /** The Task is not waiting any more. */
  onStop: () => void;
}) {
  const wt = waitingLabelsFor(t.dateLocale);
  const [picking, setPicking] = useState(false);
  const whoId = useId();
  const sinceId = useId();
  const followId = useId();
  const errorId = useId();
  const waiting = values.waitingSince !== "";
  return (
    <>
      <p id={whoId}>{wt.editWho}</p>
      <div
        className="work-edit-waiting-who"
        role="group"
        aria-labelledby={whoId}
      >
        <span>
          {values.waitingContact ? (contactName ?? wt.someone) : wt.editWhoNone}
        </span>
        {transport && (
          <button
            type="button"
            disabled={disabled}
            aria-expanded={picking}
            onClick={() => setPicking(!picking)}
          >
            {wt.changeWho}
          </button>
        )}
        {values.waitingContact && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onContact(null)}
          >
            {wt.clearWho}
          </button>
        )}
      </div>
      {picking && transport && (
        <ContactPicker
          transport={transport}
          labels={t}
          onClose={() => setPicking(false)}
          onPick={(contact) => {
            setPicking(false);
            onContact(contact);
          }}
        />
      )}
      <label htmlFor={sinceId}>{wt.editSince}</label>
      <div className="work-due-row">
        <input
          id={sinceId}
          type="date"
          value={values.waitingSince}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? errorId : undefined}
          onChange={(event) =>
            onSince(event.target.value, event.target.validity.badInput)
          }
        />
        {waiting && (
          <button type="button" disabled={disabled} onClick={onStop}>
            {wt.clearSince}
          </button>
        )}
      </div>
      <label htmlFor={followId}>{wt.editFollowUp}</label>
      <div className="work-due-row">
        <input
          id={followId}
          type="date"
          value={values.followUp}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? errorId : undefined}
          onChange={(event) =>
            onFollowUp(event.target.value, event.target.validity.badInput)
          }
        />
        {values.followUp && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onFollowUp("", false)}
          >
            {wt.clearFollowUp}
          </button>
        )}
      </div>
      {invalid && <p id={errorId}>{t.dueIncomplete}</p>}
    </>
  );
}
