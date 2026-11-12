import { useContext, useEffect, useEffectEvent } from "react";
import { foldSearchText } from "../work-items";
import { BoardClearSearch, BoardQuery } from "./board-search";
import type { BoardCore } from "./use-board-core";

/** How long the search text rests before the board is read with it, so a word typed fast makes one read. */
const SEARCH_DELAY_MS = 300;
/** get_work_board takes a `q` of up to 200 characters. */
const SEARCH_MAX = 200;

/**
 * The tab row's search as the board sees it: the text it filters by and, after a rest, the server read that
 * carries it as `q`. A changed search text rests for a moment, then the board is read from its first page with
 * the text as `q` (an emptied search reads without it): the cards of a page not loaded yet are found too, and
 * "Visa fler" goes on from the new first page. The text at mount is not a request.
 */
export function useBoardSearch({ latest, commit, reload }: BoardCore) {
  const query = useContext(BoardQuery);
  const clearSearch = useContext(BoardClearSearch);
  const searchText = query.trim().slice(0, SEARCH_MAX);
  const needle = foldSearchText(searchText);
  const startSearch = useEffectEvent(() => {
    if (searchText === (latest.current.search ?? "")) return;
    commit({ ...latest.current, search: searchText || undefined });
    reload();
  });
  useEffect(() => {
    const timer = setTimeout(startSearch, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [searchText]);
  return { query, clearSearch, searchText, needle };
}
