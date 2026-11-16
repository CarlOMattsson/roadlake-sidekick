/**
 * The texts of the AI cost row in Control (ai-usage-row.tsx), shown only where the instance switched it on. Amounts
 * arrive already written ("0,42 USD"). Swedish first; the English key set is the same.
 */
export type AiUsageLabels = {
  /** The row's name, before what the month cost. */
  title: string;
  /** What the month's AI Steps cost of the month's cap: "0,42 USD av 5,00 USD". */
  spent: (spent: string, cap: string) => string;
  /** The AI Steps started today of the day's cap. */
  starts: (count: number, cap: number) => string;
  /** What Claude Code itself estimated it spent, said apart from the server's own count. */
  estimate: (amount: string) => string;
  loading: string;
  failed: string;
  retry: string;
};

export const aiUsageSv: AiUsageLabels = {
  title: "AI denna månad",
  spent: (spent, cap) => `${spent} av ${cap}`,
  starts: (count, cap) => `${count} av ${cap} starter i dag`,
  estimate: (amount) => `${amount} uppskattat av Claude Code`,
  loading: "Läser AI-kostnaden …",
  failed: "AI-kostnaden gick inte att läsa.",
  retry: "Försök igen",
};

export const aiUsageEn: AiUsageLabels = {
  title: "AI this month",
  spent: (spent, cap) => `${spent} of ${cap}`,
  starts: (count, cap) => `${count} of ${cap} starts today`,
  estimate: (amount) => `${amount} estimated by Claude Code`,
  loading: "Reading the AI cost …",
  failed: "The AI cost could not be read.",
  retry: "Try again",
};

export function aiUsageLabelsFor(locale: "sv" | "en"): AiUsageLabels {
  return locale === "sv" ? aiUsageSv : aiUsageEn;
}
