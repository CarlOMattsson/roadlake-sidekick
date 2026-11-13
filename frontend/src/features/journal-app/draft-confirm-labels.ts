/**
 * The sentences that confirm saving a draft as an entry, before and after: "Det här skapar en anteckning med 6
 * kopplingar. 8 uppgifter skapas." and "Anteckningen sparades. 8 uppgifter skapades." A count of zero is left out, so no
 * sentence names "0 uppgifter". Spread into journalEn and journalSv (labels.ts).
 */

/** The parts that are not left out, as one text. */
function sentences(...parts: (string | false)[]): string {
  return parts.filter(Boolean).join(" ");
}

const tasks = (n: number) => `${n} ${n === 1 ? "task" : "tasks"}`;
const uppgifter = (n: number) => `${n} ${n === 1 ? "uppgift" : "uppgifter"}`;

export const draftConfirmEn = {
  finalizeConfirm: (links: number, created: number, updated: number) =>
    sentences(
      links > 0
        ? `This saves an entry with ${links} ${links === 1 ? "link" : "links"}.`
        : "This saves an entry.",
      created > 0 && `It creates ${tasks(created)}.`,
      updated > 0 && `It updates ${tasks(updated)}.`,
    ),
  entrySaved: (created: number, updated: number) =>
    sentences(
      "Entry saved.",
      created > 0 && `${tasks(created)} created.`,
      updated > 0 && `${tasks(updated)} updated.`,
    ),
};

export const draftConfirmSv: typeof draftConfirmEn = {
  finalizeConfirm: (links, created, updated) =>
    sentences(
      links > 0
        ? `Det här skapar en anteckning med ${links} ${links === 1 ? "koppling" : "kopplingar"}.`
        : "Det här skapar en anteckning.",
      created > 0 && `${uppgifter(created)} skapas.`,
      updated > 0 && `${uppgifter(updated)} uppdateras.`,
    ),
  entrySaved: (created, updated) =>
    sentences(
      "Anteckningen sparades.",
      created > 0 && `${uppgifter(created)} skapades.`,
      updated > 0 && `${uppgifter(updated)} uppdaterades.`,
    ),
};
