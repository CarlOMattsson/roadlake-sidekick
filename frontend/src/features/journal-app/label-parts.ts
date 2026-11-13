import { draftConfirmEn, draftConfirmSv } from "./draft-confirm-labels";
import { taggedEn, taggedSv } from "./tagged-labels";

/** The sentence groups kept in their own files, spread into journalEn and journalSv (labels.ts). */
export const partsEn = { ...draftConfirmEn, ...taggedEn };
export const partsSv = { ...draftConfirmSv, ...taggedSv };
