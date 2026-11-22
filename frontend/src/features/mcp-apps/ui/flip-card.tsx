import {
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
import "../awaiting.css";
import "./flip-card.css";

/**
 * One review card (designsystem §3 Repetition): a fixed face (a photo, or the question as text), then either the front's
 * prompt and "Visa svaret", or the answer and the grade buttons. The prompt and the answer share one cell, and so do
 * the reveal and the grades, so the card keeps its height when it turns and the grade buttons appear where the reveal
 * button was: the thumb stays put. Fullscreen is one centred column; inline puts the 120 face beside the text.
 *
 * The keys act while the focus is inside the card (WCAG 2.1.4 "active only on focus", so no switch is needed): Space or
 * Enter turns it, 1 to 9 choose a grade. A turn by the user moves the focus to the answer (read with a hidden "Svar:"),
 * and a grade moves it back to the reveal button of the next card. The answer rises in over --sk-dur-slow, which is
 * 0 ms under reduced motion, and the stylesheet turns the animation off there as well.
 *
 * A photo is drawn only from a `data:image/` URL: the app makes no request of its own (the host's CSP allows `data:`
 * images and no connection), so any other source leaves the face empty. `alt` must not give the answer away.
 */
export type FlipFront = {
  /** The face photo, a `data:image/` URL with its alternative text. */
  photo?: { src: string; alt: string };
  /** Under a photo the prompt ("Vem är det här?"); without one the question itself, drawn on the face. */
  text?: string;
};

export type FlipBack = {
  /** The answer ("Lena Holm"). */
  title: string;
  /** One muted line under it ("Projektledare · Holm Bygg"). */
  meta?: string;
};

export type FlipGrade = {
  label: string;
  onChoose: () => void;
  /** The view's one primary action ("Kunde"); drawn as primary only in fullscreen. */
  primary?: boolean;
};

export type FlipCardProps = {
  /** The room's locale: the card's own words (reveal, the answer's lead) follow it. */
  locale: string;
  front: FlipFront;
  back: FlipBack;
  revealed: boolean;
  onReveal: () => void;
  /** In key order: the first is 1, the second 2. Two in the first version (Igen, Kunde). */
  grades: readonly FlipGrade[];
  /** `inline`: the 120 face of a Claude card, no primary button. `full`: the 200 face of the review layer. */
  density?: "inline" | "full";
  /** The card is on its way: the face is a skeleton and the reveal is held. */
  loading?: boolean;
  /** A grade is on its way: the grade buttons are held (they keep the focus). */
  busy?: boolean;
  /** Under the buttons: a grade that did not arrive (`ErrorNotice placement="row"`). */
  notice?: ReactNode;
  /** The card's root, so a view can put the focus on it and the keys work at once. */
  ref?: Ref<HTMLDivElement>;
  className?: string;
};

const DATA_IMAGE = /^data:image\/(?:png|jpeg|webp|gif|avif);/i;

/** A source the card may draw: an inline image, never a URL that would make a request. */
export function isDrawablePhoto(src: string): boolean {
  return DATA_IMAGE.test(src);
}

type Pending = "answer" | "reveal" | null;

export function FlipCard({
  locale,
  front,
  back,
  revealed,
  onReveal,
  grades,
  density = "full",
  loading = false,
  busy = false,
  notice,
  ref,
  className,
}: FlipCardProps) {
  const labels = reviewLabelsFor(locale);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const answerRef = useRef<HTMLDivElement>(null);
  const revealRef = useRef<HTMLButtonElement>(null);
  // Where the focus goes after a turn the user asked for. A turn the view makes by itself moves no focus.
  const pending = useRef<Pending>(null);

  useLayoutEffect(() => {
    const want = pending.current;
    if (want === null) return;
    if ((want === "answer") !== revealed) return;
    pending.current = null;
    const root = rootRef.current;
    const active = root?.ownerDocument.activeElement ?? null;
    // Only when the focus was in the card (or fell out of it with the side that went inert), never away from elsewhere.
    if (
      active &&
      active !== root?.ownerDocument.body &&
      !root?.contains(active)
    )
      return;
    (want === "answer" ? answerRef.current : revealRef.current)?.focus();
  }, [revealed]);

  const full = density === "full";
  const photo =
    front.photo && isDrawablePhoto(front.photo.src) ? front.photo : null;
  const textFace = !front.photo && !loading;

  function reveal() {
    if (loading || revealed) return;
    pending.current = "answer";
    onReveal();
  }

  function choose(grade: FlipGrade) {
    if (busy || !revealed) return;
    pending.current = "reveal";
    grade.onChoose();
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (
      event.defaultPrevented ||
      event.nativeEvent.isComposing ||
      event.ctrlKey ||
      event.altKey ||
      event.metaKey
    )
      return;
    const target = event.target as HTMLElement;
    if (target.closest("input, textarea, select, [contenteditable]")) return;
    if (!revealed) {
      // On a button the browser already presses it; elsewhere in the card the keys turn it.
      if (
        (event.key === " " || event.key === "Enter") &&
        target.tagName !== "BUTTON"
      ) {
        event.preventDefault();
        reveal();
      }
      return;
    }
    if (!/^[1-9]$/.test(event.key)) return;
    const grade = grades[Number(event.key) - 1];
    if (!grade) return;
    event.preventDefault();
    choose(grade);
  }

  function setRoot(node: HTMLDivElement | null) {
    rootRef.current = node;
    if (typeof ref === "function") ref(node);
    else if (ref) ref.current = node;
  }

  const classes = ["sk-flip", className].filter(Boolean).join(" ");

  return (
    <KeyScope
      ref={setRoot}
      role="group"
      aria-label={labels.card}
      aria-busy={loading || undefined}
      tabIndex={-1}
      className={classes}
      data-density={density}
      data-revealed={revealed || undefined}
      data-face={textFace ? "text" : "photo"}
      onKeyDown={onKeyDown}
    >
      <div className="sk-flip__head">
        <div
          className={
            textFace ? "sk-flip__face sk-flip__face--text" : "sk-flip__face"
          }
          aria-hidden={photo || textFace ? undefined : "true"}
        >
          {loading ? (
            <span className="sidekick-wait-block sk-flip__skeleton" />
          ) : photo ? (
            <img
              className="sk-flip__photo"
              src={photo.src}
              alt={photo.alt}
              draggable={false}
            />
          ) : textFace ? (
            <p className="sk-flip__question">{front.text}</p>
          ) : null}
        </div>
        <div className="sk-flip__stack sk-flip__text">
          <div
            className="sk-flip__side"
            aria-hidden={revealed ? "true" : undefined}
            inert={revealed}
          >
            {loading ? (
              <span className="sidekick-wait-block sk-flip__prompt-skeleton" />
            ) : front.photo && front.text ? (
              <p className="sk-flip__prompt">{front.text}</p>
            ) : null}
          </div>
          <div
            className="sk-flip__side sk-flip__side--back"
            aria-hidden={revealed ? undefined : "true"}
            inert={!revealed}
          >
            <div ref={answerRef} className="sk-flip__answer" tabIndex={-1}>
              <span className="sk-flip__sr">{labels.answer} </span>
              <p className="sk-flip__title">{back.title}</p>
              {back.meta ? <p className="sk-flip__meta">{back.meta}</p> : null}
            </div>
          </div>
        </div>
      </div>
      <div className="sk-flip__stack sk-flip__actions">
        <div
          className="sk-flip__side"
          aria-hidden={revealed ? "true" : undefined}
          inert={revealed}
        >
          <button
            ref={revealRef}
            type="button"
            className={buttonClass(
              full ? "primary" : "secondary",
              "sk-flip__btn",
            )}
            aria-disabled={loading || undefined}
            aria-keyshortcuts="Space Enter"
            onClick={reveal}
          >
            {labels.reveal}
          </button>
        </div>
        <div
          className="sk-flip__side sk-flip__grades"
          role="group"
          aria-label={labels.grades}
          aria-hidden={revealed ? undefined : "true"}
          inert={!revealed}
        >
          {grades.map((grade, index) => (
            <button
              key={grade.label}
              type="button"
              className={buttonClass(
                full && grade.primary ? "primary" : "secondary",
                "sk-flip__btn",
              )}
              aria-keyshortcuts={index < 9 ? String(index + 1) : undefined}
              aria-disabled={busy || undefined}
              onClick={() => choose(grade)}
            >
              {grade.label}
            </button>
          ))}
        </div>
      </div>
      {notice ? <div className="sk-flip__notice">{notice}</div> : null}
    </KeyScope>
  );
}
