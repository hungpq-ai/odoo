import logging
from odoo import models

_logger = logging.getLogger(__name__)


class MailMessageAnalytics(models.Model):
    """Extend mail.message to log feedback to analytics."""

    _inherit = "mail.message"

    def set_user_vote(self, vote_value):
        """Override to also log feedback to analytics."""
        # Call the original method first
        result = super().set_user_vote(vote_value)

        # Log to analytics
        try:
            UsageLog = self.env["llm.usage.log"].sudo()
            for message in self:
                if message.llm_role in ("assistant", "tool"):
                    UsageLog.log_feedback(message.id, vote_value)
        except Exception as e:
            _logger.warning(f"Failed to log feedback to analytics: {e}")

        return result
