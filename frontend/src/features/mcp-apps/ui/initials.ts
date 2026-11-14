/**
 * Up to two letters: the first letter of the first and the last word, or the first two letters of
 * a single word. Only letters and digits count, so punctuation never becomes an initial. Text in parentheses is a note,
 * not a name: "Kerstin Åberg (club)" is "KÅ", unless the name is nothing else.
 */
export function initialsOf(name: string): string {
  const bare = name.replace(/\([^)]*\)?/gu, " ").trim();
  const words = (bare || name)
    .split(/\s+/u)
    .map((word) =>
      Array.from(word)
        .filter((ch) => /[\p{L}\p{N}]/u.test(ch))
        .join(""),
    )
    .filter((word) => word !== "");
  if (words.length === 0) return "?";
  const head = Array.from(words[0] ?? "");
  const tail = Array.from(words[words.length - 1] ?? "");
  const letters =
    words.length === 1 ? head.slice(0, 2) : [head[0] ?? "", tail[0] ?? ""];
  return letters.join("").toLocaleUpperCase();
}
