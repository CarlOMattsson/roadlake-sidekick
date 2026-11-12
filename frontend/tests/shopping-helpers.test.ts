import { describe, expect, it, vi } from "vitest";
import {
  emptyAsk,
  groupByStore,
  splitItemNames,
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

describe("emptyAsk", () => {
  it("sends the example when the host offers messages, else leaves it as text", () => {
    const send = vi.fn().mockResolvedValue(true);
    const withSend = emptyAsk("sv-SE", "Lägg till kaffe", send);
    withSend.onSend?.();
    expect(send).toHaveBeenCalledWith("Lägg till kaffe");
    expect(emptyAsk("en-GB", "Add coffee").onSend).toBeUndefined();
  });
});
