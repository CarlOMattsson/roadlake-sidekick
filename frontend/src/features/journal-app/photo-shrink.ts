/**
 * Shrinks a photo the owner chose before it leaves the device (ADR-014): a long edge of at most 2048 px and at most
 * 4 MiB as JPEG, plus a thumbnail of at most 320 px and 128 KiB. Drawing the picture on a canvas and encoding it again
 * leaves every metadata block of the file behind (location, camera, time); the server's strict parser refuses a file
 * that still carries one. The picture is turned upright when it is decoded (the browser reads the file's orientation),
 * so the pixels already stand the right way.
 *
 * The browser's image calls sit behind `ImageIo`, so the sizes and the quality steps are tested without a canvas.
 * Nothing here logs bytes, names or sizes.
 */

export const MAX_PHOTO_EDGE = 2048;
export const MAX_PHOTO_BYTES = 4 * 1024 * 1024;
export const MAX_THUMBNAIL_EDGE = 320;
export const MAX_THUMBNAIL_BYTES = 128 * 1024;
/** What a picture the browser cannot read, or one that stays too large after every step, is refused with. */
export type ShrinkFailure = "unreadable" | "too_large";

export class ShrinkError extends Error {
  constructor(readonly reason: ShrinkFailure) {
    super(reason);
    this.name = "ShrinkError";
  }
}

/** The quality steps tried in turn; the first encoding that fits its byte limit wins. */
const QUALITY_STEPS = [0.85, 0.7, 0.55, 0.4] as const;

/** A decoded picture: its size and a way to draw it at another size. */
export type DecodedImage = {
  width: number;
  height: number;
  /** The picture as JPEG at `width` by `height` and `quality` (0 to 1). */
  encode: (width: number, height: number, quality: number) => Promise<Blob>;
  close: () => void;
};

export type ImageIo = {
  /** Decodes the file, upright; rejects for a file that is no picture the browser can read. */
  decode: (file: Blob) => Promise<DecodedImage>;
  /** The bytes of a blob as base64, without a prefix. */
  toBase64: (blob: Blob) => Promise<string>;
};

export type ShrunkPhoto = {
  /** Base64 of the JPEG, no `data:` prefix. */
  photo: string;
  thumbnail: string;
  width: number;
  height: number;
  mediaType: "image/jpeg";
};

/** The size that fits `width` by `height` inside a square of `edge`, in whole pixels, keeping the shape; never larger. */
export function fitWithin(
  width: number,
  height: number,
  edge: number,
): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= edge) return { width, height };
  const scale = edge / longest;
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

async function encodeWithin(
  image: DecodedImage,
  edge: number,
  limit: number,
): Promise<{ blob: Blob; width: number; height: number }> {
  let { width, height } = fitWithin(image.width, image.height, edge);
  // A step in quality first, then a smaller picture, until it fits: a very large photo still goes in.
  for (let shrink = 0; shrink < 4; shrink += 1) {
    for (const quality of QUALITY_STEPS) {
      const blob = await image.encode(width, height, quality);
      if (blob.size <= limit) return { blob, width, height };
    }
    ({ width, height } = fitWithin(
      width,
      height,
      Math.max(1, Math.floor(Math.max(width, height) * 0.75)),
    ));
  }
  throw new ShrinkError("too_large");
}

/** Shrinks `file` to the photo and thumbnail the server takes. Throws `ShrinkError` for a file that cannot be used. */
export async function shrinkPhoto(
  file: Blob,
  /** The most bytes the photo may take: the server's 4 MiB, or less where one call carries it (a tool call: 1 MiB). */
  maxBytes: number = MAX_PHOTO_BYTES,
  io: ImageIo = browserImageIo,
): Promise<ShrunkPhoto> {
  let image: DecodedImage;
  try {
    image = await io.decode(file);
  } catch {
    throw new ShrinkError("unreadable");
  }
  try {
    if (!(image.width > 0 && image.height > 0))
      throw new ShrinkError("unreadable");
    const photo = await encodeWithin(
      image,
      MAX_PHOTO_EDGE,
      Math.min(maxBytes, MAX_PHOTO_BYTES),
    );
    const thumb = await encodeWithin(
      image,
      MAX_THUMBNAIL_EDGE,
      MAX_THUMBNAIL_BYTES,
    );
    return {
      photo: await io.toBase64(photo.blob),
      thumbnail: await io.toBase64(thumb.blob),
      width: photo.width,
      height: photo.height,
      mediaType: "image/jpeg",
    };
  } catch (error) {
    // A canvas or reader that failed is a picture that could not be used.
    throw error instanceof ShrinkError ? error : new ShrinkError("unreadable");
  } finally {
    image.close();
  }
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = typeof reader.result === "string" ? reader.result : "";
      const comma = text.indexOf(",");
      if (comma < 0) reject(new Error("unreadable"));
      else resolve(text.slice(comma + 1));
    };
    reader.onerror = () => reject(new Error("unreadable"));
    reader.readAsDataURL(blob);
  });
}

/** The browser's own decoder and canvas: the real `ImageIo`. */
export const browserImageIo: ImageIo = {
  async decode(file) {
    const bitmap = await createImageBitmap(file, {
      imageOrientation: "from-image",
    });
    return {
      width: bitmap.width,
      height: bitmap.height,
      close: () => bitmap.close(),
      encode: (width, height, quality) =>
        new Promise<Blob>((resolve, reject) => {
          const canvas = document.createElement("canvas");
          canvas.width = width;
          canvas.height = height;
          const context = canvas.getContext("2d");
          if (!context) {
            reject(new Error("unreadable"));
            return;
          }
          // JPEG has no transparency: a transparent PNG would turn black without a white ground.
          context.fillStyle = "#fff";
          context.fillRect(0, 0, width, height);
          context.drawImage(bitmap, 0, 0, width, height);
          canvas.toBlob(
            (blob) => (blob ? resolve(blob) : reject(new Error("unreadable"))),
            "image/jpeg",
            quality,
          );
        }),
    };
  },
  toBase64,
};
