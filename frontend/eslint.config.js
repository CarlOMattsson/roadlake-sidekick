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
  "src/features/journal-app/labels.ts": 515,
  "src/mobile/companion-transport.ts": 610,
};

const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function importBoundaryRules(folder, exceptions = [], extraPatterns = []) {
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
  return {
    "no-restricted-imports": [
      "error",
      { patterns: [...patterns, ...extraPatterns] },
    ],
  };
}

// Files that must stay usable without the Sidekick app's own catalogue or components: the inline cards render in
// a host that loads only what they import. Each file also keeps its folder's import boundary.
const SELF_CONTAINED_FILES = [
  "src/features/work-app/inline/inline-summary.tsx",
  "src/features/work-app/inline/inline-summary-labels.ts",
  "src/features/work-app/inline/work-card.tsx",
  "src/features/work-app/shared/card-labels.ts",
];
const SELF_CONTAINED_PATTERNS = [
  {
    regex: "^@/(?:i18n|components)(?:/|$)",
    message:
      "The inline card and its labels import no Sidekick app catalogue or components.",
  },
];
// The Claude entry gives its rooms no host settings: the settings screen exists only in the mobile app.
const CLAUDE_ENTRY_FILE = "src/features/mcp-apps/sidekick-entry.tsx";
const CLAUDE_ENTRY_PATTERNS = [
  {
    regex: "(?:^@/mobile(?:/|$)|settings-panel)",
    message: "The Claude entry offers no host settings; they are mobile only.",
  },
];

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
  ...SELF_CONTAINED_FILES.map((file) => ({
    files: [file],
    rules: importBoundaryRules("work-app", [], SELF_CONTAINED_PATTERNS),
  })),
  {
    files: [CLAUDE_ENTRY_FILE],
    rules: importBoundaryRules("mcp-apps", [], CLAUDE_ENTRY_PATTERNS),
  },
];

const TSX_SYNTAX_RULES = [
  {
    selector: "JSXText[value=/[A-Za-zÅÄÖÜåäöü]{2,}/]",
    message:
      "User-visible text must come from the label files, not a JSX literal.",
  },
  {
    selector:
      "JSXAttribute[name.name=/^(aria-label|aria-description|alt|title)$/] > Literal[value=/[A-Za-zÅÄÖÜåäöü]{2,}/]",
    message: "Accessible names must come from the label files, not a literal.",
  },
];

// The MCP apps' forms act through their buttons; the mobile pairing form submits.
const FEATURE_SYNTAX_RULES = [
  ...TSX_SYNTAX_RULES,
  {
    // A form acts through its buttons: its submit handler only prevents navigation.
    selector:
      "JSXOpeningElement[name.name='form'] > JSXAttribute[name.name='onSubmit'] > JSXExpressionContainer > :not(Identifier[name='preventSubmit'])",
    message:
      "A form's onSubmit must be preventSubmit; act through the buttons.",
  },
];

export default tseslint.config(
  {
    ignores: [
      "dist",
      "dist-mcp-app",
      "dist-mobile",
      "android",
      "coverage",
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
      "no-restricted-syntax": ["error", ...TSX_SYNTAX_RULES],
    },
  },
  {
    files: ["src/features/**/*.tsx"],
    rules: {
      "no-restricted-syntax": ["error", ...FEATURE_SYNTAX_RULES],
    },
  },
  {
    // The Claude entry never reads host settings (see CLAUDE_ENTRY_PATTERNS).
    files: [CLAUDE_ENTRY_FILE],
    rules: {
      "no-restricted-syntax": [
        "error",
        ...FEATURE_SYNTAX_RULES,
        {
          selector: "Identifier[name='hostSettings']",
          message: "The Claude entry gives its rooms no hostSettings.",
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
