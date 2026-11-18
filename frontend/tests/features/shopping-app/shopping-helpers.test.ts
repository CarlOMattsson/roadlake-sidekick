import { describe, expect, it, vi } from "vitest";
import {
  emptyAsk,
  groupByStore,
  splitItemNames,
  storeSpellings,
} from "@/features/shopping-app/shopping-view-parts/helpers";
import type { ShoppingItem } from "@/features/shopping-app/transport";

function item(name: string, store: string | null, purchased = false) {
  return { id: `${name}-${store}`, name, store, purchased } as ShoppingItem;
}

describe("splitItemNames", () => {
  it("splits on commas and line breaks, trims, and drops empty names", () => {
    expect(splitItemNames(" glödlampor, mjölk ,, ägg\n smör\r\n")).toEqual([
      "glödlampor",
      "mjölk",
      "ägg",
      "smör",
    ]);
    expect(splitItemNames("  , ,\n")).toEqual([]);
    expect(splitItemNames("mjölk 2 l")).toEqual(["mjölk 2 l"]);
  });

  it("keeps a decimal comma between digits, but splits a comma after a number", () => {
    expect(splitItemNames("1,5 l mjölk, ägg")).toEqual(["1,5 l mjölk", "ägg"]);
    expect(splitItemNames("ägg 12, mjölk")).toEqual(["ägg 12", "mjölk"]);
    expect(splitItemNames("2,5 kg potatis\n0,5 l grädde")).toEqual([
      "2,5 kg potatis",
      "0,5 l grädde",
    ]);
  });
});

describe("groupByStore order", () => {
  const names = (items: ShoppingItem[]) =>
    groupByStore(items).map(([store]) => store);

  it("puts the store with the most items on the list first", () => {
    expect(
      names([
        item("a", "Clas Ohlson"),
        item("b", "ICA"),
        item("c", "ICA"),
        item("d", "Akademibokhandeln"),
      ]),
    ).toEqual(["ICA", "Akademibokhandeln", "Clas Ohlson"]);
  });

  it("weighs a store by every item of the list, so ticking items off does not move it", () => {
    const all = [
      item("a", "Apotea"),
      item("b", "ICA"),
      item("c", "ICA", true),
      item("d", "ICA", true),
    ];
    const open = all.filter((one) => !one.purchased);
    expect(groupByStore(open, all).map(([store]) => store)).toEqual([
      "ICA",
      "Apotea",
    ]);
  });

  it("breaks ties in Swedish alphabetical order, Å Ä Ö last", () => {
    expect(
      names([item("a", "Örebro"), item("b", "Zoo"), item("c", "Åhléns")]),
    ).toEqual(["Zoo", "Åhléns", "Örebro"]);
  });

  it("keeps the group without a store last, however many items it has", () => {
    expect(names([item("a", null), item("b", null), item("c", "ICA")])).toEqual(
      ["ICA", null],
    );
  });
});

describe("shops that differ only in case", () => {
  const grouped = (items: ShoppingItem[]) =>
    groupByStore(items).map(([store, rows]) => [
      store,
      rows.map((row) => row.name),
    ]);

  it("are one group, named by the spelling most items use", () => {
    expect(
      grouped([
        item("a", "ICA"),
        item("b", "ica"),
        item("c", "ica"),
        item("d", "Coop"),
      ]),
    ).toEqual([
      ["ica", ["a", "b", "c"]],
      ["Coop", ["d"]],
    ]);
  });

  it("take the first spelling on a tie", () => {
    expect(grouped([item("a", "ica"), item("b", "ICA")])).toEqual([
      ["ica", ["a", "b"]],
    ]);
  });

  it("storeSpellings maps each lower-case shop to its one spelling and skips items without a shop", () => {
    const spellings = storeSpellings([
      item("a", "ICA"),
      item("b", "Ica"),
      item("c", "Ica"),
      item("d", " Coop "),
      item("e", null),
      item("f", "  "),
    ]);
    expect([...spellings]).toEqual([
      ["ica", "Ica"],
      ["coop", "Coop"],
    ]);
  });
});

describe("emptyAsk", () => {
  it("sends the example when the host offers messages, else leaves it as text", () => {
    const send = vi.fn().mockResolvedValue(true);
    const withSend = emptyAsk("sv-SE", "Lägg till kaffe", send);
    withSend.onSend?.();
    expect(send).toHaveBeenCalledWith("Lägg till kaffe");
    expect(emptyAsk("en-GB", "Add coffee").onSend).toBeUndefined();
  });
});
