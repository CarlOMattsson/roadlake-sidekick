/**
 * Runtime checks against the shapes generated from the tool contract (`tool-shapes.generated.ts`).
 * A shape is the outputSchema of a tool reduced to what a check can use: types, properties, required
 * keys, items, unions and constants. This file is the only hand-written matcher; the shapes
 * themselves are generated, so a retyped field in the contract changes what a guard accepts.
 *
 * Extra keys are allowed (an older app may meet a newer server). An enum is checked as the type of
 * its values, so a value added later by the server is still accepted.
 */

/** One reduced schema node, as `scripts/tool-shapes.mjs` writes it. */
export type Shape = {
  type?: "string" | "number" | "boolean" | "null" | "array" | "object";
  const?: unknown;
  items?: Shape;
  properties?: Record<string, Shape>;
  required?: string[];
  additionalProperties?: Shape;
  anyOf?: Shape[];
};

/** Whether a value is an object that is not an array and not null. */
export function isPlainObject(
  value: unknown,
): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Whether `value` fits `shape`. In an object the contract's `required` keys must be present;
 * a key that is present (not undefined) must fit its property. An empty shape matches anything.
 */
export function matchesShape(shape: Shape, value: unknown): boolean {
  if (shape.anyOf)
    return shape.anyOf.some((member) => matchesShape(member, value));
  if ("const" in shape) return value === shape.const;
  switch (shape.type) {
    case undefined:
      return true;
    case "string":
    case "number":
    case "boolean":
      return typeof value === shape.type;
    case "null":
      return value === null;
    case "array": {
      const { items } = shape;
      return (
        Array.isArray(value) &&
        (items === undefined ||
          value.every((item) => matchesShape(items, item)))
      );
    }
    case "object":
      return isPlainObject(value) && objectMatches(shape, value);
  }
}

function objectMatches(shape: Shape, value: Record<string, unknown>): boolean {
  const properties = shape.properties ?? {};
  const required = shape.required ?? [];
  if (required.some((key) => value[key] === undefined)) return false;
  for (const [key, propertyShape] of Object.entries(properties)) {
    const present = value[key];
    if (present !== undefined && !matchesShape(propertyShape, present))
      return false;
  }
  const { additionalProperties } = shape;
  if (additionalProperties === undefined) return true;
  return Object.entries(value).every(
    ([key, entry]) =>
      key in properties || matchesShape(additionalProperties, entry),
  );
}

/**
 * The shape at a path below `shape`: a property name steps into an object, "[]" into the items of an
 * array. A nullable member (anyOf with a null) is looked through. Throws when the path does not exist,
 * so a contract that drops a field fails when the module loads, not when a user opens the app.
 */
export function shapeAt(shape: Shape, ...path: string[]): Shape {
  let current = shape;
  for (const step of path) {
    const node = withoutNull(current);
    const next = step === "[]" ? node.items : node.properties?.[step];
    if (!next) throw new Error(`Shape has no "${step}" at ${path.join(".")}`);
    current = next;
  }
  return current;
}

function withoutNull(shape: Shape): Shape {
  if (!shape.anyOf) return shape;
  const members = shape.anyOf.filter((member) => member.type !== "null");
  return members.length === 1 && members[0] ? members[0] : shape;
}

/**
 * A guard for an object `shape` that a view reads as `T`. The `required` keys (the fields the view
 * cannot work without, which may be fewer than the contract's) must be present and fit the shape; every
 * other key of the shape is checked when present. Throws when a required key is
 * not in the shape, which means the contract no longer has the field.
 */
export function recordGuard<T>(
  shape: Shape,
  required: readonly (keyof T & string)[],
): (value: unknown) => value is T {
  const properties = withoutNull(shape).properties ?? {};
  for (const key of required) {
    if (!(key in properties)) throw new Error(`Shape has no property "${key}"`);
  }
  const effective: Shape = {
    ...withoutNull(shape),
    required: [...required],
  };
  return (value: unknown): value is T => matchesShape(effective, value);
}
