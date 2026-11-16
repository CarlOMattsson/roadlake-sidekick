import { Button } from "../mcp-apps/ui/button";
import { useRead } from "../mcp-apps/ui/use-read";
import { usd } from "../mcp-apps/ui/usd";
import { aiUsageLabelsFor } from "./ai-usage-labels";
import type { ControlTransport } from "./transport";
import "../mcp-apps/update-reminder.css";

/**
 * Whether this instance shows the AI cost in Control. It is a Sidekick setting, SIDEKICK_MCP_APP_SHOW_AI_USAGE (off by
 * default), which the backend writes into the app document as `<meta name="sidekick-ai-usage" content="on">`. Without
 * the meta (the default, or a host such as the phone that does not declare it) the row is not drawn and nothing is read.
 */
export function aiUsageShown(doc: Document = document): boolean {
  return (
    doc.querySelector<HTMLMetaElement>('meta[name="sidekick-ai-usage"]')
      ?.content === "on"
  );
}

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
