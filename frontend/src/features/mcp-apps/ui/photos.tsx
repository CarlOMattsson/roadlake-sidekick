import { useEffect, useRef, useState } from "react";

import { PhotoIcon } from "./icons";
import { photoLabelsFor } from "./photo-labels";

import "./photos.css";

/**
 * Photo tiles (designsystem §3 Foton): square thumbnails with radius 8 and 8 between them, as a strip on a card or a
 * week day (`PhotoStrip`, 64 or 40) and as a grid in a day or an entry (`PhotoGrid`, 72 that fill the row, or three
 * and four columns). The images come in as props, already in the tool result: the app makes no network request and
 * draws only `data:image/…` sources (the host's CSP allows `img-src 'self' data:` and nothing else). Any other address
 * is refused and the tile shows the photo glyph instead, so a stray URL never becomes a request. Nothing here logs a
 * source.
 *
 * Every photo has a name: its caption, or "Foto {n} från {dag}" when it has none (never a file name).
 */

export type Photo = {
  id: string;
  /** The thumbnail: a `data:image/…` URL (about 96 px on its longest side). */
  thumb?: string;
  /** The caption, which is also the image's text alternative. */
  alt?: string;
  /** The calendar day (YYYY-MM-DD) the photo belongs to, for the name of a photo without a caption. */
  date?: string;
  /** The large photo's size in pixels, so the viewer keeps its place while the photo loads. */
  width?: number;
  height?: number;
  /**
   * What the app read from the file before it was shrunk, kept as fields beside the clean image (never inside it).
   * Only the viewer shows them; the tiles never do. `taken_at` is ISO 8601: with an offset it is shown in the reader's
   * time, without one as the camera's wall clock.
   */
  taken_at?: string;
  /** Where it was taken: the place name on the viewer's meta line, the coordinates only in its details. */
  location?: PhotoLocation;
  /** The camera or phone ("Pixel 8 Pro"). */
  camera?: string;
  /**
   * The file's orientation (EXIF 1–8), kept as data and not drawn: the image was turned upright when it was
   * re-encoded, so its pixels already stand the right way.
   */
  orientation?: number;
};

export type PhotoLocation = {
  /** Degrees, WGS 84. */
  lat: number;
  lon: number;
  /** The place name, when one is known ("Visby"). */
  name?: string;
};

const RASTER =
  /^data:image\/(?:png|jpeg|webp|gif|avif);base64,[a-z0-9+/=\s]+$/i;

/**
 * `src` when it is a raster image inline in the document (`data:image/png|jpeg|webp|gif|avif;base64,…`); null for
 * anything else: an http(s), blob or file address would be a request the host's CSP blocks (or worse, one it lets
 * through), and an SVG can carry more than a picture.
 */
export function safePhotoSrc(src: string | null | undefined): string | null {
  return typeof src === "string" && RASTER.test(src) ? src : null;
}

/** A caption that is only a camera's or a phone's file name ("IMG_2041.HEIC", "PXL_20261114_0930.jpg"). */
const FILE_NAME =
  /^(?:[^\s/\\]+\.(?:jpe?g|png|gif|webp|heic|heif|avif|tiff?|bmp|dng)|(?:img|dsc|dscn|pxl|photo|image|screenshot)[_-]?[\d_-]+)$/i;

/** "14 nov" / "14 Nov": the day of a photo without its year, as a row's meta line writes it. */
export function photoDayLabel(date: string, locale: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    .toLocaleDateString(locale, { day: "numeric", month: "short" })
    .replace(/\.$/, "");
}

const TAKEN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$/i;

/**
 * When a photo was taken, in words: "14 nov 09:30" on the viewer's meta line (`short`), "14 november 2026 09:30" in
 * its details (`long`). The time is the camera's wall clock where the photo was taken, as the ISO value writes it: an
 * offset is not converted, so a photo from a trip keeps its morning. Null for anything that is not a date and time.
 */
export function photoTakenLabel(
  value: string | null | undefined,
  locale: string,
  form: "short" | "long" = "short",
): string | null {
  const match = typeof value === "string" ? TAKEN.exec(value.trim()) : null;
  if (!match) return null;
  const [year, month, day, hour, minute] = match.slice(1, 6).map(Number) as [
    number,
    number,
    number,
    number,
    number,
  ];
  const taken = new Date(year, month - 1, day, hour, minute);
  // 2026-02-30 or 25:00 rolls over in Date; a camera never writes it, so it is not shown.
  if (taken.getDate() !== day || hour > 23 || minute > 59) return null;
  const date = taken
    .toLocaleDateString(locale, {
      day: "numeric",
      month: form === "long" ? "long" : "short",
      ...(form === "long" ? { year: "numeric" as const } : {}),
    })
    .replace(/\.$/, "");
  const time = taken.toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${date} ${time}`;
}

/** The location when its coordinates are real degrees, or null, so nothing half-made is shown. */
export function photoLocation(photo: Photo): PhotoLocation | null {
  const where = photo.location;
  if (!where) return null;
  const { lat, lon } = where;
  if (
    !Number.isFinite(lat) ||
    !Number.isFinite(lon) ||
    Math.abs(lat) > 90 ||
    Math.abs(lon) > 180
  )
    return null;
  const name = where.name?.trim();
  return name ? { lat, lon, name } : { lat, lon };
}

/**
 * The coordinates in words, four decimals (about 10 m): "57,6348° N, 18,2948° Ö" in Swedish, "57.6348° N,
 * 18.2948° E" in English. Only the viewer's details show them: no tile, row or card does, and nothing links to a map.
 */
export function photoCoordinates(where: PhotoLocation, locale: string): string {
  const [north, south, east, west] = photoLabelsFor(locale).compass;
  const degrees = (value: number) =>
    `${Math.abs(value).toLocaleString(locale, {
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    })}°`;
  return `${degrees(where.lat)} ${where.lat < 0 ? south : north}, ${degrees(where.lon)} ${where.lon < 0 ? west : east}`;
}

/** The caption to show under a photo, or null when it has none (or only a file name). */
export function photoCaption(photo: Photo): string | null {
  const caption = photo.alt?.trim() ?? "";
  return caption && !FILE_NAME.test(caption) ? caption : null;
}

/**
 * The photo's name: its caption, or for a photo without one (or whose caption is only a file name) "Foto {n}",
 * with "från {dag}" when the day is known. `index` is the photo's place in its set, from 0.
 */
export function photoAlt(photo: Photo, index: number, locale: string): string {
  const caption = photoCaption(photo);
  if (caption) return caption;
  const labels = photoLabelsFor(locale);
  const day = photo.date ? photoDayLabel(photo.date, locale) : null;
  return day ? labels.photoFrom(index + 1, day) : labels.photo(index + 1);
}

/** The tiles that fit in `max`: all of them, or `max - 1` and a last "+n" tile that stands for the rest. */
export function photoSlots(
  photos: readonly Photo[],
  max: number,
): { shown: Photo[]; more: { photo: Photo; count: number } | null } {
  const room = Math.max(1, Math.floor(max));
  if (photos.length <= room) return { shown: [...photos], more: null };
  const shown = photos.slice(0, room - 1);
  const photo = photos[room - 1] as Photo;
  return { shown, more: { photo, count: photos.length - shown.length } };
}

type TilesProps = {
  photos: readonly Photo[];
  /** The room's locale: the photos' names and the "+n" tile's name. */
  locale: string;
  /** A tile was pressed: the room opens the viewer on this photo (inline: the entry in fullscreen with it open). */
  onOpen: (id: string) => void;
  /**
   * The "+n" tile was pressed: the room shows them all (the entry). Without it the "+n" tile opens the viewer on the
   * first photo it stands for, from where the rest are a step away.
   */
  onMore?: () => void;
  /** The list's name for assistive technology; "Foton" by default. */
  label?: string;
};

function PhotoTile({
  photo,
  index,
  locale,
  more,
  onPress,
}: {
  photo: Photo;
  index: number;
  locale: string;
  /** How many photos the tile stands for, when it is the "+n" tile. */
  more?: number;
  onPress: () => void;
}) {
  const src = safePhotoSrc(photo.thumb);
  // A source the browser could not decode. Keyed on the source, so a new thumbnail is tried again.
  const [broken, setBroken] = useState<string | null>(null);
  const drawn = src !== null && broken !== src;
  const name = photoAlt(photo, index, locale);
  const moreName = more ? photoLabelsFor(locale).more(more) : undefined;
  return (
    <button
      type="button"
      className={more ? "sk-photo sk-photo--more" : "sk-photo"}
      data-photo-id={photo.id}
      aria-label={moreName}
      onClick={onPress}
    >
      {drawn ? (
        <img
          className="sk-photo__img"
          src={src}
          alt={more ? "" : name}
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setBroken(src)}
        />
      ) : (
        <span
          className="sk-photo__missing"
          role={more ? undefined : "img"}
          aria-label={more ? undefined : name}
        >
          <PhotoIcon />
        </span>
      )}
      {more ? (
        <span className="sk-photo__count" aria-hidden="true">
          +{more}
        </span>
      ) : null}
    </button>
  );
}

function Tiles({
  photos,
  locale,
  onOpen,
  onMore,
  label,
  max,
  className,
}: TilesProps & { max: number; className: string }) {
  const { shown, more } = photoSlots(photos, max);
  return (
    <ul
      className={className}
      aria-label={label ?? photoLabelsFor(locale).photos}
    >
      {shown.map((photo, index) => (
        <li key={photo.id} className="sk-photos__item">
          <PhotoTile
            photo={photo}
            index={index}
            locale={locale}
            onPress={() => onOpen(photo.id)}
          />
        </li>
      ))}
      {more ? (
        <li key={more.photo.id} className="sk-photos__item">
          <PhotoTile
            photo={more.photo}
            index={shown.length}
            locale={locale}
            more={more.count}
            onPress={() => (onMore ? onMore() : onOpen(more.photo.id))}
          />
        </li>
      ) : null}
    </ul>
  );
}

/**
 * One row of thumbnails: 64 on a journal card inline (the row takes 72 with its air), 40 on a day of the week view.
 * At most `max` tiles (4), the last one "+n" when there are more. Never wraps and never scrolls. 40 is drawn 40 and
 * taps 44: the target reaches 2 into the 8 between tiles on each side. Nothing is drawn without photos.
 */
export function PhotoStrip({
  size = 64,
  max = 4,
  ...props
}: TilesProps & { size?: 64 | 40; max?: number }) {
  if (props.photos.length === 0) return null;
  return (
    <Tiles
      {...props}
      max={max}
      className={`sk-photos sk-photos--strip sk-photos--${size}`}
    />
  );
}

const FILL_TILE = 72;
const FILL_GAP = 8;
/** Before the grid is measured (and where it cannot be: a test without layout), four tiles to the row. */
const FILL_COLUMNS = 4;

/** How many 72 tiles fit in the measured element's width, kept up to date as the frame changes. */
function useFillColumns(enabled: boolean) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [columns, setColumns] = useState(FILL_COLUMNS);
  useEffect(() => {
    const node = ref.current;
    if (!enabled || !node || typeof ResizeObserver === "undefined")
      return undefined;
    const observer = new ResizeObserver(() => {
      const width = node.clientWidth;
      if (width > 0)
        setColumns(
          Math.max(1, Math.floor((width + FILL_GAP) / (FILL_TILE + FILL_GAP))),
        );
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [enabled]);
  return [ref, columns] as const;
}

/**
 * The photos of a day or an entry.
 *
 * - `layout="columns"` (an entry): every photo, square, three to the row in a narrow frame and four from 36 rem (the
 *   detail view on a desktop), 8 between.
 * - `layout="fill"` (the day view's Foton): 72 tiles that fill the row, at most `rows` rows (2); when they do not all
 *   fit, the last tile is "+n".
 *
 * Nothing is drawn without photos: an entry without photos shows only its "+ Lägg till foto" row.
 */
export function PhotoGrid({
  layout = "columns",
  rows = 2,
  ...props
}: TilesProps & { layout?: "columns" | "fill"; rows?: number }) {
  const some = props.photos.length > 0;
  const fill = layout === "fill";
  const [ref, columns] = useFillColumns(fill && some);
  if (!some) return null;
  if (fill)
    return (
      <div className="sk-photos-frame" ref={ref}>
        <Tiles
          {...props}
          max={columns * Math.max(1, Math.floor(rows))}
          className="sk-photos sk-photos--fill"
        />
      </div>
    );
  return (
    <div className="sk-photos-frame">
      <Tiles
        {...props}
        max={props.photos.length}
        className="sk-photos sk-photos--columns"
      />
    </div>
  );
}
