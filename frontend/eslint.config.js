import js from "@eslint/js";
import globals from "globals";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

/*
 * Import boundaries: src/lib must not import src/features. A feature folder may import its own files,
 * src/lib and the shared src/features/mcp-apps folder, but never another feature's files. Existing
 * violations are listed per file below ("existing, to be removed"); the list may only shrink.
 */
const FEATURE_FOLDERS = [
  "control-app",
  "journal-app",
  "mcp-apps",
  "shopping-app",
  "work-app",
];
const SHARED_FEATURE_FOLDER = "mcp-apps";

// Exception paths are relative to src/features, e.g. "work-app/transport/transport".
const EXISTING_BOUNDARY_EXCEPTIONS = {
  // existing, to be removed: contract checks import feature transport modules.
  "src/lib/mcp/contract-checks.ts": [
    "control-app/transport",
    "journal-app/draft-review-parts/edit-values",
    "journal-app/transport",
    "shopping-app/transport",
    "work-app/transport/transport",
  ],
  // existing, to be removed: the awaiting screen imports work-app and control-app labels.
  "src/features/mcp-apps/awaiting.tsx": [
    "control-app/labels",
    "work-app/shell/view-tabs",
    "work-app/shell/work-shell-labels",
  ],
  // existing, to be removed: the shell composes feature room entry points; how rooms compose is still open.
  "src/features/mcp-apps/sidekick-rooms.tsx": [
    "control-app/room",
    "journal-app/room",
    "shopping-app/room",
    "work-app/contacts/contacts-room",
    "work-app/room",
  ],
};

const MAX_FILE_LINES = 500;
// Existing files over MAX_FILE_LINES, with their size rounded up to the next ten. Split a file and delete its line;
// never raise a number.
const OVERSIZED_FILES = {
  "src/features/journal-app/day-frame.tsx": 520,
  "src/features/journal-app/labels.ts": 515,
  "src/features/journal-app/transport.ts": 510,
  "src/features/work-app/contacts/contacts-list.tsx": 600,
  "src/features/work-app/shared/labels.ts": 547,
  "src/features/work-app/saved-views/saved-views-bar.tsx": 530,
  "src/features/work-app/tasks/task-steps.tsx": 660,
  "src/mobile/companion-transport.ts": 610,
};

const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function importBoundaryRules(folder, exceptions = []) {
  let patterns;
  if (folder === "lib") {
    // A regex, not a glob: gitignore-style negation cannot re-include a file under an ignored parent folder.
    const allowed = exceptions.length
      ? `(?!(?:${exceptions.map(escapeRegex).join("|")})$)`
      : "";
    patterns = [
      {
        regex: `(?:^|/)features/${allowed}`,
        message:
          "src/lib must not import src/features; move shared code into src/lib.",
      },
    ];
  } else {
    patterns = FEATURE_FOLDERS.filter(
      (other) => other !== folder && other !== SHARED_FEATURE_FOLDER,
    ).map((other) => {
      const message = `Import ${other} through src/features/mcp-apps or src/lib, not its internals.`;
      const allowedPaths = exceptions
        .filter((e) => e.startsWith(`${other}/`))
        .map((e) => escapeRegex(e.slice(other.length + 1)));
      if (allowedPaths.length === 0)
        return { group: [`**/${other}/**`], message };
      // A regex, not a glob: gitignore-style negation cannot re-include a file under an ignored subfolder.
      return {
        regex: `(?:^|/)${other}/(?!(?:${allowedPaths.join("|")})$)`,
        message,
      };
    });
  }
  return { "no-restricted-imports": ["error", { patterns }] };
}

const importBoundaryBlocks = [
  { files: ["src/lib/**/*.{ts,tsx}"], rules: importBoundaryRules("lib") },
  ...FEATURE_FOLDERS.map((folder) => ({
    files: [`src/features/${folder}/**/*.{ts,tsx}`],
    rules: importBoundaryRules(folder),
  })),
  // Per-file ratchet blocks come last so they replace the folder rule for these files only.
  ...Object.entries(EXISTING_BOUNDARY_EXCEPTIONS).map(([file, exceptions]) => ({
    files: [file],
    rules: importBoundaryRules(
      file.startsWith("src/lib/") ? "lib" : file.split("/")[2],
      exceptions,
    ),
  })),
];

export default tseslint.config(
  {
    ignores: [
      "dist",
      "dist-mcp-app",
      "dist-mobile",
      "android",
      "eslint.config.js",
      "scripts/check.mjs",
      "scripts/generate-tool-types.mjs",
      "scripts/tool-shapes.mjs",
      "vite.config.d.ts",
      "vite.config.js",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": "off",
    },
  },
  {
    /*
     * Localization gate: user-visible text lives in the typed label files (`*-labels.ts`,
     * `labels.ts`), never as a literal in a component. Reviewed exceptions: machine
     * placeholders such as date/time format hints, and punctuation or symbols shorter
     * than two letters (separators, ellipses, keyboard hints).
     */
    files: ["src/**/*.tsx"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXText[value=/[A-Za-zÅÄÖÜåäöü]{2,}/]",
          message:
            "User-visible text must come from the label files, not a JSX literal.",
        },
        {
          selector:
            "JSXAttribute[name.name=/^(aria-label|aria-description|alt|title)$/] > Literal[value=/[A-Za-zÅÄÖÜåäöü]{2,}/]",
          message:
            "Accessible names must come from the label files, not a literal.",
        },
      ],
    },
  },
  {
    // Accessibility gate: static jsx-a11y checks on every component file. Runtime checks live in the axe spec.
    files: ["src/**/*.tsx"],
    ...jsxA11y.flatConfigs.recommended,
  },
  {
    /*
     * File-size gate: a source file stays under 500 lines (blank lines and comments excluded) so a view
     * is split into hooks and sub-components instead of growing into one file. Files already over the
     * limit are listed in OVERSIZED_FILES with their current size rounded up; the list may only shrink.
     */
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      "max-lines": [
        "error",
        { max: MAX_FILE_LINES, skipBlankLines: true, skipComments: true },
      ],
    },
  },
  // Per-file ratchet blocks come after the general gate so they replace its limit for these files only.
  ...Object.entries(OVERSIZED_FILES).map(([file, max]) => ({
    files: [file],
    rules: {
      "max-lines": ["error", { max, skipBlankLines: true, skipComments: true }],
    },
  })),
  ...importBoundaryBlocks,
);
