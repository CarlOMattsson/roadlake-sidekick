/**
 * The sentences about keeping one entry out of Claude's memory: the two menu items, the marker on the entry and its row,
 * the line after each choice and the failures. Spread into journalEn and journalSv (label-parts.ts).
 */
export const memoryEn = {
  entryKeepOutOfMemory: "Keep out of memory",
  entryBringBackIntoMemory: "Bring back into memory",
  entryOutOfMemory: "Kept out of memory",
  entryKeptOutOfMemory:
    "The entry is kept out of memory. What Claude already remembered about it is forgotten within a few minutes.",
  entryBackInMemory: "The entry is part of the memory again.",
  entryMemoryFailed: "Couldn’t change the memory setting of the entry.",
};
export const memorySv: typeof memoryEn = {
  entryKeepOutOfMemory: "Håll utanför minnet",
  entryBringBackIntoMemory: "Ta med i minnet igen",
  entryOutOfMemory: "Utanför minnet",
  entryKeptOutOfMemory:
    "Anteckningen hålls utanför minnet. Det Claude redan mindes om den glöms inom några minuter.",
  entryBackInMemory: "Anteckningen är med i minnet igen.",
  entryMemoryFailed: "Det gick inte att ändra minnesvalet för anteckningen.",
};
