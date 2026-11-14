import { useMemo } from "react";
import { toolOffered } from "../../../mcp-apps/tool-support";
import { useRead } from "../../../mcp-apps/ui/use-read";
import type { WorkTransport } from "../../transport/transport";

/**
 * The name of the Domain a Project or Process belongs to, for the meta line under the title. It is a nicety, not
 * part of the record: until it is read, or when the read fails or the host cannot answer get_domain, the name is
 * undefined and the line simply goes without it (no error is shown).
 */
export function useDomainName(
  transport: WorkTransport,
  domainId: string | undefined,
): string | undefined {
  const offered = toolOffered(transport, "get_domain");
  const readDomain = useMemo(
    () =>
      domainId && offered
        ? () =>
            transport
              .getDomain(domainId)
              .then((result) => ({ id: domainId, name: result.domain.name }))
        : undefined,
    [transport, domainId, offered],
  );
  const [read] = useRead(readDomain);
  const found = read.phase === "ready" ? read.value : undefined;
  return found && found.id === domainId ? found.name : undefined;
}
