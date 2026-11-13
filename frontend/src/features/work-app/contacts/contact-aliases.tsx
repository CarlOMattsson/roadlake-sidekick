import { useEffect, useId, useRef, useState } from "react";
import type { WorkLabels } from "../shared/labels";
import { titleProblem, type TitleProblem } from "../shared/fields";
import type { WorkContactAlias } from "../transport/transport";

/**
 * Aliases of one Contact, the list inside the Contact editor. An archived Contact is read-only, so `editable` hides the add and remove
 * controls and the aliases stay visible as text.
 */
export function ContactAliases({
  aliases,
  busy,
  editable,
  onAdd,
  onRemove,
  labels: t,
}: {
  aliases: WorkContactAlias[];
  busy: boolean;
  editable: boolean;
  /** Adds the alias; `done` runs once the server has stored it. */
  onAdd: (value: string, done: () => void) => void;
  onRemove: (alias: WorkContactAlias) => void;
  labels: WorkLabels;
}) {
  return (
    <>
      {aliases.length ? (
        <ul className="work-list">
          {aliases.map((alias) => (
            <AliasRow
              key={alias.id}
              alias={alias}
              busy={busy}
              editable={editable}
              onRemove={onRemove}
              labels={t}
            />
          ))}
        </ul>
      ) : (
        <p>{t.noAliases}</p>
      )}
      {editable && <AliasAdd busy={busy} onAdd={onAdd} labels={t} />}
    </>
  );
}

/**
 * The nicknames (aliases) of one Contact under the name: one muted meta line,
 * "Även kallad X, Y" ("Nicknames: X, Y" in English); without nicknames nothing is drawn. Adding and removing nicknames happens in the
 * Contact's editor (`ContactAliases`), not here.
 */
export function ContactAliasSummary({
  aliases,
  labels: t,
}: {
  aliases: WorkContactAlias[];
  labels: WorkLabels;
}) {
  if (aliases.length === 0) return null;
  return (
    <p className="work-alias-line">
      {t.aliasLabel(aliases.length)}{" "}
      <span className="work-alias-values">
        {aliases.map((alias) => alias.value).join(", ")}
      </span>
    </p>
  );
}

/**
 * One alias as text. Removing it asks for a confirmation first; the confirm button takes focus and
 * Cancel returns focus to the remove button.
 */
function AliasRow({
  alias,
  busy,
  editable,
  onRemove,
  labels: t,
}: {
  alias: WorkContactAlias;
  busy: boolean;
  editable: boolean;
  onRemove: (alias: WorkContactAlias) => void;
  labels: WorkLabels;
}) {
  const [confirming, setConfirming] = useState(false);
  const removeButton = useRef<HTMLButtonElement>(null);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    if (confirming) confirmButton.current?.focus();
    else if (restoreFocus.current) {
      restoreFocus.current = false;
      removeButton.current?.focus();
    }
  }, [confirming]);
  return (
    <li>
      <span>{alias.value}</span>
      {editable && (
        <div className="work-row-actions">
          {confirming ? (
            <>
              <button
                ref={confirmButton}
                type="button"
                className="sk-btn--danger"
                disabled={busy}
                onClick={() => onRemove(alias)}
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
            </>
          ) : (
            <button
              ref={removeButton}
              type="button"
              className="sk-btn--quiet"
              disabled={busy}
              aria-label={t.removeAliasFor(alias.value)}
              onClick={() => setConfirming(true)}
            >
              {t.removeAlias}
            </button>
          )}
        </div>
      )}
    </li>
  );
}

/** Adds one alias. The text is kept until the server has stored it, so a failed add can be retried. */
function AliasAdd({
  busy,
  onAdd,
  labels: t,
}: {
  busy: boolean;
  onAdd: (value: string, done: () => void) => void;
  labels: WorkLabels;
}) {
  const [value, setValue] = useState("");
  const [problem, setProblem] = useState<TitleProblem>();
  const input = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const errorId = useId();
  const bad = problem !== undefined;
  function submit() {
    if (busy) return;
    // The alias has the same 200-character rule as a name; the server normalizes the rest.
    const found = titleProblem(value);
    setProblem(found);
    if (found) {
      input.current?.focus();
      return;
    }
    onAdd(value.trim(), () => setValue(""));
  }
  return (
    <div className="work-edit">
      <label htmlFor={inputId}>{t.aliasValue}</label>
      <input
        id={inputId}
        ref={input}
        type="text"
        value={value}
        disabled={busy}
        aria-invalid={bad ? true : undefined}
        aria-describedby={bad ? errorId : undefined}
        onChange={(event) => {
          setProblem(undefined);
          setValue(event.target.value);
        }}
        onKeyDown={(event) => {
          // Inside the Contact editor's form, Enter would press Save; here it adds the nickname.
          if (event.key !== "Enter") return;
          event.preventDefault();
          submit();
        }}
      />
      {problem && (
        <p id={errorId}>
          {problem === "required" ? t.aliasRequired : t.aliasTooLong}
        </p>
      )}
      <button type="button" disabled={busy} onClick={submit}>
        {t.addAlias}
      </button>
    </div>
  );
}
