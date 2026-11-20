import { describe, expect, it } from "vitest";
import {
  parseTypedItem,
  parseTypedItems,
} from "@/features/shopping-app/shopping-view-parts/parse-items";

describe("parseTypedItem reads an amount in the text", () => {
  it.each([
    ["2 l mjölk", { name: "Mjölk", quantity: "2", unit: "l" }],
    ["2l mjölk", { name: "Mjölk", quantity: "2", unit: "l" }],
    ["1,5 l mjölk", { name: "Mjölk", quantity: "1.5", unit: "l" }],
    ["ägg 12 st", { name: "Ägg", quantity: "12", unit: "st" }],
    ["2 x mjölk", { name: "Mjölk", quantity: "2" }],
    ["2x mjölk", { name: "Mjölk", quantity: "2" }],
    ["2 mjölk", { name: "Mjölk", quantity: "2" }],
    ["läsk 2", { name: "Läsk", quantity: "2" }],
    ["Läsk 2", { name: "Läsk", quantity: "2" }],
    ["bröd 12", { name: "Bröd", quantity: "12" }],
  ])("%s", (text, expected) => {
    expect(parseTypedItem(text)).toEqual(expected);
  });
});

describe("parseTypedItem leaves text without a plain amount as a name", () => {
  it.each([
    ["blöjor stl 4", "Blöjor stl 4"],
    ["iPhone 15", "iPhone 15"],
    ["Coca Cola 2", "Coca Cola 2"],
    ["läsk 0", "Läsk 0"],
    ["läsk 100", "Läsk 100"],
    ["läsk 2,5", "Läsk 2,5"],
    ["B12", "B12"],
    ["5 kg", "5 kg"],
    ["3-pack", "3-pack"],
  ])("%s", (text, name) => {
    expect(parseTypedItem(text)).toEqual({ name });
  });

  it("keeps a name with a capital as typed and capitalises an all lower-case one", () => {
    expect(parseTypedItem("Mjölk")).toEqual({ name: "Mjölk" });
    expect(parseTypedItem("mjölk")).toEqual({ name: "Mjölk" });
  });

  it("keeps a quantity over 999999.999 in the name", () => {
    expect(parseTypedItem("1000000 mjölk")).toEqual({ name: "1000000 mjölk" });
    expect(parseTypedItem("999999,999 l mjölk")).toEqual({
      name: "Mjölk",
      quantity: "999999.999",
      unit: "l",
    });
  });
});

describe("parseTypedItems", () => {
  it("reads each separated item, and a decimal comma does not separate", () => {
    expect(parseTypedItems("1,5 l mjölk, ägg")).toEqual([
      { name: "Mjölk", quantity: "1.5", unit: "l" },
      { name: "Ägg" },
    ]);
  });
});
