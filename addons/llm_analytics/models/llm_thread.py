import logging
from odoo import api, models

_logger = logging.getLogger(__name__)


class LLMThreadAnalytics(models.Model):
    """Extend LLM Thread to track output tokens from assistant messages."""

    _inherit = "llm.thread"

    @api.returns("mail.message", lambda value: value.id)
    def message_post(self, *, llm_role=None, **kwargs):
        """Override to log output tokens for assistant messages."""
        message = super().message_post(llm_role=llm_role, **kwargs)

        # Log output tokens for assistant messages
        if llm_role == "assistant" and kwargs.get("body"):
            self._update_usage_log_output_tokens(kwargs.get("body"))

        return message

    def _update_usage_log_output_tokens(self, body_content):
        """Update the most recent usage log with output tokens.

        This finds the most recent usage log for the current model/user
        that has 0 output tokens and updates it.

        Args:
            body_content: The message body content
        """
        if not body_content:
            return

        try:
            UsageLog = self.env["llm.usage.log"].sudo()

            # Find the most recent log for this model (created when chat started)
            model_id = self.model_id.id if self.model_id else False
            if not model_id:
                return

            # Get the most recent log for this model (within last 5 minutes)
            from datetime import datetime, timedelta
            recent_cutoff = datetime.now() - timedelta(minutes=5)

            recent_log = UsageLog.search([
                ("model_id", "=", model_id),
                ("user_id", "=", self.env.user.id),
                ("tokens_output", "=", 0),  # Only update logs without output tokens
                ("request_date", ">=", recent_cutoff),
            ], order="request_date DESC", limit=1)

            if recent_log:
                # Strip HTML tags for token estimation
                import re
                plain_text = re.sub(r'<[^>]+>', '', str(body_content))

                # Use provider's estimate method if available
                provider = self.provider_id
                if provider and hasattr(provider, "_estimate_tokens"):
                    tokens_output = provider._estimate_tokens(plain_text)
                else:
                    # Fallback estimate: ~4 chars per token for English
                    tokens_output = max(1, len(plain_text) // 4)

                # Recalculate cost with output tokens
                if provider and hasattr(provider, "_estimate_cost"):
                    cost = provider._estimate_cost(
                        self.model_id, recent_log.tokens_input, tokens_output
                    )
                else:
                    cost = recent_log.cost

                recent_log.write({
                    "tokens_output": tokens_output,
                    "cost": cost,
                })
                _logger.debug(
                    f"Updated usage log {recent_log.id} with {tokens_output} output tokens"
                )

        except Exception as e:
            _logger.warning(f"Failed to update output tokens: {e}")
