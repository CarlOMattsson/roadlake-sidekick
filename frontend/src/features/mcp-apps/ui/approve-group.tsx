import type { ElementType } from "react";

import { buttonClass } from "./button";
import { decisionLabelsFor } from "./decision-labels";
import { ErrorNotice } from "./states";
import "./tokens.css";
import "./family.css";
import "./approve-group.css";

/**
 * A group of suggestions the server marked safe to approve together, with one button for all of them. Each row is a
 * toggle with a ring that is filled while the row is in the group; a tap takes it out (or back) and the button's count
 * follows ("Godkänn alla 3", "Godkänn 2"). There is no "select all". Which suggestions belong in the group is the
 * server's decision (`bulk`); this component counts nothing on its own, and a suspicious or unsure suggestion never
 * reaches it.
 *
 * `max` caps one confirmation: only the first `max` items form the batch, the rest are named in a line under it and
 * wait for the next one. Claude's voice mode approves at most three per confirmation, so a view that answers there
 * passes `max={3}`; `groupBatch` gives the same ids to a caller that confirms without drawing the group. A row taken
 * out does not pull in the next item, so nothing moves under the owner's finger.
 *
 * The view owns `excluded` (reset it when the items change), the call, the receipt with Ångra for the whole group, and
 * the card around it (kicker, OpenLink). `busy` holds every control while the approval runs; `failed` puts the
 * failure's line under the button and keeps the group as it was.
 */
export type ApproveGroupItem = { id: string; label: string };

export type GroupBatch = {
  /** The items this confirmation covers, in order. */
  batch: ApproveGroupItem[];
  /** The ids that will be approved: the batch less the rows taken out. */
  ids: string[];
  /** How many items wait beyond the batch. */
  beyond: number;
};

export function groupBatch(
  items: readonly ApproveGroupItem[],
  excluded: ReadonlySet<string>,
  max?: number,
): GroupBatch {
  const size =
    max === undefined
      ? items.length
      : Math.max(0, Math.min(items.length, Math.floor(max)));
  const batch = items.slice(0, size);
  return {
    batch,
    ids: batch.filter((item) => !excluded.has(item.id)).map((item) => item.id),
    beyond: items.length - batch.length,
  };
}

export function ApproveGroup({
  locale,
  title,
  items,
  excluded,
  onToggle,
  onApproveAll,
  busy = false,
  failed = false,
  max,
  headingLevel = 3,
  heading = "card",
  className,
}: {
  locale: string;
  /** "3 säkra förslag", "Säkra förslag (3)". */
  title: string;
  items: readonly ApproveGroupItem[];
  excluded: ReadonlySet<string>;
  onToggle: (id: string) => void;
  /** Called with the ids in the batch that are still in the group. */
  onApproveAll: (ids: string[]) => void;
  busy?: boolean;
  failed?: boolean;
  /** At most this many per confirmation (3 where Claude's voice mode answers). */
  max?: number;
  headingLevel?: 2 | 3 | 4;
  /** The title as an inline card's title, or as a section heading in a fullscreen view. */
  heading?: "card" | "section";
  className?: string;
}) {
  const t = decisionLabelsFor(locale);
  const { batch, ids, beyond } = groupBatch(items, excluded, max);
  const Heading = `h${headingLevel}` as ElementType;
  const count = ids.length;
  const label = busy
    ? t.approveBusy
    : count === 0
      ? t.group.none
      : count === items.length
        ? t.group.all(count)
        : t.group.some(count);
  const held = busy || count === 0;

  return (
    <section
      className={className ? `sk-approve ${className}` : "sk-approve"}
      aria-label={title}
      aria-busy={busy || undefined}
    >
      <Heading
        className={
          heading === "card"
            ? "sk-card__title sk-approve__title"
            : "sk-approve__title sk-approve__title--section"
        }
      >
        {title}
      </Heading>
      <ul className="sk-approve__rows">
        {batch.map((item) => {
          const included = !excluded.has(item.id);
          return (
            <li className="sk-approve__item" key={item.id}>
              <button
                type="button"
                className="sk-approve__row"
                aria-pressed={included}
                aria-disabled={busy || undefined}
                onClick={() => {
                  if (!busy) onToggle(item.id);
                }}
              >
                <Ring filled={included} />
                <span className="sk-approve__label">{item.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
      {beyond > 0 && max !== undefined ? (
        <p className="sk-approve__beyond">{t.group.beyond(beyond, max)}</p>
      ) : null}
      <div className="sk-approve__actions">
        <button
          type="button"
          className={buttonClass("secondary", "sk-btn--compact")}
          aria-busy={busy || undefined}
          aria-disabled={held || undefined}
          onClick={() => {
            if (!held) onApproveAll(ids);
          }}
        >
          {label}
        </button>
      </div>
      {failed ? (
        <ErrorNotice
          locale={locale}
          placement="row"
          message={t.failedApprove}
        />
      ) : null}
    </section>
  );
}

/** The row's ring: filled with a knocked-out tick while the row is in the group, an empty ring when it is out. */
function Ring({ filled }: { filled: boolean }) {
  return (
    <svg
      className="sk-approve__ring"
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
      data-filled={filled ? "true" : undefined}
    >
      <circle className="sk-approve__ring-frame" cx={8} cy={8} r={6.5} />
      {filled ? (
        <path className="sk-approve__ring-tick" d="M4.6 8.3L6.9 10.6L11.4 6" />
      ) : null}
    </svg>
  );
}
