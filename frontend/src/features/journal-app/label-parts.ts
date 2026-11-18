import { draftConfirmEn, draftConfirmSv } from "./draft-confirm-labels";
import { memoryEn, memorySv } from "./memory-labels";
import { queuedEn, queuedSv } from "./queued-labels";
import { taggedEn, taggedSv } from "./tagged-labels";
import { taggedReachEn, taggedReachSv } from "./tagged-reach-labels";

/** The sentence groups kept in their own files, spread into journalEn and journalSv (labels.ts). */
export const partsEn = {
  ...draftConfirmEn,
  ...taggedEn,
  ...taggedReachEn,
  ...queuedEn,
  ...memoryEn,
};
export const partsSv = {
  ...draftConfirmSv,
  ...taggedSv,
  ...taggedReachSv,
  ...queuedSv,
  ...memorySv,
};
