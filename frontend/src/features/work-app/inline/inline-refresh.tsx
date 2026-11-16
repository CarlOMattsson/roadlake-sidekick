import { RefreshIcon } from "../board/board-sections";
import { ownerDateFormat } from "../../mcp-apps/app-timezone";
import { refreshLabelsFor } from "./inline-refresh-labels";
import "./inline-summary.css";

/**
 * The read-again control of an inline board or agenda card, as WorkRoom keeps it: where the last read stands, when the
 * last one that succeeded ended (epoch millis), and the request. A card gets it only when the host answers the read.
 */
export type ListRefresh = {
  phase: "idle" | "busy" | "failed";
  at?: number;
  onRefresh: () => void;
};

/** The time of day in the owner's zone and the app's language, 24 hours: "14:05". */
function clockTime(at: number, dateLocale: string): string {
  return ownerDateFormat(dateLocale, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(at));
}

/**
 * What a card's head says in the date's place: "Updated 14:05" once the owner has refreshed it, else the date the
 * caller passes.
 */
export function refreshedOr(
  refresh: ListRefresh | undefined,
  dateLocale: string,
  date: string,
): string {
  return refresh?.at === undefined
    ? date
    : refreshLabelsFor(dateLocale).updated(clockTime(refresh.at, dateLocale));
}

/**
 * The icon button in the corner of the card, level with the head. While the read runs it stays focusable
 * (aria-disabled, not disabled) and a second press does nothing; a failed read leaves it as the way to try again.
 */
export function InlineRefreshButton({
  refresh,
  dateLocale,
}: {
  refresh: ListRefresh;
  dateLocale: string;
}) {
  const words = refreshLabelsFor(dateLocale);
  const busy = refresh.phase === "busy";
  return (
    <>
      <button
        type="button"
        className="sk-iconbtn work-inline-refresh"
        aria-label={words.refresh}
        title={words.refresh}
        aria-busy={busy ? "true" : undefined}
        aria-disabled={busy ? "true" : undefined}
        onClick={() => {
          if (!busy) refresh.onRefresh();
        }}
      >
        <RefreshIcon />
      </button>
      <span className="work-visually-hidden" aria-live="polite">
        {busy ? words.refreshing : ""}
      </span>
    </>
  );
}

/** The line under the card's head after a failed read; the card keeps the data it showed. */
export function RefreshFailure({
  refresh,
  dateLocale,
}: {
  refresh: ListRefresh;
  dateLocale: string;
}) {
  if (refresh.phase !== "failed") return null;
  return (
    <p className="work-compact-status" data-tone="overdue" role="alert">
      {refreshLabelsFor(dateLocale).failed}
    </p>
  );
}
