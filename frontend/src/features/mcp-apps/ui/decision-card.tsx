import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ElementType,
  type ReactNode,
} from "react";

import { buttonClass } from "./button";
import type { ApplyError } from "./decision-codes";
import { decisionLabelsFor } from "./decision-labels";
import { ChevronRightIcon } from "./icons";
import { KeyScope } from "./key-scope";
import { ErrorNotice } from "./states";
import { TrustNote } from "./trust-note";
import "./tokens.css";
import "./family.css";
import "./decision-card.css";

/**
 * The decision card: one thing Sidekick or Claude proposes to change (a suggestion, a ready conversation, a suspicious
 * suggestion), with the owner's answer on the card. The same parts in the same order everywhere: the trust note when
 * the check found something, the kicker with the source ("Förslag · från Morgonmejl · 07:02"), the title (what
 * changes), the changes, "Varför" and its sentence, and the answer row.
 *
 * The answer row always has Dismiss on the left and Approve on the right. Inline, Approve is a compact secondary and
 * Dismiss a compact tertiary; in `full` (the list of a fullscreen view, or its detail pane with `frame={false}`)
 * Approve is the compact primary and Dismiss a secondary, Edit (when given) stands apart at the start, and in a narrow frame the two answers share the
 * card's width at 48. A `suspicious` card has no Approve: inline it offers Dismiss (the suggested answer, framed) and
 * Review; in `full` Dismiss is the primary and "Godkänn ändå" a tertiary that asks once before it approves.
 *
 * Inline shows at most two changes, the rest counted on the last line, and "Varför" in at most two lines. Under a trust
 * note the note is the reason to read: its first reason, one change and no "Varför", so an inline card stays within a
 * phone's card height (`full` shows every reason). A suspicious card shows no change inline: it cannot be approved
 * there, and a long value (an account number) would take the lines its reason needs; Review leads to all of them.
 * `full` shows every change ("före → efter" when `before` is given), the whole sentence and the check's line
 * ("Kontrollerad · säker 94 %", "Inte kontrollerad"); `children` follow them in `full` (a QuoteBlock with the
 * untrusted text).
 *
 * The trust comes from the server's closed codes through `decisionTrust` (decision-codes.ts), never from free text.
 * `edited` adds "ändrad av dig" to the kicker when the owner changed the suggestion before deciding. `actions.open`
 * makes the title the way to the card's detail (a list of cards), a button with › that keeps the title's type.
 *
 * `busy` marks the answer in flight (both answers wait); `failed` puts the failure's line under the buttons and the
 * card stays, with the server's `applyError` in words when it gave one. `decided` turns the card into its receipt
 * ("Tillagd: Lena Holm · Öppna ›"); with `hold` the card keeps the height it had while undecided, so nothing moves
 * while the view's ReceiptBar offers Ångra, and it shrinks to the receipt once `hold` is dropped. The view formats
 * `source.at` (the owner's clock) and owns the receipt bar, the keyboard shortcuts and the calls.
 */
export type DecisionTrustState = "ok" | "unsure" | "suspicious" | "off";

export type DecisionTrust = {
  state: DecisionTrustState;
  /** The check's reason, one sentence, for `unsure` and `suspicious`: the one an inline card shows. */
  reason?: string;
  /** Every reason, the first one first, when there are more: `full` shows them all. */
  reasons?: readonly string[];
  /** The checker's confidence in per cent, for the `ok` line in `full`. */
  confidence?: number;
};

export type DecisionChange = {
  label: string;
  value: string;
  /** The value before the change, shown as "före → efter" in `full`. */
  before?: string;
};

export type DecisionAnswer = "approve" | "dismiss";

export type DecisionCardProps = {
  locale: string;
  /** The family's word for the thing: "Förslag", "Färdigt samtal". */
  kicker: string;
  /** What changes, written by the server: "Skapa kontakt: Lena Holm". */
  title: string;
  changes?: DecisionChange[];
  /** One sentence on why it is proposed. */
  why?: string;
  /** Who proposed it; `at` is display text the view formats ("07:02", "i går 18:40"). */
  source?: { name: string; at?: string };
  trust?: DecisionTrust;
  /** The owner changed the suggestion before deciding (the server's payload differs from the proposal). */
  edited?: boolean;
  actions: {
    /**
     * The two answers. A card that cannot give one where it is drawn leaves it out (a ready conversation without the
     * host's message to start it, or without the tool that skips it); a suggestion always has both.
     */
    approve?: () => void;
    dismiss?: () => void;
    /** Opens the detail view. Required for a suspicious card inline, which cannot be approved there. */
    review?: () => void;
    /** Opens the target's form in suggestion mode (`full` only). */
    edit?: () => void;
    /**
     * Opens the card's detail from its title (a card in a list): the title is then a button with ›, and `review` is
     * still the suspicious card's own answer. Absent: the title is plain text.
     */
    open?: () => void;
  };
  /** Other words for the two answers ("Starta", "Hoppa över idag" on a ready conversation). */
  answerLabels?: { approve?: string; dismiss?: string };
  density?: "inline" | "full";
  /** `full` without the card's surface and edge: the detail pane beside a list. */
  frame?: boolean;
  busy?: DecisionAnswer;
  failed?: DecisionAnswer;
  /** Why the server refused an approval; words for it replace the general failure line. */
  applyError?: ApplyError;
  decided?: {
    message: string;
    open?: { label: string; onOpen: () => void };
    /** Keep the undecided height while the view's receipt offers Ångra. */
    hold?: boolean;
  };
  headingLevel?: 2 | 3 | 4;
  children?: ReactNode;
  className?: string;
};

const INLINE_CHANGES = 2;

export function DecisionCard({
  locale,
  kicker,
  title,
  changes = [],
  why,
  source,
  trust,
  edited,
  actions,
  answerLabels,
  density = "inline",
  frame = true,
  busy,
  failed,
  applyError,
  decided,
  headingLevel = 3,
  children,
  className,
}: DecisionCardProps) {
  const t = decisionLabelsFor(locale);
  const titleId = useId();
  const full = density === "full";
  const state = trust?.state ?? "ok";
  const suspicious = state === "suspicious";
  const noted = state === "unsure" || suspicious;
  const Heading = `h${headingLevel}` as ElementType;

  // The undecided height, read while undecided, so a decided card that holds keeps it.
  const root = useRef<HTMLElement | null>(null);
  const [held, setHeld] = useState<number | null>(null);
  useLayoutEffect(() => {
    if (!decided && root.current)
      setHeld(root.current.getBoundingClientRect().height);
  }, [decided]);

  const classes = [
    "sk-decision",
    `sk-decision--${density}`,
    frame ? "sk-card" : "sk-decision--bare",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  if (decided) {
    return (
      <article
        ref={root}
        className={`${classes} sk-decision--decided`}
        aria-labelledby={titleId}
        style={decided.hold && held ? { minHeight: held } : undefined}
        data-hold={decided.hold ? "true" : undefined}
      >
        <p className="sk-decision__receipt" id={titleId}>
          <CheckGlyph />
          <span className="sk-decision__receipt-text">{decided.message}</span>
        </p>
        {decided.open ? (
          <button
            type="button"
            className="sk-btn sk-btn--open sk-decision__receipt-open"
            onClick={decided.open.onOpen}
          >
            {decided.open.label}
            <ChevronRightIcon />
          </button>
        ) : null}
      </article>
    );
  }

  const shownChanges = full
    ? changes
    : changes.slice(0, suspicious ? 0 : noted ? 1 : INLINE_CHANGES);
  const hiddenChanges = changes.length - shownChanges.length;
  const kickerText = [
    kicker,
    source ? t.from(source.name) : null,
    source?.at ?? null,
    edited ? t.edited : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const checkLine = full
    ? state === "ok" && trust
      ? t.trust.ok(trust.confidence)
      : state === "off"
        ? t.trust.off
        : null
    : null;
  const waiting = busy !== undefined;

  return (
    <article
      ref={root}
      className={classes}
      aria-labelledby={titleId}
      aria-busy={waiting || undefined}
      data-trust={trust ? state : undefined}
    >
      {noted ? (
        <TrustNote
          state={suspicious ? "suspicious" : "unsure"}
          reason={
            full && trust?.reasons?.length
              ? trust.reasons.join(" ")
              : trust?.reason
          }
          locale={locale}
          flow={full ? "block" : "run"}
          className="sk-decision__trust"
        />
      ) : null}
      <p className="sk-eyebrow sk-decision__kicker">{kickerText}</p>
      <Heading className="sk-card__title sk-decision__title" id={titleId}>
        {actions.open ? (
          <button
            type="button"
            className="sk-decision__open"
            data-sk-open=""
            onClick={actions.open}
          >
            <span className="sk-decision__open-text">{title}</span>
            <ChevronRightIcon />
          </button>
        ) : (
          title
        )}
      </Heading>
      {shownChanges.length > 0 ? (
        <ul className="sk-decision__changes">
          {shownChanges.map((change, index) => (
            <li
              className="sk-decision__change"
              key={`${change.label}-${index}`}
            >
              <span className="sk-decision__change-label">{change.label}:</span>{" "}
              {full && change.before !== undefined ? (
                <>
                  <span className="sk-decision__change-before">
                    {change.before}
                  </span>
                  <span aria-hidden="true"> → </span>
                  <span className="sk-decision__sr"> {t.changedTo} </span>
                </>
              ) : null}
              <span className="sk-decision__change-value">{change.value}</span>
              {hiddenChanges > 0 && index === shownChanges.length - 1 ? (
                <span
                  className="sk-decision__change-more"
                  aria-label={t.moreChangesLabel(hiddenChanges)}
                >
                  {" "}
                  {t.moreChanges(hiddenChanges)}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {why && (full || !noted) ? (
        <p className="sk-decision__why">
          <span className="sk-decision__why-label">{t.why}</span> {why}
        </p>
      ) : null}
      {checkLine ? <p className="sk-card__meta">{checkLine}</p> : null}
      {full ? children : null}
      <Answers
        locale={locale}
        full={full}
        suspicious={suspicious}
        actions={actions}
        answerLabels={answerLabels}
        busy={busy}
        title={title}
      />
      {failed ? (
        <ErrorNotice
          locale={locale}
          placement="row"
          message={
            failed === "dismiss"
              ? t.failedDismiss
              : applyError
                ? t.applyErrors[applyError]
                : t.failedApprove
          }
        />
      ) : null}
    </article>
  );
}

function Answers({
  locale,
  full,
  suspicious,
  actions,
  answerLabels,
  busy,
  title,
}: {
  locale: string;
  full: boolean;
  suspicious: boolean;
  actions: DecisionCardProps["actions"];
  answerLabels: DecisionCardProps["answerLabels"];
  busy?: DecisionAnswer;
  title: string;
}) {
  const t = decisionLabelsFor(locale);
  const [confirming, setConfirming] = useState(false);
  const anyway = useRef<HTMLButtonElement | null>(null);
  const cancel = useRef<HTMLButtonElement | null>(null);
  const returnFocus = useRef(false);
  useLayoutEffect(() => {
    if (confirming) cancel.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      anyway.current?.focus();
    }
  }, [confirming]);

  const waiting = busy !== undefined;
  const guard = (run: (() => void) | undefined) => () => {
    if (!waiting) run?.();
  };
  const held = waiting ? { "aria-disabled": true as const } : {};
  const dismissLabel =
    busy === "dismiss" ? t.dismissBusy : (answerLabels?.dismiss ?? t.dismiss);
  const approveLabel =
    busy === "approve" ? t.approveBusy : (answerLabels?.approve ?? t.approve);
  const compact = "sk-btn--compact sk-decision__answer";
  const takeBack = () => {
    returnFocus.current = true;
    setConfirming(false);
  };

  if (confirming)
    return (
      <KeyScope
        className="sk-decision__answers sk-decision__answers--confirm"
        role="group"
        aria-label={t.confirmAnyway}
        onEscape={takeBack}
      >
        <p className="sk-decision__confirm">{t.confirmAnyway}</p>
        <button
          ref={cancel}
          type="button"
          className={buttonClass("quiet", compact)}
          onClick={takeBack}
        >
          {t.cancel}
        </button>
        <button
          type="button"
          className={buttonClass("secondary", compact)}
          aria-busy={busy === "approve" || undefined}
          {...held}
          onClick={guard(actions.approve)}
        >
          {busy === "approve" ? t.approveBusy : t.approveAnyway}
        </button>
      </KeyScope>
    );

  const dismiss = actions.dismiss ? (
    <button
      type="button"
      className={buttonClass(
        suspicious
          ? full
            ? "primary"
            : "secondary"
          : full
            ? "secondary"
            : "quiet",
        compact,
      )}
      aria-busy={busy === "dismiss" || undefined}
      {...held}
      onClick={guard(actions.dismiss)}
    >
      {dismissLabel}
    </button>
  ) : null;

  if (suspicious)
    return (
      <div className="sk-decision__answers">
        {dismiss}
        {full ? (
          <button
            ref={anyway}
            type="button"
            className={buttonClass("quiet", compact)}
            {...held}
            onClick={guard(() => setConfirming(true))}
          >
            {t.approveAnyway}
          </button>
        ) : actions.review ? (
          <button
            type="button"
            className={buttonClass("quiet", compact)}
            {...held}
            onClick={guard(actions.review)}
          >
            {t.review}
          </button>
        ) : null}
      </div>
    );

  if (!actions.approve && !actions.dismiss) return null;
  return (
    <div className="sk-decision__answers">
      {full && actions.edit ? (
        <button
          type="button"
          className={buttonClass("quiet", `${compact} sk-decision__edit`)}
          aria-label={`${t.edit}: ${title}`}
          {...held}
          onClick={guard(actions.edit)}
        >
          {t.edit}
        </button>
      ) : null}
      {dismiss}
      {actions.approve ? (
        <button
          type="button"
          className={buttonClass(full ? "primary" : "secondary", compact)}
          aria-busy={busy === "approve" || undefined}
          {...held}
          onClick={guard(actions.approve)}
        >
          {approveLabel}
        </button>
      ) : null}
    </div>
  );
}

function CheckGlyph() {
  return (
    <svg
      className="sk-decision__receipt-glyph"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.25"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  );
}
