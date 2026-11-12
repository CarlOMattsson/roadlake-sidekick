import type {
  JournalDraft,
  JournalDraftFields,
  JournalKeyPoint,
} from "../transport";

export const KEY_POINT_KINDS = [
  "fact",
  "reflection",
  "decision",
  "commitment",
  "question",
] as const satisfies readonly JournalKeyPoint["kind"][];
/** Whether a string is a key point kind the schema allows. */
export function isKeyPointKind(
  value: string,
): value is JournalKeyPoint["kind"] {
  return (KEY_POINT_KINDS as readonly string[]).includes(value);
}
export const TITLE_MAX = 200;
export const SUMMARY_MAX = 10_000;
export const KEY_POINT_MAX = 2000;
export const KEY_POINTS_MAX = 50;

/** Editable draft fields as the editor shows them; an empty summary means none. */
export type EditValues = {
  title: string;
  summary: string;
  keyPoints: JournalKeyPoint[];
};
export type EditState = { values: EditValues; base: EditValues };

export function valuesOf(
  draft: Pick<JournalDraft, "title" | "summary" | "key_points">,
): EditValues {
  return {
    title: draft.title,
    summary: draft.summary ?? "",
    keyPoints: draft.key_points.map((point) => ({ ...point })),
  };
}
function keyPointsSignature(points: JournalKeyPoint[]): string {
  return JSON.stringify(points.map((point) => [point.kind, point.text.trim()]));
}
/**
 * Only the fields that differ from what the owner last saw. update_journal_draft replaces all
 * fields, so the parent fills every unchanged field from the draft it holds.
 */
export function changedFields(state: EditState): Partial<JournalDraftFields> {
  const { values, base } = state;
  const changes: Partial<JournalDraftFields> = {};
  if (values.title.trim() !== base.title.trim())
    changes.title = values.title.trim();
  if (values.summary.trim() !== base.summary.trim())
    changes.summary = values.summary.trim() === "" ? null : values.summary;
  if (
    keyPointsSignature(values.keyPoints) !== keyPointsSignature(base.keyPoints)
  )
    changes.key_points = values.keyPoints.map((point) => ({
      kind: point.kind,
      text: point.text.trim(),
    }));
  return changes;
}
/** After a reload a field the owner changed keeps their value; the others follow the draft. */
export function follow(current: EditState, fresh: EditValues): EditState {
  const { values, base } = current;
  return {
    base: fresh,
    values: {
      title: values.title !== base.title ? values.title : fresh.title,
      summary: values.summary !== base.summary ? values.summary : fresh.summary,
      keyPoints:
        keyPointsSignature(values.keyPoints) !==
        keyPointsSignature(base.keyPoints)
          ? values.keyPoints
          : fresh.keyPoints,
    },
  };
}
export function mergeFields(
  draft: Pick<JournalDraft, "title" | "summary" | "key_points">,
  changes: Partial<JournalDraftFields>,
): JournalDraftFields {
  return {
    title: changes.title ?? draft.title,
    summary: "summary" in changes ? (changes.summary ?? null) : draft.summary,
    key_points: changes.key_points ?? draft.key_points,
  };
}

/** A key point of a kind the schema does not allow becomes a fact, and the owner is told. */
export function normalizeKeyPoints(draft: JournalDraft): {
  draft: JournalDraft;
  changed: boolean;
} {
  if (draft.key_points.every((point) => isKeyPointKind(point.kind)))
    return { draft, changed: false };
  return {
    changed: true,
    draft: {
      ...draft,
      key_points: draft.key_points.map((point) =>
        isKeyPointKind(point.kind) ? point : { ...point, kind: "fact" },
      ),
    },
  };
}
