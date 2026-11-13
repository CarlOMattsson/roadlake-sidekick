import { createContext } from "react";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { tagLabelsFor } from "../../mcp-apps/ui/tag-labels";
import {
  tagLabelOf,
  useTagVocabulary,
  type TagKind,
  type TagOption,
} from "../../mcp-apps/ui/tag-vocabulary";
import { TagFilter } from "../../mcp-apps/ui/tags";
import type { WorkFilters, WorkTransport } from "../transport/transport";

/**
 * The tag vocabulary of the list around a row (Agenda, Status, a Project's Tasks), for the labels of the row's
 * tags. Without a provider a row reads each tag as its slug.
 */
export const KnownTags = createContext<readonly TagOption[]>([]);

/** The owner's tags for Work records of `kind`, read once per transport and only where the host has list_tags. */
export function useWorkTags(
  transport: WorkTransport,
  kind: TagKind | readonly TagKind[],
) {
  const offers = useToolSupport(transport);
  return useTagVocabulary(
    offers("list_tags") ? transport.listTags : undefined,
    kind,
  );
}

/** The tags an Agenda or Status read is narrowed to (a saved view may name them too). */
export function filterTags(filters: WorkFilters): string[] {
  const tags = filters.tags;
  if (Array.isArray(tags)) return tags;
  return typeof tags === "string" && tags ? [tags] : [];
}

/** The filters narrowed to these tags, every one required (tag_match "all"); no tag drops the tag filter. */
export function withFilterTags(
  filters: WorkFilters,
  tags: string[],
): WorkFilters {
  const rest = Object.fromEntries(
    Object.entries(filters).filter(
      ([key]) => key !== "tags" && key !== "tag_match",
    ),
  );
  return tags.length > 0 ? { ...rest, tags, tag_match: "all" } : rest;
}

/**
 * The tag filter row of the Agenda and Status: the tags in use on Tasks and Projects as toggle chips, and once the
 * list answers for the chosen tags, a status line that says what it is narrowed to. No tag in use draws nothing.
 */
export function WorkTagFilter({
  options,
  selected,
  settled,
  onChange,
  locale,
}: {
  options: readonly TagOption[];
  selected: string[];
  /** True once the shown page was read with `selected`. */
  settled: boolean;
  onChange: (tags: string[]) => void;
  locale: string;
}) {
  return (
    <>
      <TagFilter
        options={options}
        selected={selected}
        onChange={onChange}
        locale={locale}
      />
      {settled && selected.length > 0 && (
        <p role="status" className="work-visually-hidden">
          {tagLabelsFor(locale).filtered(
            selected.map((slug) => tagLabelOf(slug, options)),
          )}
        </p>
      )}
    </>
  );
}
