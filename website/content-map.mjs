// The only hand-edited registry for the docs sync (scripts/sync-docs.mjs).
// Paths are relative to the source root (the repository). Entries without a
// trailing slash are stems: "docs/android" covers android.md and android.sv.md.

// Which documents become pages. Only these documents are published.
// After the docs restructuring only this list and `order` change, never the script.
export const include = [
  'docs/README',
  'docs/contribute/',
  'docs/faq',
  'docs/start/',
  'docs/guide/',
  'docs/operate/',
  'docs/reference/',
  'docs/explanation/',
  'docs/decisions/',
  'docs/maintainers/',
];

// Never rendered, even if matched by `include`.
export const exclude = ['docs/images/', 'docs/contracts/'];

// Root files rendered as pages: source stem (SECURITY covers SECURITY.md and SECURITY.sv.md) and page slug.
export const rootFiles = [
  { src: 'CONTRIBUTING', slug: 'docs/contribute/index' },
  { src: 'CODE_OF_CONDUCT', slug: 'docs/contribute/code-of-conduct' },
  { src: 'CLA', slug: 'docs/contribute/cla' },
  { src: 'LICENSE', slug: 'docs/license' },
  { src: 'SECURITY', slug: 'docs/security-policy' },
  { src: 'CHANGELOG', slug: 'docs/changelog' },
];

// Page order inside a folder: folder page path -> slugs in order. Pages not listed sort last, alphabetically.
// Each entry must name an existing page (checked by --verify-sources and by the tests).
export const order = {
  docs: ['index', 'faq'],
  'docs/start': ['index', 'self-hosted-server', 'work-laptop', 'first-day', 'first-contribution'],
  'docs/guide': ['index', 'work', 'journal', 'contacts', 'shopping', 'control-and-memory', 'android-app', 'today-widget'],
  'docs/operate': [
    'index',
    'connect-claude',
    'pair-android',
    'push-reminders',
    'memory',
    'update',
    'backup-and-restore',
    'empty-trash',
    'move-data',
    'license-key',
  ],
  'docs/operate/work-laptop': ['index', 'network', 'start-at-login', 'backup-and-update', 'macos', 'model-server', 'uninstall'],
  'docs/reference': ['configuration', 'scopes', 'cli', 'selfhost-profiles', 'languages', 'design-system'],
  'docs/explanation': ['overview', 'security-and-privacy', 'threat-model', 'licensing', 'schema-baseline'],
  'docs/explanation/architecture': ['backend', 'mcp-apps'],
  'docs/decisions': ['index', 'log', 'archive'],
  'docs/contribute': ['index', 'development', 'code-of-conduct', 'cla'],
  'docs/maintainers': ['index', 'release', 'release-drill', 'verification', 'website-domain'],
};

// Generated pages: page slug -> the generator that produces them (used for the report-a-problem link).
export const generated = {};

// Mermaid blocks whose source lacks accTitle/accDescr: sha256-12 of the block -> text for alt and caption.
// Temporary: the source blocks should carry accTitle/accDescr themselves; then delete the entry.
export const diagramText = {
  '3f10ffe94ae4': {
    title: 'MCP Apps boundary',
    descr:
      'The host conversation calls curated Sidekick MCP tools and shows Sidekick views as MCP Apps. The apps reach the tools through the host bridge. The tools call shared application use cases, which read and write PostgreSQL.',
  },
};

// Directories copied as-is to public/docs-images/ (used by the home page; docs reference their own images).
export const assets = ['docs/images/rooms/'];
