import { draftConfirmEn, draftConfirmSv } from "./draft-confirm-labels";
import { entryReadEn, entryReadSv } from "./entry-read-labels";
import { glanceEn, glanceSv } from "./glance-labels";
import { memoryEn, memorySv } from "./memory-labels";
import { queuedEn, queuedSv } from "./queued-labels";
import { receiptEn, receiptSv } from "./receipt-labels";
import { taggedEn, taggedSv } from "./tagged-labels";
import { taggedReachEn, taggedReachSv } from "./tagged-reach-labels";
import { weekEn, weekSv } from "./week-labels";

/** The sentence groups kept in their own files, spread into journalEn and journalSv (labels.ts). */
export const partsEn = {
  ...draftConfirmEn,
  ...entryReadEn,
  ...taggedEn,
  ...taggedReachEn,
  ...queuedEn,
  ...memoryEn,
  ...weekEn,
  ...glanceEn,
  ...receiptEn,
};
export const partsSv = {
  ...draftConfirmSv,
  ...entryReadSv,
  ...taggedSv,
  ...taggedReachSv,
  ...queuedSv,
  ...memorySv,
  ...weekSv,
  ...glanceSv,
  ...receiptSv,
};
