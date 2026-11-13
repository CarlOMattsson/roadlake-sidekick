// @ts-check
import { defineConfig, passthroughImageService } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightLinksValidator from 'starlight-links-validator';
import cspInlineHashes from './integrations/csp-inline-hashes.mjs';
import sitemapRootDefault from './integrations/sitemap-root-default.mjs';
import { lightTheme, darkTheme } from './src/styles/code-theme.mjs';

import { SITE_URL, SITE_BASE, REPO_URL } from './site-config.mjs';

const site = SITE_URL;
const base = SITE_BASE || '/';
const repo = REPO_URL;

/** Sidebar group: English label, Swedish translation, one folder under docs/. */
const group = (label, sv, dir, collapsed = true) => ({
  label,
  translations: { sv },
  collapsed,
  items: [{ autogenerate: { directory: `docs/${dir}`, collapsed: true } }],
});

export default defineConfig({
  site,
  base,
  trailingSlash: 'always',
  build: { format: 'directory' },
  // No sharp and no image binaries: the screenshots are already the right size.
  image: { service: passthroughImageService() },
  security: {
    // A <meta http-equiv> policy with hashes for the inline scripts and styles. No 'unsafe-inline' for scripts.
    csp: {
      directives: [
        "default-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'none'",
      ],
      // Pagefind runs WebAssembly.
      scriptDirective: { resources: ["'self'", "'wasm-unsafe-eval'"] },
    },
  },
  integrations: [
    starlight({
      title: 'Roadlake Sidekick',
      description: 'Sidekick keeps your tasks, journal, contacts and shopping in your own database and shows them in Claude.',
      defaultLocale: 'en',
      locales: {
        en: { label: 'English', lang: 'en' },
        sv: { label: 'Svenska', lang: 'sv' },
      },
      // The 404 page is our own bilingual src/pages/404.astro.
      disable404Route: true,
      lastUpdated: false,
      pagefind: true,
      favicon: '/favicon.svg',
      social: [{ icon: 'github', label: 'GitHub', href: repo }],
      // No edit link: the Footer override offers "Report a problem with this page" (a prefilled GitHub issue).
      customCss: ['./src/styles/tokens.css', './src/styles/starlight.css', './src/styles/marketing.css'],
      routeMiddleware: './src/routeData.ts',
      head: [
        { tag: 'link', attrs: { rel: 'apple-touch-icon', href: `${base === '/' ? '' : base}/apple-touch-icon.png` } },
        { tag: 'link', attrs: { rel: 'manifest', href: `${base === '/' ? '' : base}/site.webmanifest` } },
        { tag: 'meta', attrs: { name: 'theme-color', content: '#0f766e' } },
        { tag: 'meta', attrs: { property: 'og:image', content: `${site}${base === '/' ? '' : base}/og.png` } },
        { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
      ],
      expressiveCode: {
        themes: [darkTheme, lightTheme],
        useStarlightDarkModeSwitch: true,
        useStarlightUiThemeColors: false,
        // Plain code frames: no terminal window chrome (title bar with dots) around shell blocks.
        defaultProps: { frame: 'code' },
        styleOverrides: {
          borderRadius: '0.75rem',
          borderColor: 'var(--sk-line)',
          codeBackground: 'var(--site-code-bg)',
          codeFontFamily: 'var(--site-mono)',
          codeFontSize: '0.875rem',
          codeLineHeight: '1.5rem',
          uiFontFamily: 'var(--sk-font)',
          uiFontSize: '0.875rem',
          frames: {
            editorActiveTabBackground: 'var(--site-code-bg)',
            editorTabBarBackground: 'var(--site-code-bg)',
            terminalTitlebarBackground: 'var(--site-code-bg)',
            terminalBackground: 'var(--site-code-bg)',
            editorBackground: 'var(--site-code-bg)',
            frameBoxShadowCssValue: 'none',
          },
        },
      },
      components: {
        Header: './src/components/overrides/Header.astro',
        SiteTitle: './src/components/overrides/SiteTitle.astro',
        MobileMenuFooter: './src/components/overrides/MobileMenuFooter.astro',
        PageFrame: './src/components/overrides/PageFrame.astro',
        PageTitle: './src/components/overrides/PageTitle.astro',
        Footer: './src/components/overrides/Footer.astro',
      },
      // Relative links keep a reader in their language (also on an English fallback page under /sv/).
      plugins: [starlightLinksValidator({ errorOnRelativeLinks: false })],
      sidebar: [
        group('Get started', 'Kom igång', 'start', false),
        group('User guide', 'Användarguide', 'guide', false),
        group('Operate', 'Drift', 'operate', false),
        group('Reference', 'Referens', 'reference'),
        group('Explanation', 'Förklaring', 'explanation'),
        group('Decisions', 'Beslut', 'decisions'),
        group('Contribute', 'Bidra', 'contribute'),
        group('Maintainers', 'Underhåll', 'maintainers'),
      ],
    }),
    // Must come after Starlight: adds the hashes of Starlight's inline scripts to the CSP meta tag.
    cspInlineHashes(),
    sitemapRootDefault(new URL(base.endsWith('/') ? base : `${base}/`, site).href),
  ],
});
