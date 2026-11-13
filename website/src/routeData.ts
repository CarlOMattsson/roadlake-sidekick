import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
import { getCollection } from 'astro:content';

type Entry = { type: 'link' | 'group'; href?: string; badge?: unknown; attrs?: Record<string, unknown>; entries?: Entry[] };

let svIds: Set<string> | undefined;

type HeadTag = { tag: string; attrs?: Record<string, unknown>; content?: string };

const IMAGE_ALT = { sv: 'Roadlake Sidekick, logotyp', en: 'Roadlake Sidekick logo' };

/** Swedish title and description for pages whose body exists only in English (shown as the English fallback). */
const SV_FALLBACK_META: Record<string, { title: string; description: string }> = {
  'docs/license': {
    title: 'Licens',
    description:
      'Roadlake Sidekicks licens med tillgänglig källkod: vad du får göra med källkoden och de tilläggsvillkor som gäller. Texten finns bara på engelska.',
  },
};

/** Head fixes Starlight does not make: og:type website outside the docs, an alt text for the share image, localized fallback meta. */
function fixHead(route: { locale?: string; id: string; head: unknown; entry: { data: { title: string; description?: string } } }) {
  const head = route.head as HeadTag[];
  const locale = route.locale === 'sv' ? 'sv' : 'en';
  const stem = route.id.replace(/^(sv|en)\//, '').replace(/\/index$/, '').replace(/^index$/, '');
  const isDoc = stem.startsWith('docs');
  const override = locale === 'sv' ? SV_FALLBACK_META[stem] : undefined;
  const meta = (tag: HeadTag, key: string) => tag.tag === 'meta' && (tag.attrs?.property === key || tag.attrs?.name === key);
  for (const tag of head) {
    if (!isDoc && meta(tag, 'og:type')) tag.attrs = { ...tag.attrs, content: 'website' };
    if (!override) continue;
    if (tag.tag === 'title') tag.content = `${override.title} | Roadlake Sidekick`;
    if (meta(tag, 'og:title')) tag.attrs = { ...tag.attrs, content: override.title };
    if (meta(tag, 'description') || meta(tag, 'og:description')) tag.attrs = { ...tag.attrs, content: override.description };
  }
  if (override) {
    route.entry.data.title = override.title;
    route.entry.data.description = override.description;
  }
  const at = head.findIndex((tag) => meta(tag, 'og:image'));
  if (at >= 0) {
    head.splice(
      at + 1,
      0,
      { tag: 'meta', attrs: { property: 'og:image:alt', content: IMAGE_ALT[locale] } },
      { tag: 'meta', attrs: { name: 'twitter:image:alt', content: IMAGE_ALT[locale] } },
    );
  }
}

/** Fixes page meta; marks sidebar links to pages that exist only in English with an "EN" badge on the Swedish site. */
export const onRequest = defineRouteMiddleware(async (context) => {
  const route = context.locals.starlightRoute;
  fixHead(route as unknown as Parameters<typeof fixHead>[0]);
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
