/**
 * A small CSS reader for tests.
 *
 * jsdom lays nothing out, and its CSSOM drops declarations it cannot parse (`flex: 1 1 0`, `border` with a
 * `var()`), so `getComputedStyle` cannot be trusted with this app's stylesheets. This reads the real file into
 * rules and declarations instead, and resolves which rules apply to a *rendered* element with `Element.matches`.
 * A test therefore checks the markup the component produced against the stylesheet, not a regex against text.
 *
 * Limits: `!important` and inheritance are not modelled, and pseudo-classes jsdom cannot match
 * (`:hover`, `:focus-visible`) never apply to an element; ask for them by selector with `rule()`.
 * The pixel result of a rule is checked by the Playwright specs under `tests/e2e`.
 */
import { readSource } from "./source-files";

export type Declarations = Readonly<Record<string, string>>;

export interface CssRule {
  /** The selector list as written, whitespace-normalised. */
  readonly selector: string;
  /** The at-rules around it, outermost first, e.g. `@container (max-width: 360px)`. */
  readonly conditions: readonly string[];
  readonly declarations: Declarations;
}

const GROUPING_AT_RULES = new Set([
  "media",
  "container",
  "supports",
  "layer",
  "scope",
]);

function normalise(text: string): string {
  return text
    .replace(/\s+/g, " ")
    .replace(/ ?([>+~]) ?/g, " $1 ")
    .replace(/\s*,\s*/g, ", ")
    .replace(/\(\s+/g, "(")
    .replace(/\s+\)/g, ")")
    .trim();
}

/** Splits `text` on `separator` where it is not inside parentheses, brackets or a string. */
function splitTopLevel(text: string, separator: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let quote = "";
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i] as string;
    if (quote !== "") {
      if (char === "\\") i += 1;
      else if (char === quote) quote = "";
    } else if (char === '"' || char === "'") quote = char;
    else if (char === "(" || char === "[") depth += 1;
    else if (char === ")" || char === "]") depth -= 1;
    else if (char === separator && depth === 0) {
      parts.push(text.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(text.slice(start));
  return parts;
}

type Specificity = readonly [number, number, number];

function compareSpecificity(a: Specificity, b: Specificity): number {
  return a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
}

/** The specificity of one complex selector (ids, classes/attributes/pseudo-classes, types/pseudo-elements). */
function specificity(selector: string): Specificity {
  let ids = 0;
  let classes = 0;
  let types = 0;
  let rest = selector.replace(
    /:(is|not|has|where|matches)\(((?:[^()]|\([^()]*\))*)\)/g,
    (_whole, name: string, args: string) => {
      if (name !== "where") {
        const widest = splitTopLevel(args, ",")
          .map((part) => specificity(part.trim()))
          .sort(compareSpecificity)
          .pop();
        if (widest !== undefined) {
          ids += widest[0];
          classes += widest[1];
          types += widest[2];
        }
      }
      return " ";
    },
  );
  const take = (pattern: RegExp, onMatch: () => void) => {
    rest = rest.replace(pattern, () => {
      onMatch();
      return " ";
    });
  };
  take(/\[[^\]]*\]/g, () => (classes += 1));
  take(/#[\w-]+/g, () => (ids += 1));
  take(/::[\w-]+/g, () => (types += 1));
  take(/:[\w-]+(\([^)]*\))?/g, () => (classes += 1));
  take(/\.[\w-]+/g, () => (classes += 1));
  take(/(^|[\s>+~])[a-zA-Z][\w-]*/g, () => (types += 1));
  return [ids, classes, types];
}

/** A value with its whitespace collapsed and one space after each comma, leaving quoted text untouched. */
function normaliseValue(value: string): string {
  return value
    .split(/("[^"]*"|'[^']*')/)
    .map((piece, index) =>
      index % 2 === 1
        ? piece
        : piece
            .replace(/\s+/g, " ")
            .replace(/\(\s+/g, "(")
            .replace(/\s+\)/g, ")")
            .replace(/,(?! )/g, ", "),
    )
    .join("")
    .trim();
}

function parseDeclarations(body: string): Declarations {
  const declarations: Record<string, string> = {};
  for (const part of splitTopLevel(body, ";")) {
    const colon = part.indexOf(":");
    if (colon < 0) continue;
    const property = part.slice(0, colon).trim();
    if (property === "") continue;
    declarations[
      property.startsWith("--") ? property : property.toLowerCase()
    ] = normaliseValue(part.slice(colon + 1));
  }
  return declarations;
}

/** The index just after the `}` that closes the block opened at `open` (a `{`). */
function closingBrace(css: string, open: number): number {
  let depth = 0;
  let quote = "";
  for (let i = open; i < css.length; i += 1) {
    const char = css[i] as string;
    if (quote !== "") {
      if (char === "\\") i += 1;
      else if (char === quote) quote = "";
    } else if (char === '"' || char === "'") quote = char;
    else if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      if (depth === 0) return i + 1;
    }
  }
  throw new Error("unbalanced braces in stylesheet");
}

function parseRules(
  css: string,
  conditions: readonly string[],
  keyframes: Map<string, CssRule[]>,
): CssRule[] {
  const rules: CssRule[] = [];
  let i = 0;
  while (i < css.length) {
    const open = css.indexOf("{", i);
    const semicolon = css.indexOf(";", i);
    if (open < 0) break;
    if (
      semicolon >= 0 &&
      semicolon < open &&
      css.slice(i).trimStart()[0] === "@"
    ) {
      i = semicolon + 1; // `@import`, `@charset`
      continue;
    }
    const prelude = css.slice(i, open).trim();
    const end = closingBrace(css, open);
    const body = css.slice(open + 1, end - 1);
    i = end;
    if (prelude.startsWith("@")) {
      const name = /^@([\w-]+)/.exec(prelude)?.[1] ?? "";
      if (GROUPING_AT_RULES.has(name)) {
        rules.push(
          ...parseRules(body, [...conditions, normalise(prelude)], keyframes),
        );
      } else if (name === "keyframes") {
        keyframes.set(
          prelude.replace(/^@keyframes\s+/, "").trim(),
          parseRules(body, [], keyframes),
        );
      }
      continue; // `@font-face` and the like carry no selector rules
    }
    if (body.includes("{")) {
      throw new Error(`nested rules are not supported (in "${prelude}")`);
    }
    rules.push({
      selector: normalise(prelude),
      conditions,
      declarations: parseDeclarations(body),
    });
  }
  return rules;
}

export interface StyleOptions {
  /** At-rules the rules must sit inside, e.g. `@container (max-width: 360px)`. None by default. */
  conditions?: readonly string[];
  /** A room root class (`sidekick-work`) to treat as an ancestor of the element. */
  room?: string;
  /** A pseudo-element (`::before`): the rules that style it on this element, instead of the element itself. */
  pseudo?: string;
}

export class Stylesheet {
  readonly rules: readonly CssRule[];
  private readonly frames = new Map<string, CssRule[]>();

  constructor(css: string) {
    this.rules = parseRules(
      css.replace(/\/\*[\s\S]*?\*\//g, ""),
      [],
      this.frames,
    );
  }

  /** The steps of `@keyframes name` (`from`, `to`, `50%`), in order. Throws when there is none. */
  keyframes(name: string): { selector: string; declarations: Declarations }[] {
    const steps = this.frames.get(name);
    if (steps === undefined) throw new Error(`no @keyframes ${name}`);
    return steps.map(({ selector, declarations }) => ({
      selector,
      declarations,
    }));
  }

  /** Every rule whose selector list names every selector in `selector` (a comma list is allowed), in the given at-rule context (none by default). */
  private named(selector: string, conditions: readonly string[]): CssRule[] {
    const wanted = splitTopLevel(normalise(selector), ",").map((part) =>
      part.trim(),
    );
    return this.rules.filter((rule) => {
      const listed = splitTopLevel(rule.selector, ",").map((part) =>
        part.trim(),
      );
      return (
        rule.conditions.join("|") === conditions.map(normalise).join("|") &&
        wanted.every((part) => listed.includes(part))
      );
    });
  }

  /** Whether the sheet has a rule for `selector`. */
  has(selector: string, conditions: readonly string[] = []): boolean {
    return this.named(selector, conditions).length > 0;
  }

  /**
   * The merged declarations of every rule that lists `selector` (a later rule wins). Throws when there is
   * none, so a renamed selector fails loudly rather than passing as "no declarations".
   */
  rule(selector: string, conditions: readonly string[] = []): Declarations {
    const found = this.named(selector, conditions);
    if (found.length === 0) {
      const token = /[.#\w-]+(?:::?[\w-]+)*$/.exec(selector.trim())?.[0] ?? "";
      const near = this.rules
        .filter((rule) => token !== "" && rule.selector.includes(token))
        .map((rule) => rule.selector)
        .slice(0, 5);
      throw new Error(
        `no rule for "${selector}"${conditions.length > 0 ? ` in ${conditions.join(" ")}` : ""}` +
          (near.length > 0 ? `; similar: ${near.join(" | ")}` : ""),
      );
    }
    return found.reduce<Declarations>(
      (merged, rule) => ({ ...merged, ...rule.declarations }),
      {},
    );
  }

  /**
   * The declarations that apply to `element`: every rule (in the given at-rule context) with a selector that
   * matches it, later rules winning. The element must be rendered, so a class the component stopped applying
   * shows up here as a missing declaration. App rules are scoped under a room root (`.sidekick-work`); the
   * tests render a view alone, so `room` stands that class on the document for the duration of the lookup.
   */
  styleOf(
    element: Element,
    { conditions = [], room, pseudo }: StyleOptions = {},
  ): Declarations {
    const context = conditions.map(normalise).join("|");
    const root = element.ownerDocument.documentElement;
    const added = room !== undefined && !root.classList.contains(room);
    if (added) root.classList.add(room);
    try {
      // The cascade: the more specific selector wins, and the later one among equals.
      const applying: { weight: Specificity; order: number; rule: CssRule }[] =
        [];
      this.rules.forEach((rule, order) => {
        if (rule.conditions.join("|") !== context) return;
        for (const part of splitTopLevel(rule.selector, ",")) {
          let matches = false;
          const text = part.trim();
          const hasPseudo = pseudo !== undefined && text.endsWith(pseudo);
          if (pseudo !== undefined && !hasPseudo) continue;
          try {
            matches = element.matches(
              hasPseudo ? text.slice(0, -pseudo.length) || "*" : text,
            );
          } catch {
            // a pseudo-class jsdom does not know never applies
          }
          if (matches) {
            applying.push({ weight: specificity(part.trim()), order, rule });
          }
        }
      });
      applying.sort(
        (a, b) => compareSpecificity(a.weight, b.weight) || a.order - b.order,
      );
      const merged: Record<string, string> = {};
      for (const { rule } of applying) Object.assign(merged, rule.declarations);
      return merged;
    } finally {
      if (added && room !== undefined) root.classList.remove(room);
    }
  }
}

/** The stylesheet at `relativePath` under `frontend/src`. */
export function readStylesheet(...relativePaths: string[]): Stylesheet {
  return new Stylesheet(relativePaths.map(readSource).join("\n"));
}
