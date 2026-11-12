"""Curated FastMCP transport adapter."""

# Where the public MCP application is mounted in the API process. The OAuth proxy's own routes
# (authorize, token, register, consent, auth/callback) live under the same prefix.
MCP_MOUNT_PATH = "/mcp"
