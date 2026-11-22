import type { DecisionTrust } from "./decision-card";
import { decisionLabelsFor } from "./decision-labels";

/**
 * The closed codes a suggestion carries from the server, and how a card reads them. The server never sends a sentence
 * of its own about a check: the deterministic screen sets flags, the independent checker returns a verdict, a
 * confidence and reason codes, and an approval that fails gives an apply error. Every code is a word list here (sv and
 * en in `decision-labels.ts`), so nothing a mail or a model wrote can reach the trust note.
 *
 * The lists follow the server's (a new code is a new entry, never a new meaning for an old one). A code the app does not
 * know yet still counts: an unknown flag makes the card unsure, an unknown reason adds no sentence.
 */
export const SCREENING_FLAGS = [
  "contains_link",
  "payment_related",
  "contact_detail_unverified",
  "homoglyph_domain",
  "instruction_like_text",
  "duplicate_existing",
  "large_batch",
] as const;
export type ScreeningFlag = (typeof SCREENING_FLAGS)[number];

/** The checker's reason codes; `other` has no sentence of its own. */
export const CHECK_REASONS = [
  "out_of_scope",
  "destructive_intent",
  "instruction_like_text",
  "mismatch_with_source",
  "payment_related",
  "contact_detail_unverified",
  "duplicate_likely",
  "other",
] as const;
export type CheckReason = (typeof CHECK_REASONS)[number];

export const APPLY_ERRORS = [
  "project_gone",
  "conflict",
  "invalid_payload",
  "not_permitted",
] as const;
export type ApplyError = (typeof APPLY_ERRORS)[number];

/**
 * The flags that make a card suspicious on their own, without a checker: money, an address that imitates another, and
 * text that talks to an AI. They are the ways an injected mail turns into harm. The others (a link, an address on
 * another domain, a likely duplicate, a large batch) make it unsure: worth a second look, still the owner's to approve.
 */
export const SUSPICIOUS_FLAGS: ReadonlySet<string> = new Set<ScreeningFlag>([
  "payment_related",
  "homoglyph_domain",
  "instruction_like_text",
]);

/** A suggestion's check as the server keeps it (snake_case, as the tools send it). */
export type SuggestionCheck = {
  /** `queued` and `failed` read as not checked: no confidence is shown. A verdict left from an earlier check still warns. */
  check_state: "off" | "queued" | "checked" | "failed";
  verdict?: "ok" | "uncertain" | "suspicious" | null;
  /** 0–100, only from the independent checker. */
  confidence?: number | null;
  screening_flags?: readonly string[];
  /** The latest check's reason codes. */
  reason_codes?: readonly string[];
};

/**
 * The card's trust from the server's check. Suspicious when the checker said so or a suspicious flag is set; unsure
 * when the checker was uncertain or any other flag is set; otherwise checked with its confidence, or not checked.
 * A warning verdict counts whatever the check state (an earlier check's verdict left on a card still warns); a
 * confidence is only shown for a check that is done. The sentences are the flags', the suspicious ones first, then the
 * checker's, each once: `reason` is the first (what an inline card has room for), `reasons` all of them when there is
 * more than one (what the detail shows).
 */
export function decisionTrust(
  check: SuggestionCheck,
  locale: string,
): DecisionTrust {
  const t = decisionLabelsFor(locale);
  const flags = check.screening_flags ?? [];
  const checked = check.check_state === "checked";
  const verdict = check.verdict ?? null;
  const suspicious =
    verdict === "suspicious" ||
    flags.some((flag) => SUSPICIOUS_FLAGS.has(flag));
  const unsure = !suspicious && (verdict === "uncertain" || flags.length > 0);

  if (!suspicious && !unsure) {
    if (!checked || verdict !== "ok") return { state: "off" };
    return check.confidence == null
      ? { state: "ok" }
      : { state: "ok", confidence: check.confidence };
  }

  const ordered = [
    ...flags.filter((flag) => SUSPICIOUS_FLAGS.has(flag)),
    ...flags.filter((flag) => !SUSPICIOUS_FLAGS.has(flag)),
  ];
  const sentences = [
    ...ordered.map((flag) => sentenceOf(t.flags, flag)),
    ...(check.reason_codes ?? []).map((code) =>
      sentenceOf(t.checkReasons, code),
    ),
  ].filter((sentence): sentence is string => sentence !== null);
  const state = suspicious ? "suspicious" : "unsure";
  const unique = [...new Set(sentences)];
  if (unique.length === 0) return { state };
  return unique.length === 1
    ? { state, reason: unique[0] }
    : { state, reason: unique[0], reasons: unique };
}

/** A code's own sentence; an unknown code (or a name like "constructor") has none. */
function sentenceOf(
  sentences: Partial<Record<ScreeningFlag | CheckReason, string>>,
  code: string,
): string | null {
  return Object.hasOwn(sentences, code)
    ? (sentences[code as ScreeningFlag | CheckReason] ?? null)
    : null;
}
