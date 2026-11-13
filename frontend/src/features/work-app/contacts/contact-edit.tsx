import { useEffect, useId, useRef, useState } from "react";
import type { WorkLabels } from "../shared/labels";
import { keepEdits, titleProblem } from "../shared/fields";
import { useUnsavedGuard } from "../../mcp-apps/unsaved-guard";
import { ContactAliases } from "./contact-aliases";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import type {
  WorkContactAlias,
  WorkContactChanges,
  WorkContactRecord,
} from "../transport/transport";

/** Limits of the update_contact schema: email 320, phone 64 and context note 10,000 characters. */
export const EMAIL_MAX_LENGTH = 320;
export const PHONE_MAX_LENGTH = 64;
export const CONTEXT_NOTE_MAX_LENGTH = 10_000;
/** Limits of the profile fields of the update_contact schema (relationship, organization, role, address). */
export const RELATIONSHIP_MAX_LENGTH = 80;
export const ORGANIZATION_MAX_LENGTH = 200;
export const ROLE_MAX_LENGTH = 120;
export const ADDRESS_MAX_LENGTH = 500;

/** Editable Contact fields as the form shows them; empty text means "no value". */
export type ContactDraft = {
  displayName: string;
  email: string;
  phone: string;
  relationship: string;
  organization: string;
  role: string;
  address: string;
  contextNote: string;
};
/**
 * `base` is the Contact as the user last saw it (opening the editor, or the latest reload). A field
 * counts as changed only while it differs from base, so an edit reverted by hand is not sent.
 */
export type ContactDraftState = { values: ContactDraft; base: ContactDraft };
export type ContactFieldProblem =
  | "nameRequired"
  | "nameTooLong"
  | "emailInvalid"
  | "phoneTooLong"
  | "contextNoteTooLong";
type DraftField = keyof ContactDraft;

export function draftFromContact(contact: WorkContactRecord): ContactDraft {
  return {
    displayName: contact.display_name,
    email: contact.email ?? "",
    phone: contact.phone ?? "",
    relationship: contact.relationship ?? "",
    organization: contact.organization ?? "",
    role: contact.role ?? "",
    address: contact.address ?? "",
    contextNote: contact.context_note ?? "",
  };
}

/**
 * The same shape the server accepts: no whitespace or control characters, exactly one "@" with
 * a non-empty local part and domain, and at most 320 characters. The server stays the authority.
 */
export function isPlausibleEmail(value: string): boolean {
  if (Array.from(value).length > EMAIL_MAX_LENGTH) return false;
  if (/[\s\p{Cc}\p{Cf}]/u.test(value)) return false;
  const parts = value.split("@");
  return parts.length === 2 && parts[0] !== "" && parts[1] !== "";
}

/** The first field problem that blocks Save, or none. Empty optional fields are valid. */
export function contactFieldProblem(
  state: ContactDraftState,
): ContactFieldProblem | undefined {
  // The name uses the same 200-character rule as a Task or Project title.
  const name = titleProblem(state.values.displayName);
  if (name === "required") return "nameRequired";
  if (name === "tooLong") return "nameTooLong";
  const email = state.values.email.trim();
  if (email !== "" && !isPlausibleEmail(email)) return "emailInvalid";
  if (Array.from(state.values.phone.trim()).length > PHONE_MAX_LENGTH)
    return "phoneTooLong";
  if (
    Array.from(state.values.contextNote.trim()).length > CONTEXT_NOTE_MAX_LENGTH
  )
    return "contextNoteTooLong";
  return undefined;
}

/**
 * Only the fields that differ from what the user last saw. Text is trimmed the way the form saves
 * it; an empty email, phone or note is sent as null, which clears it.
 */
export function changedContactFields(
  state: ContactDraftState,
): WorkContactChanges {
  const { values, base } = state;
  const changes: WorkContactChanges = {};
  if (values.displayName.trim() !== base.displayName.trim())
    changes.display_name = values.displayName.trim();
  if (values.email.trim() !== base.email.trim())
    changes.email = values.email.trim() || null;
  if (values.phone.trim() !== base.phone.trim())
    changes.phone = values.phone.trim() || null;
  if (values.contextNote.trim() !== base.contextNote.trim())
    changes.context_note = values.contextNote.trim() || null;
  // The profile fields send "" for an empty value; the server stores blank as no value.
  if (values.relationship.trim() !== base.relationship.trim())
    changes.relationship = values.relationship.trim();
  if (values.organization.trim() !== base.organization.trim())
    changes.organization = values.organization.trim();
  if (values.role.trim() !== base.role.trim())
    changes.role = values.role.trim();
  if (values.address.trim() !== base.address.trim())
    changes.address = values.address.trim();
  return changes;
}

export function ContactEditor({
  contact,
  busy,
  saveFailed,
  onSave,
  onCancel,
  onAddAlias,
  onRemoveAlias,
  labels: t,
  focusField,
}: {
  contact: WorkContactRecord;
  busy: boolean;
  saveFailed: boolean;
  onSave: (changes: WorkContactChanges) => void;
  onCancel: () => void;
  /** Nicknames are written at once (add_contact_alias / remove_contact_alias), not with Save; the typed fields stay. */
  onAddAlias: (value: string, done: () => void) => void;
  onRemoveAlias: (alias: WorkContactAlias) => void;
  labels: WorkLabels;
  /** The field that takes the focus when the editor opens (a new Contact's "+ Telefon"); else the name. */
  focusField?: "phone" | "email" | "relationship";
}) {
  const [state, setState] = useState<ContactDraftState>(() => {
    const initial = draftFromContact(contact);
    return { values: initial, base: initial };
  });
  const [seenContact, setSeenContact] = useState(contact);
  const [problem, setProblem] = useState<ContactFieldProblem>();
  useUnsavedGuard(Object.keys(changedContactFields(state)).length > 0);
  const nameInput = useRef<HTMLInputElement>(null);
  const emailInput = useRef<HTMLInputElement>(null);
  const phoneInput = useRef<HTMLInputElement>(null);
  const relationshipInput = useRef<HTMLInputElement>(null);
  const noteInput = useRef<HTMLTextAreaElement>(null);
  const nameId = useId();
  const emailId = useId();
  const phoneId = useId();
  const relationshipId = useId();
  const organizationId = useId();
  const roleId = useId();
  const addressId = useId();
  const noteId = useId();
  const aliasesHeadingId = useId();
  const nameErrorId = useId();
  const emailErrorId = useId();
  const phoneErrorId = useId();
  const noteErrorId = useId();
  // Adjusts state during render when a reload delivers a new Contact (same pattern as ProjectEditor).
  if (contact !== seenContact) {
    setSeenContact(contact);
    const fresh = draftFromContact(contact);
    setState((current) => ({
      values: keepEdits(current, fresh),
      base: fresh,
    }));
  }
  // Read once, on open: the editor focuses the field it was opened for.
  const openedFor = useRef(focusField);
  useEffect(() => {
    const field = openedFor.current;
    (field === "phone"
      ? phoneInput
      : field === "email"
        ? emailInput
        : field === "relationship"
          ? relationshipInput
          : nameInput
    ).current?.focus();
  }, []);
  const nameBad = problem === "nameRequired" || problem === "nameTooLong";
  const emailBad = problem === "emailInvalid";
  const phoneBad = problem === "phoneTooLong";
  const noteBad = problem === "contextNoteTooLong";

  function setField(field: DraftField, value: string) {
    setProblem(undefined);
    setState((current) => ({
      ...current,
      values: { ...current.values, [field]: value },
    }));
  }
  // Save runs from the button's click, not the form's submit event: the App iframe is sandboxed
  // without allow-forms, where the browser never dispatches submit. Enter still clicks the button.
  function submit() {
    if (busy) return;
    const found = contactFieldProblem(state);
    setProblem(found);
    if (found === "nameRequired" || found === "nameTooLong")
      nameInput.current?.focus();
    else if (found === "emailInvalid") emailInput.current?.focus();
    else if (found === "phoneTooLong") phoneInput.current?.focus();
    else if (found === "contextNoteTooLong") noteInput.current?.focus();
    if (found) return;
    onSave(changedContactFields(state));
  }

  return (
    <form className="work-edit" aria-label={t.edit} noValidate>
      <label htmlFor={nameId}>{t.nameLabel}</label>
      <input
        id={nameId}
        ref={nameInput}
        type="text"
        value={state.values.displayName}
        disabled={busy}
        aria-invalid={nameBad ? true : undefined}
        aria-describedby={nameBad ? nameErrorId : undefined}
        onChange={(event) => setField("displayName", event.target.value)}
      />
      {nameBad && (
        <p id={nameErrorId}>
          {problem === "nameRequired" ? t.nameRequired : t.nameTooLong}
        </p>
      )}
      <div role="group" aria-labelledby={aliasesHeadingId}>
        <h3 id={aliasesHeadingId}>{t.aliasesHeading}</h3>
        <ContactAliases
          aliases={contact.aliases}
          busy={busy}
          editable
          onAdd={onAddAlias}
          onRemove={onRemoveAlias}
          labels={t}
        />
      </div>
      <label htmlFor={emailId}>{t.email}</label>
      <input
        id={emailId}
        ref={emailInput}
        type="email"
        value={state.values.email}
        disabled={busy}
        aria-invalid={emailBad ? true : undefined}
        aria-describedby={emailBad ? emailErrorId : undefined}
        onChange={(event) => setField("email", event.target.value)}
      />
      {emailBad && (
        <p id={emailErrorId} role="alert">
          {t.invalidChange}
        </p>
      )}
      <label htmlFor={phoneId}>{t.phone}</label>
      <input
        id={phoneId}
        ref={phoneInput}
        type="tel"
        value={state.values.phone}
        disabled={busy}
        aria-invalid={phoneBad ? true : undefined}
        aria-describedby={phoneBad ? phoneErrorId : undefined}
        onChange={(event) => setField("phone", event.target.value)}
      />
      {phoneBad && <p id={phoneErrorId}>{t.phoneTooLong}</p>}
      <label htmlFor={relationshipId}>{t.relationship}</label>
      <input
        ref={relationshipInput}
        id={relationshipId}
        type="text"
        maxLength={RELATIONSHIP_MAX_LENGTH}
        value={state.values.relationship}
        disabled={busy}
        onChange={(event) => setField("relationship", event.target.value)}
      />
      <label htmlFor={organizationId}>{t.organization}</label>
      <input
        id={organizationId}
        type="text"
        maxLength={ORGANIZATION_MAX_LENGTH}
        value={state.values.organization}
        disabled={busy}
        onChange={(event) => setField("organization", event.target.value)}
      />
      <label htmlFor={roleId}>{t.role}</label>
      <input
        id={roleId}
        type="text"
        maxLength={ROLE_MAX_LENGTH}
        value={state.values.role}
        disabled={busy}
        onChange={(event) => setField("role", event.target.value)}
      />
      <label htmlFor={addressId}>{t.address}</label>
      <textarea
        id={addressId}
        rows={3}
        maxLength={ADDRESS_MAX_LENGTH}
        value={state.values.address}
        disabled={busy}
        onChange={(event) => setField("address", event.target.value)}
      />
      <label htmlFor={noteId}>{t.contextNote}</label>
      <textarea
        id={noteId}
        ref={noteInput}
        rows={4}
        value={state.values.contextNote}
        disabled={busy}
        aria-invalid={noteBad ? true : undefined}
        aria-describedby={noteBad ? noteErrorId : undefined}
        onChange={(event) => setField("contextNote", event.target.value)}
      />
      {noteBad && <p id={noteErrorId}>{t.contextNoteTooLong}</p>}
      {saveFailed && (
        <p role="alert">
          {t.contactSaveFailed}{" "}
          <button type="button" disabled={busy} onClick={() => submit()}>
            {t.retry}
          </button>
        </p>
      )}
      <div className="work-actions work-actions-sticky">
        <button
          type="submit"
          disabled={busy}
          onClick={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          {t.save}
        </button>
        <button type="button" disabled={busy} onClick={onCancel}>
          {t.cancel}
        </button>
      </div>
    </form>
  );
}

/**
 * Archives an active Contact or restores an archived one. The first click asks for a confirmation;
 * the confirm button takes focus, and Cancel returns focus to the action button.
 */
export function ContactArchiveToggle({
  archived,
  busy,
  onConfirm,
  labels: t,
}: {
  archived: boolean;
  busy: boolean;
  onConfirm: () => void;
  labels: WorkLabels;
}) {
  const [confirming, setConfirming] = useState(false);
  const actionButton = useRef<HTMLButtonElement>(null);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    if (confirming) confirmButton.current?.focus();
    else if (restoreFocus.current) {
      restoreFocus.current = false;
      actionButton.current?.focus();
    }
  }, [confirming]);
  const label = archived ? t.restoreContact : t.archiveContact;
  if (!confirming)
    return (
      <div className="work-row-actions">
        <button
          ref={actionButton}
          type="button"
          className="sk-btn--quiet"
          disabled={busy}
          onClick={() => setConfirming(true)}
        >
          {label}
        </button>
      </div>
    );
  return (
    <div className="work-row-actions">
      <button
        ref={confirmButton}
        type="button"
        className="sk-btn--primary"
        disabled={busy}
        onClick={onConfirm}
      >
        {t.confirmChange}
      </button>
      <button
        type="button"
        className="sk-btn--quiet"
        disabled={busy}
        onClick={() => {
          restoreFocus.current = true;
          setConfirming(false);
        }}
      >
        {t.cancel}
      </button>
    </div>
  );
}

/**
 * The panel of a detail view's ⋯ button (the button sits in the Back row, see work-view.tsx ContactFrame and TaskFrame).
 * It opens under the title with "Redigera" first (design system §3, Tillbakarad; nicknames are edited there too),
 * then Archive (Restore for an archived one) in the text colour, since Restore undoes it (only a deletion is drawn in the
 * danger colour); the confirming step opens in the same panel. A Task passes no `archived`, so it has no archive entry. Escape closes it.
 */
export function ContactMenu({
  id,
  archived,
  busy,
  onConfirm,
  edit,
  remove,
  onClose,
  labels: t,
}: {
  id: string;
  archived?: boolean;
  busy: boolean;
  onConfirm?: () => void;
  /** "Redigera", first in the menu; left out for an archived (read-only) Contact. */
  edit?: { label: string; onChoose: () => void };
  /** A Task's "Ta bort uppgift" in the danger colour; no question first, because the trash and Ångra undo it. */
  remove?: { label: string; onChoose: () => void };
  onClose: () => void;
  labels: WorkLabels;
}) {
  return (
    <KeyScope id={id} className="work-contact-menu" onEscape={onClose}>
      {edit && (
        <button
          type="button"
          className="work-contact-menu-item"
          disabled={busy}
          onClick={edit.onChoose}
        >
          {edit.label}
        </button>
      )}
      {remove && (
        <button
          type="button"
          className="work-contact-menu-item"
          data-danger
          disabled={busy}
          onClick={remove.onChoose}
        >
          {remove.label}
        </button>
      )}
      {onConfirm && (
        <ContactArchiveToggle
          archived={archived === true}
          busy={busy}
          onConfirm={onConfirm}
          labels={t}
        />
      )}
    </KeyScope>
  );
}
