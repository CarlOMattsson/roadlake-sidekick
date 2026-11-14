import { describe, expect, it } from "vitest";
import {
  matchesShape,
  recordGuard,
  shapeAt,
  type Shape,
} from "@/lib/mcp/shape";
import { schemaToShape } from "../../../scripts/tool-shapes.mjs";
import { getTaskResultShape } from "@/lib/mcp/tool-shapes.generated";

const row: Shape = {
  type: "object",
  properties: {
    id: { type: "string" },
    due: { anyOf: [{ type: "string" }, { type: "null" }] },
    tags: { type: "array", items: { type: "string" } },
    kind: { const: "task" },
  },
  required: ["id"],
};

describe("matchesShape", () => {
  it("accepts a fitting object and allows extra keys", () => {
    expect(matchesShape(row, { id: "a", extra: 1 })).toBe(true);
    expect(
      matchesShape(row, { id: "a", due: null, tags: ["x"], kind: "task" }),
    ).toBe(true);
  });

  it("rejects a missing required key, a wrong type and a non-object", () => {
    expect(matchesShape(row, {})).toBe(false);
    expect(matchesShape(row, { id: 3 })).toBe(false);
    expect(matchesShape(row, { id: "a", due: 5 })).toBe(false);
    expect(matchesShape(row, { id: "a", tags: ["x", 2] })).toBe(false);
    expect(matchesShape(row, { id: "a", kind: "other" })).toBe(false);
    expect(matchesShape(row, null)).toBe(false);
    expect(matchesShape(row, [])).toBe(false);
  });
});

describe("recordGuard and shapeAt", () => {
  it("require only the named keys but still type-check the others", () => {
    const guard = recordGuard<{ id: string; due?: string | null }>(row, ["id"]);
    expect(guard({ id: "a" })).toBe(true);
    expect(guard({ id: "a", due: 1 })).toBe(false);
    expect(guard({ due: null })).toBe(false);
  });

  it("throw when the contract no longer has a field", () => {
    expect(() => recordGuard<{ gone: string }>(row, ["gone"])).toThrow(/gone/);
    expect(() => shapeAt(row, "gone")).toThrow(/gone/);
  });

  it("step into array items and through a nullable member", () => {
    const nested: Shape = { anyOf: [row, { type: "null" }] };
    expect(shapeAt({ type: "array", items: nested }, "[]", "id")).toEqual({
      type: "string",
    });
  });

  it("reject a get_task Task whose version is not a number", () => {
    const guard = recordGuard<{ id: string; version: number }>(
      shapeAt(getTaskResultShape, "task"),
      ["id", "version"],
    );
    expect(guard({ id: "a", version: 1 })).toBe(true);
    expect(guard({ id: "a", version: "1" })).toBe(false);
  });
});

describe("schemaToShape", () => {
  it("reduces enums to their value type and keeps const and nullable unions", () => {
    expect(schemaToShape({ type: "string", enum: ["a", "b"] })).toEqual({
      type: "string",
    });
    expect(schemaToShape({ const: "x", type: "string" })).toEqual({
      const: "x",
    });
    expect(
      schemaToShape({ anyOf: [{ type: "integer" }, { type: "null" }] }),
    ).toEqual({
      anyOf: [{ type: "number" }, { type: "null" }],
    });
  });

  it("refuses keywords it would otherwise weaken silently", () => {
    expect(() => {
      schemaToShape({ allOf: [{ type: "string" }] });
    }).toThrow(/allOf/);
    expect(() => {
      schemaToShape({ $ref: "#/$defs/x" });
    }).toThrow(/\$ref/);
  });
});
