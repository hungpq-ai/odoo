from . import models


def _post_init_hook(env):
    """Auto-connect MCP servers after module installation/update."""
    env["llm.mcp.server"]._auto_connect_servers()
