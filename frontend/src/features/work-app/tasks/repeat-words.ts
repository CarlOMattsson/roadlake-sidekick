import type { RecurrenceRecord } from "../../../lib/mcp/tool-results.generated";

/** What the wording reads of a rule; a rule a caller builds by hand may leave the optional parts out. */
export type RuleWords = Pick<RecurrenceRecord, "frequency" | "interval"> &
  Partial<Pick<RecurrenceRecord, "weekdays" | "day_of_month" | "last_weekday">>;

/** The weekdays by the backend's numbers (Monday is 0): the short names on the buttons and in lists, and the full ones. */
export type WeekdayNames = {
  short: readonly string[];
  full: readonly string[];
};

export const weekdayNamesSv: WeekdayNames = {
  short: ["mån", "tis", "ons", "tors", "fre", "lör", "sön"],
  full: ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"],
};

export const weekdayNamesEn: WeekdayNames = {
  short: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
  full: [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
  ],
};

const sorted = (days: readonly number[] | undefined) =>
  [...(days ?? [])].sort((a, b) => a - b);

/** "mån", "mån och tors", "mån, ons och fre". */
function listWords(names: string[], and: string): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} ${and} ${names[names.length - 1]}`;
}

/** Swedish ordinals: 1:a and 2:a (but 11:e, 12:e), every other number :e. */
function ordinalSv(n: number): string {
  const tail = n % 100;
  const suffix =
    (n % 10 === 1 || n % 10 === 2) && tail !== 11 && tail !== 12 ? "a" : "e";
  return `${n}:${suffix}`;
}

/** English ordinals: 1st, 2nd, 3rd, 4th, 11th, 21st. */
function ordinalEn(n: number): string {
  const tail = n % 100;
  if (tail >= 11 && tail <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

/** "varje vecka", "varannan vecka", "var 3:e vecka". */
function periodSv(rule: RuleWords): string {
  const unit = {
    daily: "dag",
    weekly: "vecka",
    monthly: "månad",
    yearly: "år",
  }[rule.frequency];
  if (rule.interval <= 1) return `varje ${unit}`;
  if (rule.interval === 2)
    return rule.frequency === "yearly" ? "vartannat år" : `varannan ${unit}`;
  return `var ${ordinalSv(rule.interval)} ${unit}`;
}

/**
 * A rule in Swedish words: "varje vecka", "varje måndag", "varje mån och tors", "varannan vecka",
 * "varje månad den 15:e", "sista vardagen i månaden".
 */
export function everySv(rule: RuleWords): string {
  const days = sorted(rule.weekdays);
  if (rule.frequency === "weekly" && days.length > 0) {
    const names = days.map((day) => weekdayNamesSv.short[day] ?? "");
    if (rule.interval <= 1) {
      if (days.length === 7) return "varje dag";
      const [only] = days;
      return days.length === 1 && only !== undefined
        ? `varje ${weekdayNamesSv.full[only]}`
        : `varje ${listWords(names, "och")}`;
    }
    return `${periodSv(rule)}, ${listWords(names, "och")}`;
  }
  if (rule.frequency === "monthly" && rule.last_weekday)
    return rule.interval <= 1
      ? "sista vardagen i månaden"
      : `sista vardagen ${periodSv(rule)}`;
  if (rule.frequency === "monthly" && rule.day_of_month != null)
    return `${periodSv(rule)} den ${ordinalSv(rule.day_of_month)}`;
  return periodSv(rule);
}

/** "weekly", "every other week", "every 3 weeks". */
function periodEn(rule: RuleWords): string {
  if (rule.interval <= 1)
    return {
      daily: "daily",
      weekly: "weekly",
      monthly: "monthly",
      yearly: "yearly",
    }[rule.frequency];
  const unit = {
    daily: "day",
    weekly: "week",
    monthly: "month",
    yearly: "year",
  }[rule.frequency];
  return rule.interval === 2
    ? `every other ${unit}`
    : `every ${rule.interval} ${unit}s`;
}

/**
 * A rule in English words: "weekly", "every Monday", "every Mon and Thu", "every other week",
 * "monthly on the 15th", "on the last weekday of the month".
 */
export function everyEn(rule: RuleWords): string {
  const days = sorted(rule.weekdays);
  if (rule.frequency === "weekly" && days.length > 0) {
    const names = days.map((day) => weekdayNamesEn.short[day] ?? "");
    if (rule.interval <= 1) {
      if (days.length === 7) return "daily";
      const [only] = days;
      return days.length === 1 && only !== undefined
        ? `every ${weekdayNamesEn.full[only]}`
        : `every ${listWords(names, "and")}`;
    }
    return `${periodEn(rule)}, ${listWords(names, "and")}`;
  }
  if (rule.frequency === "monthly" && rule.last_weekday)
    return rule.interval <= 1
      ? "on the last weekday of the month"
      : `on the last weekday of ${periodEn(rule)}`;
  if (rule.frequency === "monthly" && rule.day_of_month != null)
    return `${periodEn(rule)} on the ${ordinalEn(rule.day_of_month)}`;
  return periodEn(rule);
}
