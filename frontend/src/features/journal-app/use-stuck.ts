import { useEffect, useRef, useState } from "react";

/**
 * Whether a sticky element is stuck, that is, held down from where it stands in the flow. A zero-height `marker` sits
 * right before it; when the element's top is under the marker's, the element has been pushed by the scroll. Any scroll
 * in the document counts (the page or a pane), and so does a resize.
 */
export function useStuck<E extends HTMLElement>() {
  const marker = useRef<HTMLSpanElement>(null);
  const element = useRef<E>(null);
  const [stuck, setStuck] = useState(false);
  useEffect(() => {
    const check = () => {
      const mark = marker.current;
      const sticky = element.current;
      if (!mark || !sticky) return;
      setStuck(
        sticky.getBoundingClientRect().top >
          mark.getBoundingClientRect().top + 0.5,
      );
    };
    check();
    document.addEventListener("scroll", check, {
      capture: true,
      passive: true,
    });
    window.addEventListener("resize", check);
    return () => {
      document.removeEventListener("scroll", check, { capture: true });
      window.removeEventListener("resize", check);
    };
  }, []);
  return { marker, element, stuck };
}
