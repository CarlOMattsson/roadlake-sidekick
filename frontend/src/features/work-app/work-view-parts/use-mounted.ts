import { useEffect, useRef, type RefObject } from "react";

/** A ref that is true while the component is mounted; an answer that arrives later must not set state. */
export function useMounted(): RefObject<boolean> {
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return mounted;
}
