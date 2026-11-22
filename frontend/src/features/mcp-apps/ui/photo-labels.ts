/**
 * Texts of the photo tiles and the photo viewer (photos.tsx, photo-viewer.tsx): sv and en with equal keys. They
 * follow the room's locale, as the read error does (states.tsx), so the components carry no app catalogue.
 */
const photoEn = {
  /** The list of tiles, for assistive technology. */
  photos: "Photos",
  /** The name of a photo without a caption: its place in the list, and the day when it is known. Never a file name. */
  photo: (n: number) => `Photo ${n}`,
  photoFrom: (n: number, day: string) => `Photo ${n} from ${day}`,
  /** The last tile when there are more photos than room: "+3" on the tile, this as its name. */
  more: (n: number) => (n === 1 ? "1 more photo" : `${n} more photos`),
  /** The viewer's steps and its place in the set. */
  previous: "Previous photo",
  next: "Next photo",
  position: (i: number, n: number) => `${i} of ${n}`,
  /** The viewer's ⋯. */
  moreActions: "More options",
  /** While the large photo is fetched. */
  loading: "Loading photo…",
  /** The large photo could not be fetched (the thumbnail stays). */
  loadError: "Couldn’t load the photo",
};

export type PhotoLabels = typeof photoEn;

const photoSv: PhotoLabels = {
  photos: "Foton",
  photo: (n) => `Foto ${n}`,
  photoFrom: (n, day) => `Foto ${n} från ${day}`,
  more: (n) => (n === 1 ? "1 foto till" : `${n} foton till`),
  previous: "Föregående foto",
  next: "Nästa foto",
  position: (i, n) => `${i} av ${n}`,
  moreActions: "Fler val",
  loading: "Hämtar fotot…",
  loadError: "Fotot kunde inte hämtas",
};

/** The texts for a room's locale ("sv-SE" or "en-GB"); Swedish unless the locale is English. */
export function photoLabelsFor(locale: string): PhotoLabels {
  return locale.startsWith("en") ? photoEn : photoSv;
}

export { photoEn, photoSv };
