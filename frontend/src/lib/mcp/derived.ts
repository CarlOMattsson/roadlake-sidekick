/**
 * Helpers for the transport types that are derived from the generated tool contract
 * (`tool-results.generated.ts`). A transport type names a part of `ToolResults` or `ToolInputs`
 * instead of restating it, so a backend change that renames, retypes or drops a field breaks
 * `npm run typecheck` where the app reads it.
 *
 * Types only: the file has no runtime code and is erased from the bundle.
 */

/** The element type of an array. */
export type Item<T> = T extends ReadonlyArray<infer U> ? U : never;

/**
 * The server type with the named keys optional. The app may meet a server older than itself (the
 * companion app updates on its own schedule), so a field the server added later is read as optional.
 * The key names still come from the server type: renaming one there is a compile error here.
 */
export type WithOptional<T, K extends keyof T> = Omit<T, K> & {
  [P in K]?: T[P];
};
