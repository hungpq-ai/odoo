import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMToolMCP(models.Model):
    _inherit = "llm.tool"

    mcp_server_id = fields.Many2one(
        "llm.mcp.server",
        string="MCP Server",
        ondelete="cascade",
        help="The MCP server that provides this tool",
    )

    @api.model
    def _get_available_implementations(self):
        implementations = super()._get_available_implementations()
        implementations.append(("mcp", "MCP Server"))
        return implementations

    def mcp_execute(self, parameters):
        """Execute tool via MCP server"""
        self.ensure_one()

        if not self.mcp_server_id:
            raise UserError(_("This tool is not associated with an MCP server"))

        # Auto-reconnect if not connected
        if not self.mcp_server_id.is_connected:
            _logger.info(f"MCP server '{self.mcp_server_id.name}' not connected, attempting to reconnect...")
            self.mcp_server_id.start_server()

        result = self.mcp_server_id.execute_tool(self.name, parameters)

        if isinstance(result, dict) and "error" in result:
            raise UserError(_("Tool execution failed: %(error)s", error=result["error"]))

        # Handle MCP result format
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if isinstance(content, list):
                # Extract text from content array
                texts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        texts.append(item.get("text", ""))
                return "\n".join(texts) if texts else json.dumps(result)
            return str(content)

        return json.dumps(result) if result else ""

    def execute(self, parameters):
        """Override execute to route MCP tools"""
        self.ensure_one()

        if self.implementation == "mcp":
            return self.mcp_execute(parameters)

        return super().execute(parameters)
