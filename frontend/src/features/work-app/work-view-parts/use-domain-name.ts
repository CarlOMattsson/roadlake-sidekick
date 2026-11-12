import { useEffect, useState } from "react";
import { toolOffered } from "../../mcp-apps/tool-support";
import type { WorkTransport } from "../transport";

/**
 * The name of the Domain a Project or Process belongs to, for the "Hem · 1 av 3 klara" line. It is a nicety, not
 * part of the record: until it is read, or when the read fails or the host cannot answer get_domain, the name is
 * undefined and the line simply goes without it (no error is shown).
 */
export function useDomainName(
  transport: WorkTransport,
  domainId: string | undefined,
): string | undefined {
  const [found, setFound] = useState<{ id: string; name: string }>();
  const offered = toolOffered(transport, "get_domain");
  useEffect(() => {
    if (!domainId || !offered) return undefined;
    let live = true;
    // The call runs inside a promise chain so a transport that throws at once is a failed read too.
    Promise.resolve()
      .then(() => transport.getDomain(domainId))
      .then((result) => {
        if (live) setFound({ id: domainId, name: result.domain.name });
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [transport, domainId, offered]);
  return found && found.id === domainId ? found.name : undefined;
}
