{
    "name": "LLM MCP Client",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "summary": "Connect to external MCP servers for tool integration",
    "description": """
        This module extends Odoo's LLM capabilities by adding support for the
        Model Context Protocol (MCP), enabling AI assistants in Odoo to connect
        with and use tools provided by external MCP-compliant servers.

        Features:
        - Connect to external MCP servers via stdio transport
        - Auto-discover and register tools from MCP servers
        - Execute MCP tools within LLM conversations
        - JSON-RPC 2.0 protocol support
    """,
    "author": "Apexive Solutions LLC",
    "website": "https://github.com/apexive/odoo-llm",
    "license": "LGPL-3",
    "depends": ["base", "llm", "llm_tool"],
    "data": [
        "security/ir.model.access.csv",
        "views/llm_mcp_server_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
