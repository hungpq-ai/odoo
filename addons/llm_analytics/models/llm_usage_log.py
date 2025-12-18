import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LLMUsageLog(models.Model):
    _name = "llm.usage.log"
    _description = "LLM Usage Log"
    _order = "request_date desc"
    _rec_name = "display_name"

    # Basic info
    display_name = fields.Char(compute="_compute_display_name", store=True)
    request_date = fields.Datetime(
        string="Request Date",
        default=fields.Datetime.now,
        required=True,
        index=True,
    )

    # User tracking
    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.user,
        required=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )

    # Model/Provider info
    model_id = fields.Many2one(
        "llm.model",
        string="Model",
        index=True,
    )
    provider_id = fields.Many2one(
        "llm.provider",
        string="Provider",
        related="model_id.provider_id",
        store=True,
        index=True,
    )
    model_name = fields.Char(
        string="Model Name",
        help="Raw model name for cases where model record is not available",
    )

    # Request type
    request_type = fields.Selection(
        [
            ("chat", "Chat"),
            ("completion", "Completion"),
            ("embedding", "Embedding"),
            ("generation", "Generation"),
            ("other", "Other"),
        ],
        string="Request Type",
        default="chat",
        required=True,
        index=True,
    )

    # Token usage
    tokens_input = fields.Integer(
        string="Input Tokens",
        default=0,
        help="Number of input/prompt tokens",
    )
    tokens_output = fields.Integer(
        string="Output Tokens",
        default=0,
        help="Number of output/completion tokens",
    )
    tokens_total = fields.Integer(
        string="Total Tokens",
        compute="_compute_tokens_total",
        store=True,
    )

    # Cost tracking
    cost = fields.Float(
        string="Cost (USD)",
        digits=(16, 6),
        default=0.0,
        help="Estimated cost in USD",
    )

    # Performance metrics
    response_time = fields.Float(
        string="Response Time (s)",
        digits=(10, 3),
        help="Response time in seconds",
    )

    # Status
    status = fields.Selection(
        [
            ("success", "Success"),
            ("error", "Error"),
            ("timeout", "Timeout"),
        ],
        string="Status",
        default="success",
        required=True,
        index=True,
    )
    error_message = fields.Text(string="Error Message")

    # Feedback
    feedback = fields.Selection(
        [
            ("like", "Like"),
            ("dislike", "Dislike"),
        ],
        string="Feedback",
        index=True,
    )
    feedback_comment = fields.Text(string="Feedback Comment")

    # Source tracking
    source_model = fields.Char(
        string="Source Model",
        help="Odoo model that initiated the request",
    )
    source_record_id = fields.Integer(
        string="Source Record ID",
        help="ID of the record that initiated the request",
    )
    message_id = fields.Many2one(
        "mail.message",
        string="Message",
        help="Related chat message for feedback tracking",
        index=True,
        ondelete="set null",
    )

    # Aggregation helper fields
    request_date_day = fields.Date(
        string="Date",
        compute="_compute_date_parts",
        store=True,
        index=True,
    )
    request_date_week = fields.Char(
        string="Week",
        compute="_compute_date_parts",
        store=True,
    )
    request_date_month = fields.Char(
        string="Month",
        compute="_compute_date_parts",
        store=True,
    )

    @api.depends("model_id", "request_date", "user_id")
    def _compute_display_name(self):
        for record in self:
            model_name = record.model_id.name if record.model_id else record.model_name or "Unknown"
            date_str = record.request_date.strftime("%Y-%m-%d %H:%M") if record.request_date else ""
            user_name = record.user_id.name if record.user_id else ""
            record.display_name = f"{model_name} - {user_name} - {date_str}"

    @api.depends("tokens_input", "tokens_output")
    def _compute_tokens_total(self):
        for record in self:
            record.tokens_total = record.tokens_input + record.tokens_output

    @api.depends("request_date")
    def _compute_date_parts(self):
        for record in self:
            if record.request_date:
                record.request_date_day = record.request_date.date()
                record.request_date_week = record.request_date.strftime("%Y-W%W")
                record.request_date_month = record.request_date.strftime("%Y-%m")
            else:
                record.request_date_day = False
                record.request_date_week = False
                record.request_date_month = False

    @api.model
    def log_request(
        self,
        model=None,
        model_name=None,
        request_type="chat",
        tokens_input=0,
        tokens_output=0,
        cost=0.0,
        response_time=0.0,
        status="success",
        error_message=None,
        source_model=None,
        source_record_id=None,
    ):
        """
        Log an LLM request.

        Args:
            model: llm.model record or ID
            model_name: Model name string (fallback if model not provided)
            request_type: Type of request (chat, completion, embedding, etc.)
            tokens_input: Number of input tokens
            tokens_output: Number of output tokens
            cost: Estimated cost in USD
            response_time: Response time in seconds
            status: Request status (success, error, timeout)
            error_message: Error message if status is error
            source_model: Odoo model that initiated the request
            source_record_id: ID of the source record

        Returns:
            Created llm.usage.log record
        """
        vals = {
            "request_type": request_type,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "cost": cost,
            "response_time": response_time,
            "status": status,
            "error_message": error_message,
            "source_model": source_model,
            "source_record_id": source_record_id,
        }

        if model:
            if isinstance(model, int):
                vals["model_id"] = model
            else:
                vals["model_id"] = model.id

        if model_name:
            vals["model_name"] = model_name

        return self.create(vals)

    def action_set_feedback_like(self):
        """Set feedback to like"""
        self.write({"feedback": "like"})

    def action_set_feedback_dislike(self):
        """Set feedback to dislike"""
        self.write({"feedback": "dislike"})

    @api.model
    def log_feedback(self, message_id, vote_value, comment=None):
        """Log feedback from a chat message.

        Args:
            message_id: ID of mail.message
            vote_value: 1 for like, -1 for dislike, 0 for remove
            comment: Optional feedback comment

        Returns:
            Updated or created llm.usage.log record
        """
        # Find existing log for this message or create new one
        existing = self.search([("message_id", "=", message_id)], limit=1)

        feedback = False
        if vote_value == 1:
            feedback = "like"
        elif vote_value == -1:
            feedback = "dislike"

        if existing:
            existing.write({
                "feedback": feedback,
                "feedback_comment": comment,
            })
            return existing
        else:
            # Create a new feedback-only log entry
            message = self.env["mail.message"].browse(message_id)
            vals = {
                "message_id": message_id,
                "feedback": feedback,
                "feedback_comment": comment,
                "request_type": "chat",
                "status": "success",
            }

            # Try to get model info from the thread
            if message.model == "llm.thread" and message.res_id:
                try:
                    thread = self.env["llm.thread"].browse(message.res_id)
                    if thread.exists() and thread.assistant_id:
                        assistant = thread.assistant_id
                        if assistant.model_id:
                            vals["model_id"] = assistant.model_id.id
                            vals["model_name"] = assistant.model_id.name
                except Exception:
                    pass

            return self.create(vals)
