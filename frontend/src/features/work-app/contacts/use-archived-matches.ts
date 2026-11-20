import { useEffect, useState } from "react";
import type { WorkTransport } from "../transport/transport";

/**
 * How many archived Contacts match a search that found no live one, so the empty list can offer to show them. Reads
 * only while `enabled` (a search with no hit, "Show archived" off) and answers for the search it was read for: an
 * answer to an older search is never shown. A read that fails says nothing (undefined), as the offer is a convenience.
 */
export function useArchivedMatches(
  transport: WorkTransport,
  query: string,
  enabled: boolean,
): number | undefined {
  const [found, setFound] = useState<{ query: string; count: number }>();
  useEffect(() => {
    if (!enabled || !query) return;
    let current = true;
    Promise.resolve()
      .then(() => transport.listContacts({ q: query, includeArchived: true }))
      .then((page) => {
        if (current)
          setFound({
            query,
            count: page.items.filter((contact) => contact.archived).length,
          });
      })
      .catch(() => {
        if (current) setFound(undefined);
      });
    return () => {
      current = false;
    };
  }, [transport, query, enabled]);
  return enabled && found?.query === query && found.count > 0
    ? found.count
    : undefined;
}
