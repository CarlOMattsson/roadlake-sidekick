import { useSyncExternalStore } from "react";

/**
 * The update reminder. It works offline, from the age of the running code: the backend writes the commit's short hash,
 * its date and the number of days to remind after into the app document (SIDEKICK_UPDATE_REMINDER_DAYS), as
 * `<meta name="sidekick-build-commit">`, `sidekick-build-date` and `sidekick-update-days`. The app counts the days with
 * its own clock; nothing is asked of anyone. No meta (the reminder is off, the date is unknown, or a host that does
 * not declare it such as the phone's own shell) means no reminder.
 *
 * The owner can say "not for this version" (`dismissUpdateNotice`). The answer is the commit, so a newer version
 * that grows old reminds again. It is kept in the frame's storage when the host allows it, else for the session in the
 * document, like the long-press tip of the Work room.
 */
export type UpdateNotice = {
  /** Short hash of the running commit. */
  commit: string;
  /** Whole days since that commit. */
  ageDays: number;
};

const DAY_MS = 24 * 60 * 60 * 1000;
const DISMISSED_KEY = "sidekick.updateDismissed";
const CHANGED = "sidekick:update-notice";

function declared(doc: Document, name: string): string | undefined {
  return doc.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content;
}

/** The reminder the document declares, when the running code is at least that many days old. Dismissal is not applied. */
export function readUpdateNotice(
  doc: Document,
  now: Date,
): UpdateNotice | undefined {
  const commit = declared(doc, "sidekick-build-commit");
  const built = Date.parse(declared(doc, "sidekick-build-date") ?? "");
  const days = Number(declared(doc, "sidekick-update-days"));
  if (!commit || Number.isNaN(built) || !(days > 0)) return undefined;
  const ageDays = Math.max(0, Math.floor((now.getTime() - built) / DAY_MS));
  return ageDays >= days ? { commit, ageDays } : undefined;
}

/** The commit the owner asked not to be reminded about, or "". */
function dismissedCommit(doc: Document = document): string {
  let stored: string | undefined;
  try {
    stored = localStorage.getItem(DISMISSED_KEY) ?? undefined;
  } catch {
    // No storage in this frame: only this session's answer counts.
  }
  return doc.documentElement.dataset.updateDismissed ?? stored ?? "";
}

/** No more reminders for this version. Every dot and row of the page follows at once. */
export function dismissUpdateNotice(commit: string) {
  document.documentElement.dataset.updateDismissed = commit;
  try {
    localStorage.setItem(DISMISSED_KEY, commit);
  } catch {
    // No storage in this frame: the document keeps the answer for the session.
  }
  window.dispatchEvent(new Event(CHANGED));
}

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGED, onChange);
  return () => window.removeEventListener(CHANGED, onChange);
}

/**
 * The reminder to show now, or undefined: off, not old enough, or dismissed for this commit. Where it is shown
 * (the Control room, or the ⋯ menus when Control is off, SIDEKICK_ENABLED_ROOMS) is the callers' business.
 * `now` is the clock; tests pass a fixed one.
 */
export function useUpdateNotice(
  now: () => Date = () => new Date(),
): UpdateNotice | undefined {
  const dismissed = useSyncExternalStore(subscribe, dismissedCommit);
  const notice = readUpdateNotice(document, now());
  return notice && notice.commit !== dismissed ? notice : undefined;
}
