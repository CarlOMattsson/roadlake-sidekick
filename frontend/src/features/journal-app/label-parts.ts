import { draftConfirmEn, draftConfirmSv } from "./draft-confirm-labels";
import { taggedEn, taggedSv } from "./tagged-labels";
import { taggedReachEn, taggedReachSv } from "./tagged-reach-labels";

/** The sentence groups kept in their own files, spread into journalEn and journalSv (labels.ts). */
export const partsEn = { ...draftConfirmEn, ...taggedEn, ...taggedReachEn };
export const partsSv = { ...draftConfirmSv, ...taggedSv, ...taggedReachSv };
