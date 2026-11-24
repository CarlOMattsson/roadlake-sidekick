import {
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { onEnterKey, preventSubmit } from "../mcp-apps/ui/enter-key";
import { PlusIcon } from "../mcp-apps/ui/icons";
import { PhotoGrid, type Photo } from "../mcp-apps/ui/photos";
import { PhotoViewer } from "../mcp-apps/ui/photo-viewer";
import type { JournalLabels } from "./labels";
import { shrinkPhoto, type ShrunkPhoto } from "./photo-shrink";
import type { JournalPhotoRecord, PhotoTransport } from "./photo-transport";
import "./journal.css";
import "./day-photos.css";

/** The longest caption the server keeps (MAX_ALT_TEXT). */
export const CAPTION_MAX = 500;

/** A photo as the shared tiles and viewer take it: its thumbnail and what the server says about it. */
function tileOf(record: JournalPhotoRecord, thumb: string | undefined): Photo {
  return {
    id: record.id,
    thumb,
    alt: record.alt_text ?? undefined,
    date: record.journal_date ?? undefined,
    width: record.width,
    height: record.height,
    taken_at: record.taken_at ?? undefined,
    location: record.location
      ? {
          lat: record.location.lat,
          lon: record.location.lon,
          name: record.location.name ?? undefined,
        }
      : undefined,
    camera: record.camera ?? undefined,
    orientation: record.orientation ?? undefined,
  };
}

const dataUrl = (mediaType: string, base64: string) =>
  `data:${mediaType};base64,${base64}`;

/** The day's thumbnails, read one by one as the ids change; a failed one stays a tile without a picture. */
function useThumbnails(transport: PhotoTransport, ids: readonly string[]) {
  const [tiles, setTiles] = useState<ReadonlyMap<string, Photo>>(new Map());
  const [failed, setFailed] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const read = transport.readPhoto;
  const key = ids.join(",");
  useEffect(() => {
    if (!read || !key) return undefined;
    let live = true;
    const wanted = key.split(",");
    let missed = 0;
    void Promise.all(
      wanted.map((id) =>
        read(id, "thumb").then(
          ({ photo, data }) => {
            if (live)
              setTiles((now) =>
                new Map(now).set(
                  id,
                  tileOf(photo, dataUrl(photo.media_type, data)),
                ),
              );
          },
          () => {
            missed += 1;
          },
        ),
      ),
    ).then(() => {
      if (live) setFailed(missed);
    });
    return () => {
      live = false;
    };
  }, [read, key, attempt]);
  return { tiles, failed, retry: () => setAttempt((n) => n + 1) };
}

type Adding =
  | { phase: "preparing" }
  | { phase: "ready"; photo: ShrunkPhoto }
  | { phase: "saving"; photo: ShrunkPhoto }
  | { phase: "failed"; photo: ShrunkPhoto }
  | { phase: "unreadable" };

/** The add row: choose a file, see it prepared, give it a caption, add it. Absent without the host's photo tools. */
function AddPhoto({
  transport,
  labels: t,
  journalDate,
  onAdded,
}: {
  transport: PhotoTransport;
  labels: JournalLabels;
  journalDate: string;
  onAdded: () => void;
}) {
  const [adding, setAdding] = useState<Adding>();
  const [caption, setCaption] = useState("");
  const pending = useRef<PendingKey>(undefined);
  const chooser = useRef<HTMLInputElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const captionId = useId();
  const hintId = useId();
  const add = transport.addDayPhoto;
  if (!add) return null;

  function choose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // The same file can be chosen again afterwards.
    event.target.value = "";
    if (!file) return;
    setAdding({ phase: "preparing" });
    setCaption("");
    pending.current = undefined;
    shrinkPhoto(file, transport.maxPhotoBytes?.()).then(
      (photo) => setAdding({ phase: "ready", photo }),
      // A file that is no picture, or too large to shrink, is told so; the cause is never kept.
      () => setAdding({ phase: "unreadable" }),
    );
  }

  function close() {
    setAdding(undefined);
    // The focus returns to where the choice began.
    requestAnimationFrame(() => addButton.current?.focus());
  }

  function save(photo: ShrunkPhoto) {
    if (!add) return;
    const altText = caption.trim() || undefined;
    const signature = [
      journalDate,
      altText ?? "",
      photo.photo.length,
      photo.photo.slice(0, 48),
      photo.photo.slice(-48),
    ].join("|");
    pending.current = keyFor(pending.current, signature);
    setAdding({ phase: "saving", photo });
    add(
      {
        journalDate,
        photo: photo.photo,
        thumbnail: photo.thumbnail,
        altText,
      },
      pending.current.key,
    ).then(
      () => {
        setAdding(undefined);
        setCaption("");
        pending.current = undefined;
        onAdded();
      },
      () => setAdding({ phase: "failed", photo }),
    );
  }

  const photo = adding && "photo" in adding ? adding.photo : undefined;
  const busy = adding?.phase === "preparing" || adding?.phase === "saving";
  return (
    <div className="journal-photos-add">
      <input
        ref={chooser}
        type="file"
        accept="image/*"
        hidden
        tabIndex={-1}
        onChange={choose}
      />
      {adding === undefined && (
        <button
          ref={addButton}
          type="button"
          className="sk-btn--quiet journal-photos-add-button"
          onClick={() => chooser.current?.click()}
        >
          <PlusIcon />
          <span>
            {t.photosAdd}{" "}
            <span className="journal-photos-hint">{t.photosAddHint}</span>
          </span>
        </button>
      )}
      {adding?.phase === "preparing" && (
        <p role="status" className="journal-muted">
          {t.photosPreparing}
        </p>
      )}
      {adding?.phase === "unreadable" && (
        <div role="alert" className="journal-photos-problem">
          <p>{t.photosUnreadable}</p>
          <button type="button" className="sk-btn--quiet" onClick={close}>
            {t.photosCancel}
          </button>
        </div>
      )}
      {photo && (
        <form className="journal-photos-form" onSubmit={preventSubmit}>
          <img
            className="journal-photos-preview"
            src={dataUrl(photo.mediaType, photo.thumbnail)}
            alt=""
          />
          <label htmlFor={captionId}>{t.photosCaption}</label>
          <input
            id={captionId}
            type="text"
            maxLength={CAPTION_MAX}
            aria-describedby={hintId}
            value={caption}
            disabled={busy}
            onChange={(event) => setCaption(event.target.value)}
            onKeyDown={(event) =>
              onEnterKey(event, () => {
                if (!busy) save(photo);
              })
            }
          />
          <p id={hintId} className="journal-photos-hint">
            {t.photosCaptionHint}
          </p>
          {adding?.phase === "saving" && (
            <p role="status" className="journal-muted">
              {t.photosSaving}
            </p>
          )}
          {adding?.phase === "failed" && (
            <p role="alert" className="journal-photos-problem">
              {t.photosFailed}
            </p>
          )}
          <div className="journal-actions">
            <button
              type="button"
              className="sk-btn--primary"
              disabled={busy}
              onClick={() => save(photo)}
            >
              {adding?.phase === "failed" ? t.photosRetry : t.photosSave}
            </button>
            <button
              type="button"
              className="sk-btn--quiet"
              disabled={busy}
              onClick={close}
            >
              {t.photosCancel}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

type DayPhotosInput = {
  transport: PhotoTransport;
  labels: JournalLabels;
  journalDate: string;
  /** The ids of the photos on the day (`day_attachments.ids`); none from an older server. */
  ids: readonly string[];
  /** The viewer's arrow keys and Esc work in fullscreen only. */
  fullscreen: boolean;
  /** A photo was added: the view reads the day again and confirms. */
  onAdded: () => void;
};

/**
 * The day's photos: the block under the day's summary (the tiles and the add row), and the viewer, which the day
 * view puts in place of the day while a photo is open. Both are null where the host has no photo tools.
 */
export function useDayPhotos({
  transport,
  labels: t,
  journalDate,
  ids,
  fullscreen,
  onAdded,
}: DayPhotosInput): { block: ReactNode; viewer: ReactNode } {
  const offered = transport.addDayPhoto !== undefined;
  const { tiles, failed, retry } = useThumbnails(offered ? transport : {}, ids);
  const [open, setOpen] = useState<string>();
  if (!offered) return { block: null, viewer: null };

  const photos = ids.map((id) => tiles.get(id) ?? { id, date: journalDate });
  const read = transport.readPhoto;
  const viewer =
    open && read ? (
      <PhotoViewer
        photos={photos}
        currentId={open}
        onChange={setOpen}
        onClose={() => {
          const id = open;
          setOpen(undefined);
          // The focus goes back to the tile the viewer was opened from.
          requestAnimationFrame(() =>
            document
              .querySelector<HTMLElement>(`[data-photo-id="${id}"]`)
              ?.focus(),
          );
        }}
        load={(id) =>
          read(id, "photo").then(({ photo, data }) =>
            dataUrl(photo.media_type, data),
          )
        }
        backLabel={t.photosBack}
        locale={t.dateLocale}
        keys={fullscreen}
      />
    ) : null;

  const block = (
    <section className="journal-photos">
      <PhotoGrid
        photos={photos}
        locale={t.dateLocale}
        layout="fill"
        onOpen={setOpen}
      />
      {failed > 0 && (
        <p role="status" className="journal-muted">
          {t.photosLoadFailed}{" "}
          <button type="button" className="sk-more" onClick={retry}>
            {t.photosRetry}
          </button>
        </p>
      )}
      <AddPhoto
        transport={transport}
        labels={t}
        journalDate={journalDate}
        onAdded={onAdded}
      />
    </section>
  );
  return { block, viewer };
}
