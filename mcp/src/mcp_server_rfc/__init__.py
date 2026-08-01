"""MCP server over the IETF RFC corpus.

Intentionally imports nothing at package level. `python -m mcp_server_rfc.rfc`
is the documented way to reach the corpus CLI (it is how a user syncs a local
mirror), and runpy warns if the submodule has already been imported by the
package's __init__.
"""
