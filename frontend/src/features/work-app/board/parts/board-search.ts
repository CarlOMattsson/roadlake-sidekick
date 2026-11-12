import { createContext } from "react";

/**
 * The text of the tab row's search (designsystem §3 "Skapa-rad": search sits behind the search icon in all three
 * tabs). The fullscreen shell provides it around the Status tab; both layouts show only the Tasks whose title
 * holds it, and the board reads the server with it (`q`), so a hit on a page not yet loaded is found. Absent, the
 * board shows everything.
 */
export const BoardQuery = createContext("");
/** Empties the Status tab's search, given by the fullscreen shell beside BoardQuery. Absent, a search with no hit has no "Rensa sökningen" button. */
export const BoardClearSearch = createContext<(() => void) | undefined>(
  undefined,
);
