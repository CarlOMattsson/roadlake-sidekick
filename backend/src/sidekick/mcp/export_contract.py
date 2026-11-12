"""Export tool discovery as deterministic JSON."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sidekick.composition import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.config import get_settings


async def export() -> list[dict[str, Any]]:
    container = create_container(get_settings())
    tools = await create_mcp_server(container).list_tools()
    return [
        {
            "name": tool.name,
            **({"_meta": tool.meta} if tool.meta else {}),
            "title": tool.title,
            "description": tool.description,
            "inputSchema": tool.parameters,
            "outputSchema": tool.output_schema,
            "annotations": (
                tool.annotations.model_dump(mode="json", by_alias=True)
                if tool.annotations
                else None
            ),
        }
        for tool in tools
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(asyncio.run(export()), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
