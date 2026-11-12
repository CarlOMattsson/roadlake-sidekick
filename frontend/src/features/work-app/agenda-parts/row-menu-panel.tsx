import { workStatusLabel } from "../labels";
import { Fold } from "../../mcp-apps/ui/fold";
import { workDate } from "../../mcp-apps/ui/due";
import { triageDueAt, type AgendaBucket } from "../work-items";
import { TASK_STATUSES, type WorkItemRecord } from "../transport";
import { CloseIcon } from "../agenda-icons";
import { DateChip } from "./date-chip";
import { DUE_SHORTCUTS, dueChoiceOf, epochDayIso } from "./agenda-helpers";
import { RowMenu } from "./row-menu";
import type { AgendaRowContext } from "./row-context";

type PanelProps = {
  ctx: AgendaRowContext;
  /** The record as read (a write goes against it) and the row as this view holds it now. */
  record: WorkItemRecord;
  item: WorkItemRecord;
};

/**
 * The quick choices of an open Task, under its row: Status, the four statuses on one line with the current one chosen,
 * and Datum. Every choice is a compact chip, 40 drawn and 48 to tap, on the row's shared surface. × closes it: the same
 * close as Escape, focus back on the row. It stands on the open row's first title line in the › column at every text
 * size, so the panel has one head.
 */
export function RowMenuPanel({
  ctx,
  record,
  item,
  group,
  moved,
  onClose,
}: PanelProps & {
  group: AgendaBucket;
  /** A triage move changed the row: its date choices are off. */
  moved: boolean;
  onClose: () => void;
}) {
  const { labels: t, menu, offers } = ctx;
  const statusChoices = TASK_STATUSES.filter((value) =>
    offers.statusOffered(value, item.status),
  );
  return (
    <RowMenu
      scrollKey={menu.largeText ? (menu.menuGroup ?? "") : ""}
      large={menu.largeText}
    >
      <button
        type="button"
        className="work-agenda-menu-close"
        aria-label={t.closeMenu}
        onClick={onClose}
      >
        <CloseIcon />
      </button>
      {statusChoices.length > 0 && (
        <StatusChoices
          ctx={ctx}
          record={record}
          item={item}
          group={group}
          choices={statusChoices}
        />
      )}
      {offers.dueOffered && (
        <DueChoices
          ctx={ctx}
          record={record}
          item={item}
          moved={moved}
          statusChoicesShown={statusChoices.length > 0}
        />
      )}
    </RowMenu>
  );
}

/** The Status row of the menu: the statuses on one line, the current one chosen. */
function StatusChoices({
  ctx,
  record,
  item,
  group,
  choices,
}: PanelProps & {
  group: AgendaBucket;
  choices: readonly (typeof TASK_STATUSES)[number][];
}) {
  const { labels: t, menu, disabled, writes } = ctx;
  const { largeText, menuGroup } = menu;
  return (
    <div className="work-agenda-menu-row">
      {largeText ? (
        <Fold
          className="work-agenda-menu-fold"
          text={t.status}
          // The value stands under a folded group only: an open one shows it as its chosen chip.
          meta={
            menuGroup === "status"
              ? undefined
              : workStatusLabel(t, item.status ?? "")
          }
          open={menuGroup === "status"}
          onToggle={() => menu.foldGroup("status")}
        />
      ) : (
        <span className="work-agenda-menu-label" aria-hidden="true">
          {t.status}
        </span>
      )}
      {(!largeText || menuGroup === "status") && (
        <div role="group" aria-label={t.status} className="work-agenda-choices">
          {choices.map((value) => (
            <button
              key={value}
              type="button"
              className="sk-chip"
              aria-pressed={item.status === value}
              disabled={disabled}
              onClick={() =>
                // "Klar" on an overdue row is the triage move that mutes the row with its note.
                writes.send(
                  record,
                  { status: value },
                  undefined,
                  group === "overdue" && value === "completed",
                )
              }
            >
              {workStatusLabel(t, value)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** The Datum row of the menu: the three shortcuts, the Task's own date when it is none of them, and "Välj datum …". */
function DueChoices({
  ctx,
  record,
  item,
  moved,
  statusChoicesShown,
}: PanelProps & {
  moved: boolean;
  /** False: the Datum group is the only one, so it is open at large text too. */
  statusChoicesShown: boolean;
}) {
  const { labels: t, now, menu, disabled, writes } = ctx;
  const { largeText, menuGroup } = menu;
  const { dueDay, dueShortcut, dueMeta } = dueChoiceOf(item, now, t);
  return (
    <div className="work-agenda-menu-row">
      {largeText ? (
        <Fold
          className="work-agenda-menu-fold"
          text={t.rescheduleRow}
          meta={menuGroup === "due" ? undefined : dueMeta}
          open={menuGroup === "due"}
          onToggle={() => menu.foldGroup("due")}
        />
      ) : (
        <span className="work-agenda-menu-label" aria-hidden="true">
          {t.rescheduleRow}
        </span>
      )}
      {(!largeText || menuGroup === "due" || !statusChoicesShown) && (
        <div
          role="group"
          aria-label={t.rescheduleGroup}
          className="work-agenda-choices"
        >
          {/* The Task's own date is chosen: one of the three shortcuts, or a fifth chip
              first with the date itself. A chosen chip moves nothing. */}
          {dueDay !== null && !dueShortcut && (
            <button type="button" className="sk-chip" aria-pressed>
              {workDate(item.due_at, now, t.dateLocale, { inline: true })}
            </button>
          )}
          {DUE_SHORTCUTS.map((target) => (
            <button
              key={target}
              type="button"
              className="sk-chip"
              aria-pressed={dueShortcut === target}
              disabled={disabled || moved}
              onClick={() => {
                if (dueShortcut !== target)
                  writes.moveDue(record, triageDueAt(now, target));
              }}
            >
              {target === "today"
                ? t.agendaGroup.today
                : target === "tomorrow"
                  ? t.triageTomorrow
                  : t.triageNextWeek}
            </button>
          ))}
          <DateChip
            text={t.rescheduleChoose}
            label={t.rescheduleDate}
            value={dueDay === null ? "" : epochDayIso(dueDay)}
            disabled={disabled || moved}
            onPick={(day) => writes.moveDueTo(record, day)}
          />
        </div>
      )}
    </div>
  );
}
