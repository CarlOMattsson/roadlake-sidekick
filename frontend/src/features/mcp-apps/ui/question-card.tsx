import {
  useId,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
} from "react";

import { buttonClass } from "./button";
import { KeyScope } from "./key-scope";
import { reviewLabelsFor } from "./review-labels";
import "./tokens.css";
import "./family.css";
import "./question-card.css";

/**
 * One multiple-choice question (designsystem §3 Repetition, the library's questions). The prompt as a heading, the
 * options as 48 high rows where one press answers, and after the server's check one result line ("Rätt." or "Inte
 * riktigt." and the explanation) with the one action under it: "Nästa", or "Försök igen" for a wrong answer, since the
 * question is then asked again. No score. The server checks the answer, so the card only says which option was sent
 * (`chosen`) and shows `result` when it comes; until then the chosen row reads "Rättas…" and every row is held.
 *
 * Keys while the focus is in the card: 1 to 9 answer, ↑ ↓ Home End move between the options. A held row keeps the focus
 * (aria-disabled, not disabled), and after the action the focus goes to the first option of the question that follows.
 * The result line is a status region, so it is read when it comes. All words but the card's own come as props.
 */
export type QuestionResult = {
  correct: boolean;
  /** One or two sentences: why. Plain text. */
  explain?: string;
};

export type QuestionCardProps = {
  /** The room's locale: the card's own words ("Rättas…", "Rätt.") follow it. */
  locale: string;
  prompt: string;
  /** Three or four answers, in the order the server gave them. */
  options: readonly string[];
  onAnswer: (index: number) => void;
  /** The option that was sent, until the next question (or the retry) clears it. */
  chosen?: number | null;
  /** The server's check of `chosen`. */
  result?: QuestionResult | null;
  /** The one action after a result: `labels.question.next` or `labels.question.retry`. */
  action?: { label: string; onClick: () => void };
  /** Why the options are held, shown under them ("Kräver anslutning" without a network). */
  unavailable?: string;
  /** Under the action: an answer that did not arrive (`ErrorNotice placement="row"`). */
  notice?: ReactNode;
  /** The prompt's heading level in the view (default 2). */
  headingLevel?: 2 | 3 | 4;
  ref?: Ref<HTMLDivElement>;
  className?: string;
};

type OptionState = "idle" | "checking" | "correct" | "wrong" | "held";

export function QuestionCard({
  locale,
  prompt,
  options,
  onAnswer,
  chosen = null,
  result = null,
  action,
  unavailable,
  notice,
  headingLevel = 2,
  ref,
  className,
}: QuestionCardProps) {
  const labels = reviewLabelsFor(locale).question;
  const promptId = useId();
  const listRef = useRef<HTMLOListElement>(null);
  // The action removes itself; the focus then goes to the first option once the view has cleared the answer.
  const focusFirst = useRef(false);

  const answered = chosen !== null && chosen >= 0 && chosen < options.length;
  const open = !answered && !unavailable;

  useLayoutEffect(() => {
    if (!focusFirst.current || answered) return;
    focusFirst.current = false;
    const list = listRef.current;
    const active = list?.ownerDocument.activeElement ?? null;
    const root = list?.closest(".sk-question");
    if (
      active &&
      active !== list?.ownerDocument.body &&
      !root?.contains(active)
    )
      return;
    list?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [answered, prompt]);

  function answer(index: number) {
    if (!open) return;
    onAnswer(index);
  }

  function stateOf(index: number): OptionState {
    if (!answered) return unavailable ? "held" : "idle";
    if (index !== chosen) return "held";
    if (!result) return "checking";
    return result.correct ? "correct" : "wrong";
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (
      event.defaultPrevented ||
      event.nativeEvent.isComposing ||
      event.ctrlKey ||
      event.altKey ||
      event.metaKey ||
      !/^[1-9]$/.test(event.key)
    )
      return;
    const index = Number(event.key) - 1;
    if (index >= options.length) return;
    event.preventDefault();
    answer(index);
  }

  const Heading = `h${headingLevel}` as "h2";
  const classes = ["sk-question", className].filter(Boolean).join(" ");

  return (
    <KeyScope
      ref={ref}
      role="group"
      aria-labelledby={promptId}
      className={classes}
      onKeyDown={onKeyDown}
    >
      <Heading id={promptId} className="sk-question__prompt">
        {prompt}
      </Heading>
      <KeyScope
        as="div"
        roving
        role="group"
        aria-label={labels.options}
        className="sk-question__options"
      >
        <ol ref={listRef} className="sk-question__list">
          {options.map((option, index) => {
            const state = stateOf(index);
            return (
              <li key={`${index}:${option}`}>
                <button
                  type="button"
                  className="sk-question__option"
                  data-state={state}
                  aria-keyshortcuts={index < 9 ? String(index + 1) : undefined}
                  aria-disabled={state === "idle" ? undefined : "true"}
                  aria-busy={state === "checking" || undefined}
                  onClick={() => answer(index)}
                >
                  <span className="sk-question__label">{option}</span>
                  {state === "checking" ? (
                    <>
                      {/* A space, so the row reads "Belysningsstyrka Rättas…"; the grid does not draw it. */}{" "}
                      <span className="sk-question__checking">
                        {labels.checking}
                      </span>
                    </>
                  ) : state === "correct" || state === "wrong" ? (
                    <span className="sk-question__mark" aria-hidden="true" />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ol>
      </KeyScope>
      {unavailable && !answered ? (
        <p className="sk-question__unavailable">{unavailable}</p>
      ) : null}
      <p
        role="status"
        className="sk-question__result"
        data-correct={result && answered ? String(result.correct) : undefined}
      >
        {result && answered ? (
          <>
            <span className="sk-question__verdict">
              {result.correct ? labels.correct : labels.wrong}
            </span>
            {result.explain ? ` ${result.explain}` : null}
          </>
        ) : null}
      </p>
      {result && answered && action ? (
        <button
          type="button"
          className={buttonClass("primary", "sk-question__action")}
          onClick={() => {
            focusFirst.current = true;
            action.onClick();
          }}
        >
          {action.label}
        </button>
      ) : null}
      {notice ? <div className="sk-question__notice">{notice}</div> : null}
    </KeyScope>
  );
}
