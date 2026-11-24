/**
 * The sentences of the day's photos: the add row, the caption step, the progress and the failures, and the name of the
 * block's way back. Spread into journalEn and journalSv (label-parts.ts). A photo's own names ("Foto 1") and the
 * viewer's texts come with the shared tiles (ui/photo-labels.ts).
 */
export const dayPhotoEn = {
  photosAdd: "Add photo",
  photosAddHint: "From the camera or your pictures.",
  photosCaption: "Caption (optional)",
  photosCaptionHint:
    "Describe the photo for someone who can’t see it. It stays out of Claude’s memory.",
  photosSave: "Add to the day",
  photosCancel: "Cancel",
  photosPreparing: "Preparing the photo…",
  photosSaving: "Adding the photo…",
  photosAdded: "Photo added to the day.",
  photosUnreadable: "That file isn’t a picture that can be used.",
  photosFailed: "Couldn’t add the photo. Try again.",
  photosLoadFailed: "Some photos couldn’t be loaded.",
  photosRetry: "Try again",
  /** The viewer's back row: "‹ The day". */
  photosBack: "The day",
};

export const dayPhotoSv: typeof dayPhotoEn = {
  photosAdd: "Lägg till foto",
  photosAddHint: "Från kameran eller dina bilder.",
  photosCaption: "Bildtext (valfri)",
  photosCaptionHint:
    "Beskriv fotot för den som inte ser det. Den hålls utanför Claudes minne.",
  photosSave: "Lägg till på dagen",
  photosCancel: "Avbryt",
  photosPreparing: "Förbereder fotot…",
  photosSaving: "Lägger till fotot…",
  photosAdded: "Fotot lades till på dagen.",
  photosUnreadable: "Filen är ingen bild som går att använda.",
  photosFailed: "Det gick inte att lägga till fotot. Försök igen.",
  photosLoadFailed: "Några foton kunde inte hämtas.",
  photosRetry: "Försök igen",
  photosBack: "Dagen",
};
