import { aiUsageShown } from "../mcp-apps/ai-usage-shown";
import { Button } from "../mcp-apps/ui/button";
import { useRead } from "../mcp-apps/ui/use-read";
import { usd } from "../mcp-apps/ui/usd";
import { aiUsageLabelsFor } from "./ai-usage-labels";
import type { ControlTransport } from "./transport";
import "../mcp-apps/update-reminder.css";

/**
 * The AI cost row of Control's full view, one of the instance's rows (the update reminder's shape): "AI this month"
 * with what the AI Steps cost of the month's cap, then today's starts of the day's cap, and Claude Code's own estimate
 * only when it has one. Drawn only where the instance switched it on and the host offers get_ai_usage; otherwise
 * nothing is drawn and the tool is never called. It reads again with the room (`refreshKey`).
 */
export function AiUsageRow({
  transport,
  locale,
  refreshKey,
}: {
  transport: Pick<ControlTransport, "aiUsage">;
  locale: "sv" | "en";
  refreshKey?: number;
}) {
  const read = aiUsageShown() ? transport.aiUsage : undefined;
  const [state, retry] = useRead(read, refreshKey);
  if (!read) return null;
  const t = aiUsageLabelsFor(locale);
  const dateLocale = locale === "sv" ? "sv-SE" : "en-GB";
  return (
    <div className="sk-update-row control-ai-usage" lang={locale}>
      {state.phase === "ready" ? (
        <>
          <p className="control-ai-usage__spent">
            {`${t.title}: `}
            <strong>
              {t.spent(
                usd(state.value.spent_usd, dateLocale),
                usd(state.value.monthly_cap_usd, dateLocale),
              )}
            </strong>
          </p>
          <p>
            {t.starts(state.value.starts_today, state.value.daily_starts_cap)}
            {state.value.client_estimate_usd > 0
              ? ` · ${t.estimate(usd(state.value.client_estimate_usd, dateLocale))}`
              : null}
          </p>
        </>
      ) : state.phase === "reading" ? (
        <p role="status">{t.loading}</p>
      ) : (
        <>
          <p role="status">{t.failed}</p>
          <Button variant="quiet" onClick={retry}>
            {t.retry}
          </Button>
        </>
      )}
    </div>
  );
}
