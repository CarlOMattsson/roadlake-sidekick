/**
 * Text-level reading of the app's stylesheets for the CSS contract tests.
 *
 * The contract tests (`ui-css-contract`, `app-css-contract`, `journal-css-contract`) check rules of the real
 * files as text and state only what they expect. Loading the files, blanking comments, splitting rules and
 * reading a declaration live here once. `helpers/stylesheet.ts` is the other reader: it resolves which rules
 * apply to a rendered element, while this one answers "does this selector declare this value".
 */
import path from "node:path";

import { featuresDir, readText, sourceFiles } from "./source-files";

export type CssFile = {
  /** The path under `src/features`, with forward slashes. */
  rel: string;
  /** The file as written. */
  raw: string;
  /** The file with comments blanked, so words inside a comment cannot trip a rule. */
  css: string;
};

export type CssRule = {
  /** The selector list, whitespace collapsed. */
  selector: string;
  /** The declarations as written. */
  body: string;
  /** The declarations, whitespace collapsed. */
  declarations: string;
  /** The line of the rule in the text it was read from. */
  line: number;
};

export type CssDeclaration = { property: string; value: string };

/** Comments blanked out, keeping newlines, so line numbers in messages stay correct. */
export function stripComments(raw: string): string {
  return raw.replace(/\/\*[\s\S]*?\*\//g, (match) =>
    match.replace(/[^\n]/g, " "),
  );
}

/** The 1-based line of the character at `index`. */
export function lineOf(text: string, index: number): number {
  return text.slice(0, index).split("\n").length;
}

/** Every `*.css` file under `src/features/<directory>`, including subfolders. */
export function loadCssFiles(directory: string): CssFile[] {
  return sourceFiles(path.join(featuresDir, directory), /\.css$/).map(
    (file) => {
      const raw = readText(file);
      return {
        rel: path.relative(featuresDir, file).split(path.sep).join("/"),
        raw,
        css: stripComments(raw),
      };
    },
  );
}

/** The comment-blanked text of one stylesheet under `src/features`. */
export function readCss(relativePath: string): string {
  return stripComments(readText(path.join(featuresDir, relativePath)));
}

/**
 * Flat rules. A rule inside an `@media` block is matched on its own, because a rule body never contains braces.
 * At-rule preludes are never followed by a body without braces, so they do not match.
 */
export function cssRules(css: string): CssRule[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .map((match) => ({
      selector: (match[1] ?? "").replace(/\s+/g, " ").trim(),
      body: match[2] ?? "",
      declarations: (match[2] ?? "").replace(/\s+/g, " ").trim(),
      line: lineOf(css, match.index ?? 0),
    }))
    .filter((rule) => !rule.selector.startsWith("@"));
}

/** The declarations of a rule body, properties lower-cased. */
export function declarationsOf(body: string): CssDeclaration[] {
  return body
    .split(";")
    .map((part) => {
      const colon = part.indexOf(":");
      if (colon === -1) return null;
      return {
        property: part.slice(0, colon).trim().toLowerCase(),
        value: part.slice(colon + 1).trim(),
      };
    })
    .filter(
      (declaration): declaration is CssDeclaration => declaration !== null,
    );
}

/** The value of the first declaration of `property` in `body`. */
export function valueOf(body: string, property: string): string | undefined {
  return declarationsOf(body).find(
    (declaration) => declaration.property === property,
  )?.value;
}

/** True when the rule declares exactly `property: value` (one declaration, normalised spacing). */
export function declares(
  rule: CssRule,
  property: string,
  value: string,
): boolean {
  return rule.declarations
    .split(";")
    .some((declaration) => declaration.trim() === `${property}: ${value}`);
}

/** The first rule whose whole selector list is `selector` (whitespace collapsed). */
export function ruleFor(
  rules: readonly CssRule[],
  selector: string,
): CssRule | undefined {
  return rules.find((rule) => rule.selector === selector);
}

/** The custom properties declared (`--sk-name:`) in `css`. */
export function customPropertyDeclarations(css: string): Set<string> {
  return customPropertyNames(css, /(?<![\w-])(--sk-[\w-]+)\s*:/g);
}

/** The custom properties read (`var(--sk-name`) in `css`. */
export function customPropertyUses(css: string): Set<string> {
  return customPropertyNames(css, /var\(\s*(--sk-[\w-]+)/g);
}

function customPropertyNames(css: string, pattern: RegExp): Set<string> {
  return new Set([...css.matchAll(pattern)].map((match) => match[1] ?? ""));
}
