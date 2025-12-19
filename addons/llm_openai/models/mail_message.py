import json
import logging

from odoo import models, tools

_logger = logging.getLogger(__name__)


class MailMessage(models.Model):
    _inherit = "mail.message"

    def openai_format_message(self):
        """Provider-specific formatting for OpenAI."""
        self.ensure_one()
        body = self.body
        if body:
            body = tools.html2plaintext(body)

        if self.is_llm_user_message()[self]:
            formatted_message = {"role": "user"}

            # Get attachment content blocks
            attachment_blocks = self._get_attachment_content_blocks(provider="openai")

            if attachment_blocks:
                # Use multimodal content format with text + attachments
                content_blocks = []
                if body:
                    content_blocks.append({"type": "text", "text": body})
                content_blocks.extend(attachment_blocks)
                formatted_message["content"] = content_blocks
            elif body:
                formatted_message["content"] = body
            else:
                formatted_message["content"] = ""

            return formatted_message

        elif self.is_llm_assistant_message()[self]:
            formatted_message = {"role": "assistant"}

            formatted_message["content"] = body

            # Add tool calls if present in body_json
            tool_calls = self.get_tool_calls()
            if tool_calls:
                formatted_message["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": tc.get("type", "function"),
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in tool_calls
                ]

            return formatted_message

        elif self.is_llm_tool_message()[self]:
            tool_data = self.body_json
            if not tool_data:
                _logger.warning(
                    f"OpenAI Format: Skipping tool message {self.id}: no tool data found."
                )
                return None

            tool_call_id = tool_data.get("tool_call_id")
            if not tool_call_id:
                _logger.warning(
                    f"OpenAI Format: Skipping tool message {self.id}: missing tool_call_id."
                )
                return None

            # Get result content
            if "result" in tool_data:
                content = json.dumps(tool_data["result"])
            elif "error" in tool_data:
                content = json.dumps({"error": tool_data["error"]})
            else:
                content = ""

            formatted_message = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }
            return formatted_message
        else:
            return None
