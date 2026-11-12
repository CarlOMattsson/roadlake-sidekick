// Shared by astro.config.mjs and the sync script. Domain and base path are configuration only.
// The domain is most likely roadlake.com; set SITE_URL / SITE_BASE to publish elsewhere
// (for example a GitHub Pages project site: SITE_URL=https://<owner>.github.io SITE_BASE=/<repo>).
export const SITE_URL = (process.env.SITE_URL || 'https://roadlake.com').replace(/\/+$/, '');
export const SITE_BASE = ('/' + (process.env.SITE_BASE || '').replace(/^\/+|\/+$/g, '')).replace(/^\/$/, '');
export const REPO_URL = 'https://github.com/CarlOMattsson/roadlake-sidekick';
