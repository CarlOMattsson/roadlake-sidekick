import { splitItemNames } from "./helpers";

/** One typed item: its name, and the amount when the text named one ("2 l mjölk", "ägg 12 st"). */
export type TypedItem = { name: string; quantity?: string; unit?: string };

// The units that may follow an amount in typed text, written as the user does. A word that is not one of them
// ("stl" in "blöjor stl 4") is part of the name, so the amount is only read where a unit makes it plain.
const UNITS = new Map<string, string>([
  ["st", "st"],
  ["stk", "st"],
  ["l", "l"],
  ["dl", "dl"],
  ["cl", "cl"],
  ["ml", "ml"],
  ["kg", "kg"],
  ["liter", "l"],
  ["g", "g"],
  ["gram", "g"],
  ["kilo", "kg"],
  ["hg", "hg"],
  ["förp", "förp"],
  ["pkt", "pkt"],
  ["paket", "paket"],
  ["burk", "burk"],
  ["burkar", "burkar"],
  ["flaska", "flaska"],
  ["flaskor", "flaskor"],
  ["påse", "påse"],
  ["påsar", "påsar"],
]);
const AMOUNT = "(\\d+(?:[.,]\\d{1,3})?)";
const UNIT_WORDS = [...UNITS.keys()].join("|");
// "2 l mjölk", "2l mjölk", "2 x mjölk", "2 mjölk": the amount first, then a unit or an "x" or nothing, then the name.
const LEADING = new RegExp(
  `^${AMOUNT}(?:\\s*(${UNIT_WORDS})(?=\\s)|\\s*[x×](?=\\s)|(?=\\s))\\s+(\\S.*)$`,
  "iu",
);
// "ägg 12 st": the name, then the amount with its unit (the unit is required, so "iPhone 15" stays a name).
const TRAILING = new RegExp(`^(\\S.*?)\\s+${AMOUNT}\\s*(${UNIT_WORDS})$`, "iu");
const MAX_QUANTITY = 999999.999;

/** A name typed in lower case starts with a capital, as the list's other items do; a name with a capital is kept. */
function named(name: string): string {
  const text = name.trim();
  return text === text.toLowerCase()
    ? text.charAt(0).toLocaleUpperCase() + text.slice(1)
    : text;
}

function amount(text: string): string | null {
  const value = text.replace(",", ".");
  const number = Number(value);
  return number > 0 && number <= MAX_QUANTITY ? value : null;
}

/**
 * One typed item as name, quantity and unit. "2 l mjölk" is milk, 2 l; "ägg 12 st" is eggs, 12 st; "2 mjölk" is two
 * milks. Text without a plain amount ("blöjor stl 4", "bröd") is only a name.
 */
export function parseTypedItem(text: string): TypedItem {
  const trimmed = text.trim();
  const leading = LEADING.exec(trimmed);
  const trailing = leading ? null : TRAILING.exec(trimmed);
  const parts = leading
    ? { quantity: leading[1], unit: leading[2], name: leading[3] }
    : trailing
      ? { name: trailing[1], quantity: trailing[2], unit: trailing[3] }
      : null;
  const quantity = parts?.quantity ? amount(parts.quantity) : null;
  // A bare amount and unit ("5 kg") names nothing to buy: it stays as typed.
  if (!parts?.name || quantity === null || UNITS.has(parts.name.toLowerCase()))
    return { name: named(trimmed) };
  const unit = parts.unit ? UNITS.get(parts.unit.toLowerCase()) : undefined;
  return { name: named(parts.name), quantity, ...(unit ? { unit } : {}) };
}

/** The items typed in an add field: commas and line breaks separate them (`splitItemNames`), each is read as one item. */
export function parseTypedItems(text: string): TypedItem[] {
  return splitItemNames(text).map(parseTypedItem);
}
