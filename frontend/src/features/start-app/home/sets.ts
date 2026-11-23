/** Small immutable set updates shared by the home view's per-row state (a state setter needs a new set to rerender). */
export function withId(
  set: ReadonlySet<string>,
  id: string,
): ReadonlySet<string> {
  return new Set([...set, id]);
}

export function withoutId(
  set: ReadonlySet<string>,
  id: string,
): ReadonlySet<string> {
  if (!set.has(id)) return set;
  const next = new Set(set);
  next.delete(id);
  return next;
}
