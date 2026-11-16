/**
 * Whether this instance shows what AI costs: Control's month row and the month's sum on a Task's AI plan. It is a
 * Sidekick setting, SIDEKICK_MCP_APP_SHOW_AI_USAGE (off by default), which the backend writes into the app document as
 * `<meta name="sidekick-ai-usage" content="on">`. Without the meta (the default, or a host such as the phone that does
 * not declare it) no AI cost of the month is drawn.
 */
export function aiUsageShown(doc: Document = document): boolean {
  return (
    doc.querySelector<HTMLMetaElement>('meta[name="sidekick-ai-usage"]')
      ?.content === "on"
  );
}
