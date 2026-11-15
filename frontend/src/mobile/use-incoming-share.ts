/**
 * The text another app shared to Sidekick, as the page holds it. The native side keeps a share until the page takes it
 * (`takeShare`, once), so it is taken when the app starts and again on `shareReceived`, when text is shared to the
 * running app. It is held above the pairing gate: a share that arrives before the phone is paired waits there, and the
 * sheet opens once the app is. Nothing is stored; the text lives in this state until the sheet closes.
 */
import { useCallback, useEffect, useState } from "react";

import type { SharedText, SidekickNativePlugin } from "./sidekick-native";

export type IncomingShareNative = Pick<
  SidekickNativePlugin,
  "takeShare" | "addListener"
>;

export type IncomingShare = {
  /** The shared text, with a counter so that a second share opens a fresh sheet. */
  share: { text: SharedText; n: number } | undefined;
  /** The sheet closed (saved or cancelled). */
  clear: () => void;
};

export function useIncomingShare(native: IncomingShareNative): IncomingShare {
  const [share, setShare] = useState<IncomingShare["share"]>();

  useEffect(() => {
    let live = true;
    const take = () => {
      native.takeShare().then(
        (taken) => {
          const text = taken.share;
          if (live && text)
            setShare((current) => ({ text, n: (current?.n ?? 0) + 1 }));
        },
        // A phone that cannot answer has nothing shared.
        () => undefined,
      );
    };
    take();
    const handle = native.addListener("shareReceived", take);
    return () => {
      live = false;
      void handle.then((registered) => registered.remove());
    };
  }, [native]);

  const clear = useCallback(() => setShare(undefined), []);
  return { share, clear };
}
