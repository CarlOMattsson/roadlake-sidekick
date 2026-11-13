import { useEffect, useId, useRef, useState } from "react";
import { CloseIcon, PlusIcon } from "./icons";
import { KeyScope } from "./key-scope";
import { tagLabelsFor } from "./tag-labels";
import {
  TAG_MAX_LENGTH,
  TAGS_PER_FILTER,
  TAGS_PER_RECORD,
  tagLabelOf,
  tagSlugOf,
  type TagOption,
} from "./tag-vocabulary";
import "./tags.css";

/** How many suggestion chips the open field shows under the input. */
const SUGGESTIONS_SHOWN = 6;

/**
 * A record's tags as small pills, for a row, a card or a room. The pills are drawn only; the tags are read
 * once as one sentence ("Taggar: viktig, familj och 2 till"), so the pills can sit inside a row's open button.
 * `max` shows that many and "+N" for the rest (an inline card keeps its height). No tags: nothing.
 */
export function TagChips({
  tags,
  known = [],
  max,
  locale,
}: {
  tags: readonly string[];
  /** The vocabulary, for the labels; without it each tag reads as its slug. */
  known?: readonly TagOption[];
  max?: number;
  locale: string;
}) {
  if (tags.length === 0) return null;
  const t = tagLabelsFor(locale);
  const labels = tags.map((slug) => tagLabelOf(slug, known));
  const shown = max === undefined ? labels : labels.slice(0, max);
  const rest = labels.length - shown.length;
  const spoken = new Intl.ListFormat(
    locale.startsWith("en") ? "en-GB" : "sv-SE",
    {
      type: "conjunction",
    },
  ).format(rest > 0 ? [...shown, t.more(rest)] : shown);
  return (
    <span className="sk-tags">
      <span className="sk-tags-sr">{`${t.tags}: ${spoken}`}</span>
      {shown.map((label, index) => (
        <span key={tags[index]} className="sk-tag" aria-hidden="true">
          {label}
        </span>
      ))}
      {rest > 0 && (
        <span className="sk-tag sk-tag--more" aria-hidden="true">
          +{rest}
        </span>
      )}
    </span>
  );
}

/**
 * A record's tags where they can be changed: the pills and one button ("Lägg till tagg" / "Ändra taggar").
 * The button opens the editor in place: each pill gets its own remove button, a field adds a typed tag (Enter
 * or "Lägg till"), and the owner's other tags stand under it as chips to add with one tap. Every change is the
 * whole new set through `onChange`, which the room writes as one update; `done` runs once it is stored, and
 * the typed text stays until then so a failed write can be retried. `editable` false shows the pills only.
 */
export function TagField({
  tags,
  suggestions = [],
  editable,
  busy,
  name,
  onChange,
  locale,
}: {
  tags: readonly string[];
  suggestions?: readonly TagOption[];
  editable: boolean;
  busy: boolean;
  /** The record's name, for the button's accessible name ("Ändra taggar för Anna"). */
  name: string;
  onChange: (next: string[], done: () => void) => void;
  locale: string;
}) {
  const t = tagLabelsFor(locale);
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const closing = useRef(false);
  useEffect(() => {
    if (!open && closing.current) {
      closing.current = false;
      opener.current?.focus();
    }
  }, [open]);
  if (!editable)
    return tags.length > 0 ? (
      <div className="sk-tag-field">
        <TagChips tags={tags} known={suggestions} locale={locale} />
      </div>
    ) : null;
  if (!open)
    return (
      <div className="sk-tag-field">
        <TagChips tags={tags} known={suggestions} locale={locale} />
        <button
          ref={opener}
          type="button"
          className="sk-tag-field__open"
          aria-label={tags.length > 0 ? t.editFor(name) : undefined}
          onClick={() => setOpen(true)}
        >
          {tags.length === 0 && <PlusIcon />}
          {tags.length > 0 ? t.edit : t.add}
        </button>
      </div>
    );
  return (
    <TagEditor
      tags={tags}
      suggestions={suggestions}
      busy={busy}
      onChange={onChange}
      onClose={() => {
        closing.current = true;
        setOpen(false);
      }}
      locale={locale}
    />
  );
}

function TagEditor({
  tags,
  suggestions,
  busy,
  onChange,
  onClose,
  locale,
}: {
  tags: readonly string[];
  suggestions: readonly TagOption[];
  busy: boolean;
  onChange: (next: string[], done: () => void) => void;
  onClose: () => void;
  locale: string;
}) {
  const t = tagLabelsFor(locale);
  const [value, setValue] = useState("");
  const [problem, setProblem] = useState<string>();
  const input = useRef<HTMLInputElement>(null);
  const doneButton = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  // After a removal the focus goes to the pill that took its place, or to the field when none is left.
  const focusAfter = useRef<number | undefined>(undefined);
  const inputId = useId();
  const errorId = useId();
  const full = tags.length >= TAGS_PER_RECORD;
  useEffect(() => {
    input.current?.focus();
  }, []);
  useEffect(() => {
    const index = focusAfter.current;
    if (index === undefined) return;
    focusAfter.current = undefined;
    const buttons = list.current?.querySelectorAll("button");
    const next = buttons?.[Math.min(index, buttons.length - 1)];
    if (next) next.focus();
    else input.current?.focus();
  }, [tags]);

  function add(text: string) {
    if (busy) return;
    const slug = tagSlugOf(text);
    if (!slug) return;
    if ([...slug].length > TAG_MAX_LENGTH) {
      setProblem(t.tooLong(TAG_MAX_LENGTH));
      input.current?.focus();
      return;
    }
    if (tags.includes(slug)) {
      setValue("");
      return;
    }
    if (full) {
      setProblem(t.full(TAGS_PER_RECORD));
      return;
    }
    onChange([...tags, slug], () => setValue(""));
  }
  function remove(index: number) {
    if (busy) return;
    focusAfter.current = index;
    setProblem(undefined);
    onChange(
      tags.filter((_, at) => at !== index),
      () => undefined,
    );
  }
  const typed = tagSlugOf(value);
  const offered = suggestions
    .filter((tag) => !tags.includes(tag.slug))
    .filter((tag) => !typed || tag.slug.includes(typed))
    .slice(0, SUGGESTIONS_SHOWN);
  const suggestedId = `${inputId}-suggested`;
  return (
    <KeyScope
      className="sk-tag-editor"
      role="group"
      aria-label={t.tags}
      onEscape={onClose}
    >
      {tags.length > 0 && (
        <ul ref={list} className="sk-tag-editor__list" aria-label={t.tags}>
          {tags.map((slug, index) => {
            const label = tagLabelOf(slug, suggestions);
            return (
              <li key={slug}>
                <button
                  type="button"
                  className="sk-tag-editor__remove"
                  aria-label={t.remove(label)}
                  disabled={busy}
                  onClick={() => remove(index)}
                >
                  <span className="sk-tag sk-tag--removable">
                    {label}
                    <CloseIcon />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="sk-tag-editor__add">
        <label htmlFor={inputId} className="sk-tags-sr">
          {t.input}
        </label>
        <input
          id={inputId}
          ref={input}
          type="text"
          className="sk-tag-editor__input"
          value={value}
          placeholder={t.placeholder}
          autoComplete="off"
          enterKeyHint="done"
          disabled={full}
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? errorId : undefined}
          onChange={(event) => {
            setProblem(undefined);
            setValue(event.target.value);
          }}
          onKeyDown={(event) => {
            // Inside a form Enter would press its Save; here it adds the tag.
            if (event.key !== "Enter") return;
            event.preventDefault();
            add(value);
          }}
        />
        <button
          type="button"
          className="sk-btn--secondary"
          disabled={busy || full || !typed}
          onClick={() => add(value)}
        >
          {t.addButton}
        </button>
        <button
          ref={doneButton}
          type="button"
          className="sk-btn--quiet"
          onClick={onClose}
        >
          {t.done}
        </button>
      </div>
      {(problem || full) && (
        <p id={errorId} className="sk-tag-editor__problem" role="alert">
          {full ? t.full(TAGS_PER_RECORD) : problem}
        </p>
      )}
      {!full && offered.length > 0 && (
        <>
          <p id={suggestedId} className="sk-tag-editor__suggested">
            {t.suggested}
          </p>
          <ul className="sk-tag-editor__list" aria-labelledby={suggestedId}>
            {offered.map((tag) => (
              <li key={tag.slug}>
                <button
                  type="button"
                  className="sk-tag-editor__remove"
                  aria-label={t.suggest(tag.label)}
                  disabled={busy}
                  onClick={() => {
                    add(tag.slug);
                    // The chip leaves the suggestions once added: the focus goes back to the field (or to
                    // "Klar" when the record is full), never to the page.
                    if (tags.length + 1 >= TAGS_PER_RECORD)
                      doneButton.current?.focus();
                    else input.current?.focus();
                  }}
                >
                  <span className="sk-tag sk-tag--suggested">
                    <PlusIcon />
                    {tag.label}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </KeyScope>
  );
}

/**
 * The tag filter of a list: one row of toggle chips (aria-pressed), the tags in use on that kind, most used
 * first, and "Rensa" once one is chosen. Choosing more tags narrows the list (the read asks for every tag,
 * tag_match "all"). At most five at once, as the server takes. Nothing is drawn while there is no tag to offer.
 */
export function TagFilter({
  options,
  selected,
  onChange,
  locale,
}: {
  options: readonly TagOption[];
  selected: readonly string[];
  onChange: (next: string[]) => void;
  locale: string;
}) {
  const t = tagLabelsFor(locale);
  // A chosen tag the vocabulary no longer lists still shows, so it can be cleared.
  const shown = [
    ...options,
    ...selected
      .filter((slug) => !options.some((tag) => tag.slug === slug))
      .map((slug) => ({ slug, label: slug, count: 0 })),
  ];
  if (shown.length === 0) return null;
  const full = selected.length >= TAGS_PER_FILTER;
  return (
    <div className="sk-tag-filter" role="group" aria-label={t.filter}>
      {/* The chips scroll sideways; "Rensa" stands outside the scroller, so it is never scrolled away. */}
      <div className="sk-tag-filter__scroll">
        {shown.map((tag) => {
          const on = selected.includes(tag.slug);
          return (
            <button
              key={tag.slug}
              type="button"
              className="sk-tag-filter__option"
              aria-pressed={on}
              disabled={!on && full}
              title={!on && full ? t.filterFull(TAGS_PER_FILTER) : undefined}
              onClick={() =>
                onChange(
                  on
                    ? selected.filter((slug) => slug !== tag.slug)
                    : [...selected, tag.slug],
                )
              }
            >
              <span className="sk-tag">{tag.label}</span>
            </button>
          );
        })}
      </div>
      {selected.length > 0 && (
        <button
          type="button"
          className="sk-tag-filter__clear"
          aria-label={t.clearLabel}
          onClick={() => onChange([])}
        >
          {t.clear}
        </button>
      )}
    </div>
  );
}
