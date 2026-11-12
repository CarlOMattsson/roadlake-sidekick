import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
import { getCollection } from 'astro:content';

type Entry = { type: 'link' | 'group'; href?: string; badge?: unknown; attrs?: Record<string, unknown>; entries?: Entry[] };

let svIds: Set<string> | undefined;

/** Marks sidebar links to pages that exist only in English with an "EN" badge on the Swedish site. */
export const onRequest = defineRouteMiddleware(async (context) => {
  const route = context.locals.starlightRoute;
  if (route.locale !== 'sv') return;
  svIds ??= new Set((await getCollection('docs', (e) => e.id.startsWith('sv/'))).map((e) => e.id));
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  const mark = (entries: Entry[]) => {
    for (const entry of entries) {
      if (entry.type === 'group') mark(entry.entries ?? []);
      else if (entry.href) {
        const id = entry.href.slice(base.length).replace(/^\/|\/$/g, '');
        if (!svIds!.has(id) && !svIds!.has(`${id}/index`)) {
          entry.badge = { text: 'EN', variant: 'default' };
          entry.attrs = { ...entry.attrs, lang: 'en', title: context.locals.t('i18n.untranslatedContent') };
        }
      }
    }
  };
  mark(route.sidebar as unknown as Entry[]);
});
