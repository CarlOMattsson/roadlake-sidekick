import {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
} from "react";

import { BackHeader } from "./back-header";
import { ChevronLeftIcon, ChevronRightIcon, MoreIcon } from "./icons";
import { Menu, MenuItem, menuButtonKeys } from "./menu";
import { photoLabelsFor } from "./photo-labels";
import {
  photoAlt,
  photoCaption,
  photoDayLabel,
  safePhotoSrc,
  type Photo,
} from "./photos";
import { useShortcuts } from "./shortcuts";
import { ErrorNotice } from "./states";

import "./photos.css";

/** What `load` answers: a `data:image/…` URL, or the photo's bytes as a Blob (turned into one here). */
export type PhotoSource = string | Blob;

/** An entry of the viewer's ⋯, for the photo on screen: Ändra bildtext, Ta bort foto (`danger`), Kopiera bildtext. */
export type PhotoViewerAction = {
  label: string;
  onChoose: (photo: Photo) => void;
  danger?: boolean;
  disabled?: boolean;
};

/**
 * The source to draw for `source`, or null when it is no raster image inline in the document. A Blob is read into a
 * `data:` URL, because the host's CSP has no `blob:` in `img-src`.
 */
export async function toPhotoSrc(source: PhotoSource): Promise<string | null> {
  if (typeof source === "string") return safePhotoSrc(source);
  if (!source.type.startsWith("image/")) return null;
  const read = await new Promise<string | null>((resolve) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve(typeof reader.result === "string" ? reader.result : null);
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(source);
  });
  return safePhotoSrc(read);
}

/** Large photos kept while the viewer is open, so a step back draws at once; the oldest goes first. */
const KEEP = 12;
/** A swipe steps when it went this far sideways, and further sideways than up or down. */
const SWIPE_PX = 48;
/**
 * The stage's height over its width: the photo's own, from a 2:1 panorama to a 3:4 portrait (a taller photo is fitted
 * inside); 3:4 landscape while its size is unknown.
 */
const RATIO_MIN = 1 / 2;
const RATIO_MAX = 4 / 3;
const RATIO_DEFAULT = 3 / 4;

function stageRatio(photo: Photo): number {
  const { width = 0, height = 0 } = photo;
  if (width <= 0 || height <= 0) return RATIO_DEFAULT;
  return Math.min(RATIO_MAX, Math.max(RATIO_MIN, height / width));
}

type Loaded =
  { id: string; phase: "ready"; src: string } | { id: string; phase: "failed" };

/**
 * The large photo, one at a time (designsystem §3 Foton): a layer with the Back row "‹ {backLabel}" and ⋯, the photo
 * fitted to the width (its size known before it loads, so nothing jumps), the caption under it in body text and
 * "2 av 5 · 14 nov" under that. ‹ and › stand on the photo's sides at the height a landscape photo has its middle, so
 * they stay put from a landscape to a portrait photo; ← and → step too, a sideways swipe steps on a touch screen, and
 * Esc closes (`onClose`, as the Back does). At either end the step is held off, drawn in --sk-border.
 *
 * The photo is fetched only when it is shown (`load(id)`, through the host bridge: a tool call), with the thumbnail
 * blurred in its place until it comes. A failed fetch keeps the thumbnail and offers "Försök igen". The viewer draws
 * only `data:image/…` sources and logs nothing about them.
 */
export function PhotoViewer({
  photos,
  currentId,
  onChange,
  onClose,
  load,
  backLabel,
  locale,
  actions,
  keys = true,
}: {
  photos: readonly Photo[];
  /** The photo on screen. Unknown ids show the first photo. */
  currentId: string;
  /** A step: the photo to show now. */
  onChange: (id: string) => void;
  /** Back, Esc. The caller gives the focus back to the photo's tile (`[data-photo-id]`). */
  onClose: () => void;
  /** Fetches the large photo of `id`. */
  load: (id: string) => Promise<PhotoSource>;
  /** The entry the photos belong to: "‹ {backLabel}". */
  backLabel: string;
  locale: string;
  /** The ⋯ entries; no ⋯ without them. */
  actions?: readonly PhotoViewerAction[];
  /** The arrow keys and Esc (fullscreen); off where another layer is on top. */
  keys?: boolean;
}) {
  const labels = photoLabelsFor(locale);
  const found = photos.findIndex((photo) => photo.id === currentId);
  const index = Math.max(0, found);
  const photo = photos[index];
  const id = photo?.id ?? "";

  const [kept] = useState(() => new Map<string, string>());
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    if (!id || kept.has(id)) return undefined;
    let live = true;
    new Promise<PhotoSource>((resolve) => resolve(loadRef.current(id)))
      .then(toPhotoSrc)
      .then(
        (src) => {
          if (src) {
            kept.delete(id);
            kept.set(id, src);
            while (kept.size > KEEP) {
              const oldest = kept.keys().next().value as string;
              kept.delete(oldest);
            }
          }
          if (live)
            setLoaded(
              src ? { id, phase: "ready", src } : { id, phase: "failed" },
            );
        },
        // The cause is not kept or logged: it may name the photo's address.
        () => {
          if (live) setLoaded({ id, phase: "failed" });
        },
      );
    return () => {
      live = false;
    };
  }, [id, attempt, kept]);

  const src =
    kept.get(id) ??
    (loaded?.id === id && loaded.phase === "ready" ? loaded.src : null);
  const failed = !src && loaded?.id === id && loaded.phase === "failed";

  const step = (by: -1 | 1) => {
    const next = photos[index + by];
    if (next) onChange(next.id);
  };
  const [menuOpen, setMenuOpen] = useState(false);
  useShortcuts(
    {
      ArrowLeft: () => step(-1),
      ArrowRight: () => step(1),
      Escape: onClose,
    },
    // Before the shell's own Esc (which closes the record beside a list): the viewer is the layer on top.
    { enabled: keys && !menuOpen && Boolean(photo), capture: true },
  );

  const figure = useRef<HTMLElement | null>(null);
  useEffect(() => {
    figure.current?.focus({ preventScroll: true });
  }, []);

  const swipe = useRef<{ x: number; y: number; pointer: number } | null>(null);
  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (event.pointerType === "mouse") return;
    swipe.current = {
      x: event.clientX,
      y: event.clientY,
      pointer: event.pointerId,
    };
  };
  const onPointerUp = (event: PointerEvent<HTMLElement>) => {
    const start = swipe.current;
    swipe.current = null;
    if (!start || start.pointer !== event.pointerId) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (Math.abs(dx) < SWIPE_PX || Math.abs(dx) < 1.5 * Math.abs(dy)) return;
    // A swipe to the left brings the next photo, as a page is turned (in a right-to-left script the other way).
    const rtl = getComputedStyle(event.currentTarget).direction === "rtl";
    step(dx < 0 !== rtl ? 1 : -1);
  };

  const more = useRef<HTMLButtonElement | null>(null);
  const menuId = useId();
  if (!photo) return null;

  const name = photoAlt(photo, index, locale);
  const caption = photoCaption(photo);
  const day = photo.date ? photoDayLabel(photo.date, locale) : null;
  const position = labels.position(index + 1, photos.length);
  const preview = safePhotoSrc(photo.thumb);
  const first = index === 0;
  const last = index === photos.length - 1;
  const stage = {
    "--sk-photo-ratio": String(1 / stageRatio(photo)),
  } as CSSProperties;

  return (
    <section className="sk-photo-viewer" aria-label={labels.photos}>
      <BackHeader
        label={backLabel}
        onBack={onClose}
        actions={
          actions?.length ? (
            <button
              ref={more}
              type="button"
              className="sk-iconbtn"
              aria-label={labels.moreActions}
              aria-expanded={menuOpen}
              aria-controls={menuOpen ? menuId : undefined}
              onClick={() => setMenuOpen(!menuOpen)}
              onKeyDown={menuButtonKeys(menuOpen, setMenuOpen)}
            >
              <MoreIcon />
            </button>
          ) : undefined
        }
      />
      {menuOpen && actions?.length ? (
        <Menu id={menuId} anchor={more} onClose={() => setMenuOpen(false)}>
          {actions.map((action) => (
            <MenuItem
              key={action.label}
              label={action.label}
              danger={action.danger}
              disabled={action.disabled}
              onChoose={() => {
                setMenuOpen(false);
                more.current?.focus();
                action.onChoose(photo);
              }}
            />
          ))}
        </Menu>
      ) : null}
      <figure
        ref={figure}
        className="sk-photo-viewer__figure"
        tabIndex={-1}
        aria-busy={!src && !failed ? true : undefined}
      >
        <div
          className="sk-photo-viewer__stage"
          style={stage}
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          onPointerCancel={() => {
            swipe.current = null;
          }}
        >
          {src ? (
            <img
              key={`${id}:large`}
              className="sk-photo-viewer__img"
              src={src}
              alt={name}
              decoding="async"
              draggable={false}
              width={photo.width}
              height={photo.height}
            />
          ) : preview ? (
            <img
              key={`${id}:preview`}
              className="sk-photo-viewer__img sk-photo-viewer__img--preview"
              src={preview}
              alt={name}
              draggable={false}
            />
          ) : (
            <span
              className="sk-photo-viewer__blank"
              role="img"
              aria-label={name}
            />
          )}
          <button
            type="button"
            className="sk-photo-viewer__step sk-photo-viewer__step--prev"
            aria-label={labels.previous}
            aria-disabled={first || undefined}
            onClick={() => step(-1)}
          >
            <ChevronLeftIcon />
          </button>
          <button
            type="button"
            className="sk-photo-viewer__step sk-photo-viewer__step--next"
            aria-label={labels.next}
            aria-disabled={last || undefined}
            onClick={() => step(1)}
          >
            <ChevronRightIcon />
          </button>
        </div>
        {caption ? (
          <figcaption className="sk-photo-viewer__caption">
            {caption}
          </figcaption>
        ) : null}
      </figure>
      <p className="sk-photo-viewer__meta" aria-live="polite">
        {day ? `${position} · ${day}` : position}
      </p>
      {!src && !failed ? (
        <p className="sk-photo-viewer__status" role="status">
          {labels.loading}
        </p>
      ) : null}
      {failed ? (
        <ErrorNotice
          locale={locale}
          placement="row"
          message={labels.loadError}
          onRetry={() => {
            setLoaded(null);
            setAttempt((value) => value + 1);
          }}
        />
      ) : null}
    </section>
  );
}
