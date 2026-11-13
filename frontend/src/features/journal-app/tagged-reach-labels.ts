/**
 * What the tagged list says about how far back it has read: the empty list names the years read, and the end of the
 * list names the years that held nothing, so neither claims more than was read. Spread into journalEn and journalSv
 * (label-parts.ts).
 */
export const taggedReachEn = {
  /** Nothing found in the `years` windows read so far. */
  taggedNone: (tags: number, years: number): string =>
    `No entry from ${years === 1 ? "the last 12 months" : `the last ${years} years`} has ${
      tags === 1 ? "this tag" : "all of these tags"
    }.`,
  /** The list stops after two empty windows in a row; older entries are not read, so it does not say there are none. */
  taggedStopped: (tags: number): string =>
    `No more entries with ${
      tags === 1 ? "this tag" : "all of these tags"
    } in the two years before. Nothing further back has been read.`,
};

export const taggedReachSv: typeof taggedReachEn = {
  taggedNone: (tags, years) =>
    `Ingen anteckning ${years === 1 ? "de senaste 12 månaderna" : `de senaste ${years} åren`} har ${
      tags === 1 ? "den här taggen" : "alla de här taggarna"
    }.`,
  taggedStopped: (tags) =>
    `Inga fler anteckningar med ${
      tags === 1 ? "den här taggen" : "alla de här taggarna"
    } de två föregående åren. Längre bakåt har inte lästs.`,
};
