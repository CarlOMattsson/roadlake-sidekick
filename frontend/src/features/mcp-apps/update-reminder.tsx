import { useEffect, useRef, useState, type ReactNode } from "react";
import { appLocale, type AppLocale } from "./app-locale";
import { roomEnabled } from "./enabled-rooms";
import {
  dismissUpdateNotice,
  useUpdateNotice,
  type UpdateNotice,
} from "./update-notice";
import { updateReminderLabelsFor } from "./update-reminder-labels";
import { Button } from "./ui/button";
import "./update-reminder.css";

/** The command that brings a self-hosted instance up to date (tools/work.sh update). */
export const UPDATE_COMMAND = "tools/work.sh update";

/**
 * What a room's ⋯ button adds while the update reminder stands: a small calm dot, drawn inside the button, and a
 * suffix on its accessible name ("Fler val – uppdatering finns att hämta"), so the dot is said and not only
 * seen. No banner and no modal: the dot leads to the ⋯ menu. With the Control room on, its "Kontroll" entry holds
 * the row; with Control off (SIDEKICK_ENABLED_ROOMS=work) the menu holds the row itself (`MenuUpdateReminder`), and
 * `inMenu` tells a room whose ⋯ exists only for Control that it needs the button anyway. `inMenu` stays true after
 * "not for this version", so the button the owner just used does not vanish under the confirmation.
 * Without a reminder the label is `label` unchanged and there is no dot.
 */
export function useMoreMark(label: string): {
  label: string;
  dot: ReactNode;
  inMenu: boolean;
} {
  const notice = useUpdateNotice();
  const menuHoldsRow = !roomEnabled("control");
  const [kept, setKept] = useState(false);
  if (notice && menuHoldsRow && !kept) setKept(true);
  const inMenu = menuHoldsRow && (kept || Boolean(notice));
  if (!notice) return { label, dot: null, inMenu };
  const labels = updateReminderLabelsFor(appLocale());
  return {
    label: `${label} – ${labels.moreSuffix}`,
    dot: <span className="sk-update-dot" aria-hidden="true" />,
    inMenu,
  };
}

/**
 * The reminder inside a room's ⋯ menu when the Control room is off and so cannot hold it: the same compact row,
 * in the app language. With Control on the menu keeps its "Kontroll" entry and this draws nothing (one place for
 * the row, no second copy to keep in step).
 */
export function MenuUpdateReminder({ now }: { now?: () => Date }) {
  if (roomEnabled("control")) return null;
  return <UpdateReminderRow locale={appLocale()} now={now} menu />;
}

/**
 * The compact row in Control (the room that holds the instance's settings): how old the running code is, the command
 * that updates it in a code element the owner can select and copy, and one button, "Påminn inte för den här
 * versionen". The button remembers the commit, so the reminder comes back only for a newer version that grows old too.
 * After it, one line says so in the row's place and the focus rests on it. Nothing is drawn without a reminder.
 */
export function UpdateReminderRow({
  locale,
  now,
  menu,
}: {
  locale: AppLocale;
  now?: () => Date;
  /** Inside a ⋯ menu card: the row takes the card's padding. */
  menu?: boolean;
}) {
  const labels = updateReminderLabelsFor(locale);
  const notice = useUpdateNotice(now);
  const [dismissed, setDismissed] = useState<UpdateNotice>();
  const confirmation = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (dismissed) confirmation.current?.focus();
  }, [dismissed]);
  const rowClass = menu ? "sk-update-row sk-update-row--menu" : "sk-update-row";
  if (notice)
    return (
      <div className={rowClass} lang={locale}>
        <p className="sk-update-row__age">
          {labels.age(notice.ageDays, notice.commit)}
        </p>
        <p className="sk-update-row__how">
          {labels.howTo} <code>{UPDATE_COMMAND}</code>
        </p>
        <Button
          variant="quiet"
          onClick={() => {
            setDismissed(notice);
            dismissUpdateNotice(notice.commit);
          }}
        >
          {labels.dismiss}
        </Button>
      </div>
    );
  return dismissed ? (
    <p
      ref={confirmation}
      className={`${rowClass} sk-update-row__age`}
      role="status"
      tabIndex={-1}
      lang={locale}
    >
      {labels.dismissed}
    </p>
  ) : null;
}
