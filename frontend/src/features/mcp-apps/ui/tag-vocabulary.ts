import { useCallback, useMemo, useState } from "react";
import type { Item } from "../../../lib/mcp/derived";
import type { ToolResults } from "../../../lib/mcp/tool-results.generated";
import { useRead } from "./use-read";

/** One entry of the owner's tag vocabulary as list_tags returns it (TagRecord), with its use per kind. */
export type TagRecord = Item<ToolResults["list_tags"]["tags"]>;
/** The record kinds a tag marks, as list_tags counts them. */
export type TagKind = keyof TagRecord["usage"];
/** A tag a filter or a suggestion offers: the slug a record carries, the label it reads, and its use. */
export type TagOption = { slug: string; label: string; count: number };
/** Reads the first page of the vocabulary; absent when the host has no list_tags. */
export type ReadTags = () => Promise<TagRecord[]>;

/** The server's limits (sidekick.work.domain.planning): slug length, tags per record, tags per filter. */
export const TAG_MAX_LENGTH = 60;
export const TAGS_PER_RECORD = 10;
export const TAGS_PER_FILTER = 5;

/**
 * The slug the server stores for typed text: NFC, trimmed, case-folded, inner whitespace as one "-". The app
 * uses it to find a duplicate before a write; the server normalises again and is the authority.
 */
export function tagSlugOf(value: string): string {
  return value
    .normalize("NFC")
    .trim()
    .toLocaleLowerCase()
    .split(/\s+/u)
    .filter(Boolean)
    .join("-")
    .replace(/-{2,}/gu, "-")
    .replace(/^-+|-+$/gu, "");
}

// One read per transport, shared by every view that shows the same vocabulary; a tag write forgets it.
const cache = new WeakMap<ReadTags, Promise<TagRecord[]>>();

/** Makes the next `useTagVocabulary` read list_tags again, after a write that may have made a new tag. */
export function forgetTagVocabulary(read: ReadTags | undefined) {
  if (read) cache.delete(read);
}

/**
 * The owner's tag vocabulary for one kind of record, or for several counted together (a list of Tasks and
 * Projects). `options` are the tags in use on those kinds (for a filter); `suggestions` are all tags (for
 * adding one). Both come in the server's order; `sortTagOptions` puts them in reading order for a locale. A failed or missing read leaves both empty: the view then shows no filter and adds tags
 * by typing only.
 */
export function useTagVocabulary(
  read: ReadTags | undefined,
  kind: TagKind | readonly TagKind[],
) {
  const kinds: readonly TagKind[] = typeof kind === "string" ? [kind] : kind;
  const [round, setRound] = useState(0);
  // A failed read is kept too: a host that cannot answer is not asked again by every view. A tag write
  // (`refresh`) asks again.
  const readTags = useMemo(
    () =>
      read
        ? () => {
            let pending = cache.get(read);
            if (!pending) {
              pending = read();
              cache.set(read, pending);
            }
            return pending;
          }
        : undefined,
    [read],
  );
  const [found] = useRead(readTags, round);
  const tags =
    found.phase === "ready"
      ? found.value.filter((tag) => !tag.archived_at)
      : [];
  const refresh = useCallback(() => {
    forgetTagVocabulary(read);
    setRound((n) => n + 1);
  }, [read]);
  const option = (tag: TagRecord): TagOption => ({
    slug: tag.slug,
    label: tag.label,
    count: kinds.reduce((sum, each) => sum + (tag.usage[each] ?? 0), 0),
  });
  const options = tags.map(option).filter((tag) => tag.count > 0);
  const suggestions = tags.map(option);
  return { options, suggestions, refresh };
}

/** The label of a slug as the vocabulary names it; the slug itself when the vocabulary does not know it. */
export function tagLabelOf(slug: string, known: readonly TagOption[]): string {
  return known.find((tag) => tag.slug === slug)?.label ?? slug;
}

/** The options most used first, ties in the collation of the locale (Swedish puts å, ä, ö last). */
export function sortTagOptions(
  options: readonly TagOption[],
  locale: string,
): TagOption[] {
  const collator = new Intl.Collator(
    locale.startsWith("en") ? "en-GB" : "sv-SE",
  );
  return [...options].sort(
    (a, b) => b.count - a.count || collator.compare(a.label, b.label),
  );
}
