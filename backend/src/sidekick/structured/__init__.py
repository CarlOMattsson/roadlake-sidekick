"""Records and structured results shared by the interfaces over the application use cases.

The MCP tools and the companion API answer the same reads and writes. Their shared records and
`*_structured` functions live here, so neither interface imports the other: `sidekick.api` and
`sidekick.mcp` both depend on this package, and this package depends on neither.
"""
