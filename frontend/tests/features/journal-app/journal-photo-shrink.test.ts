import { describe, expect, it, vi } from "vitest";
import {
  MAX_PHOTO_BYTES,
  MAX_THUMBNAIL_BYTES,
  ShrinkError,
  fitWithin,
  shrinkPhoto,
  type DecodedImage,
  type ImageIo,
} from "@/features/journal-app/photo-shrink";

/** An image whose encodings weigh what `weigh` says for the size and quality asked for. */
function imageOf(
  width: number,
  height: number,
  weigh: (width: number, height: number, quality: number) => number,
) {
  const encode = vi.fn((w: number, h: number, quality: number) =>
    Promise.resolve(
      new Blob([new Uint8Array(weigh(w, h, quality))], { type: "image/jpeg" }),
    ),
  );
  const close = vi.fn();
  const image: DecodedImage = { width, height, encode, close };
  const io: ImageIo = {
    decode: () => Promise.resolve(image),
    toBase64: (blob) => Promise.resolve(`b64:${blob.size}`),
  };
  return { io, encode, close };
}

describe("fitWithin", () => {
  it("keeps a picture that already fits", () => {
    expect(fitWithin(800, 600, 2048)).toEqual({ width: 800, height: 600 });
  });
  it("scales the long edge down to the limit and keeps the shape", () => {
    expect(fitWithin(4000, 3000, 2048)).toEqual({ width: 2048, height: 1536 });
    expect(fitWithin(3000, 4000, 2048)).toEqual({ width: 1536, height: 2048 });
  });
  it("never makes a side smaller than one pixel", () => {
    expect(fitWithin(10000, 1, 320)).toEqual({ width: 320, height: 1 });
  });
});

describe("shrinkPhoto", () => {
  it("makes a photo of at most 2048 px and a thumbnail of at most 320 px", async () => {
    const { io, encode, close } = imageOf(4000, 3000, () => 1000);
    const shrunk = await shrinkPhoto(new Blob(["x"]), undefined, io);
    expect(shrunk).toMatchObject({
      width: 2048,
      height: 1536,
      mediaType: "image/jpeg",
    });
    expect(encode).toHaveBeenCalledWith(2048, 1536, 0.85);
    expect(encode).toHaveBeenCalledWith(320, 240, 0.85);
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("lowers the quality, then the size, until the photo fits the limit it was given", async () => {
    // 1 MiB at full size and quality, falling with both: only a smaller picture gets under 600 KiB.
    const { io } = imageOf(4000, 3000, (w, h, q) =>
      Math.round(((w * h) / (2048 * 1536)) * 1024 * 1024 * q),
    );
    const limit = 600 * 1024;
    const shrunk = await shrinkPhoto(new Blob(["x"]), limit, io);
    expect(Number(shrunk.photo.replace("b64:", ""))).toBeLessThanOrEqual(limit);
    expect(shrunk.width).toBeLessThanOrEqual(2048);
  });

  it("never asks for more than the server's own 4 MiB", async () => {
    const { io, encode } = imageOf(1000, 1000, (w, h, q) =>
      q === 0.85 && w === 1000 ? MAX_PHOTO_BYTES + 1 : 10,
    );
    const shrunk = await shrinkPhoto(new Blob(["x"]), 100 * 1024 * 1024, io);
    expect(shrunk.photo).toBe("b64:10");
    expect(encode).toHaveBeenCalledWith(1000, 1000, 0.7);
  });

  it("keeps the thumbnail under 128 KiB", async () => {
    const { io } = imageOf(2000, 2000, (w, _h, q) =>
      w > 160 ? MAX_THUMBNAIL_BYTES + 1 : Math.round(q * 1000),
    );
    const shrunk = await shrinkPhoto(new Blob(["x"]), undefined, io);
    expect(Number(shrunk.thumbnail.replace("b64:", ""))).toBeLessThanOrEqual(
      MAX_THUMBNAIL_BYTES,
    );
  });

  it("refuses a file the browser cannot read, and a picture that stays too large", async () => {
    const unreadable: ImageIo = {
      decode: () => Promise.reject(new Error("not an image")),
      toBase64: () => Promise.resolve(""),
    };
    await expect(
      shrinkPhoto(new Blob(["x"]), undefined, unreadable),
    ).rejects.toMatchObject({ reason: "unreadable" });

    const { io, close } = imageOf(4000, 3000, () => MAX_PHOTO_BYTES + 1);
    await expect(shrinkPhoto(new Blob(["x"]), undefined, io)).rejects.toEqual(
      new ShrinkError("too_large"),
    );
    expect(close).toHaveBeenCalledTimes(1);

    const empty = imageOf(0, 0, () => 1);
    await expect(
      shrinkPhoto(new Blob(["x"]), undefined, empty.io),
    ).rejects.toMatchObject({ reason: "unreadable" });
  });
});
