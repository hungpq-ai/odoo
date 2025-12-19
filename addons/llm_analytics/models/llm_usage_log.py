import logging
from datetime import timedelta
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

    @api.model
    def get_dashboard_data(self, period="month"):
        """Get aggregated data for the analytics dashboard.

        Args:
            period: 'today', 'week', 'month', or 'all'

        Returns:
            Dictionary with stats and chart data
        """
        # Build domain based on period
        domain = []
        today = fields.Date.today()

        if period == "today":
            domain = [("request_date_day", "=", today)]
        elif period == "week":
            week_ago = today - timedelta(days=7)
            domain = [("request_date_day", ">=", week_ago)]
        elif period == "month":
            month_start = today.replace(day=1)
            domain = [("request_date_day", ">=", month_start)]
        # 'all' = no domain filter

        logs = self.search(domain)

        # Calculate stats
        total_requests = len(logs)
        total_tokens = sum(logs.mapped("tokens_total"))
        tokens_input = sum(logs.mapped("tokens_input"))
        tokens_output = sum(logs.mapped("tokens_output"))
        total_cost = sum(logs.mapped("cost"))
        avg_cost = total_cost / total_requests if total_requests else 0

        response_times = [r for r in logs.mapped("response_time") if r]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0

        success_count = len(logs.filtered(lambda r: r.status == "success"))
        success_rate = (success_count / total_requests * 100) if total_requests else 0

        total_likes = len(logs.filtered(lambda r: r.feedback == "like"))
        total_dislikes = len(logs.filtered(lambda r: r.feedback == "dislike"))
        total_feedback = total_likes + total_dislikes
        satisfaction_rate = (total_likes / total_feedback * 100) if total_feedback else 0

        # Chart data - by model
        model_data = {}
        for log in logs:
            model_name = log.model_name or (log.model_id.name if log.model_id else "Unknown")
            if model_name not in model_data:
                model_data[model_name] = 0
            model_data[model_name] += 1

        max_model_count = max(model_data.values()) if model_data else 1
        by_model = [
            {
                "model": k,
                "count": v,
                "percent": (v / max_model_count * 100) if max_model_count else 0
            }
            for k, v in sorted(model_data.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

        # Chart data - by user
        user_data = {}
        for log in logs:
            user_name = log.user_id.name if log.user_id else "Unknown"
            if user_name not in user_data:
                user_data[user_name] = {"count": 0, "tokens": 0}
            user_data[user_name]["count"] += 1
            user_data[user_name]["tokens"] += log.tokens_total or 0

        by_user = [
            {
                "user": k,
                "count": v["count"],
                "tokens": v["tokens"]
            }
            for k, v in sorted(user_data.items(), key=lambda x: x[1]["count"], reverse=True)[:5]
        ]

        return {
            "stats": {
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "tokens_input": tokens_input,
                "tokens_output": tokens_output,
                "total_cost": total_cost,
                "avg_cost": avg_cost,
                "avg_response_time": avg_response_time,
                "success_rate": success_rate,
                "total_likes": total_likes,
                "total_dislikes": total_dislikes,
                "satisfaction_rate": satisfaction_rate,
            },
            "charts": {
                "byModel": by_model,
                "byUser": by_user,
            }
        }

    @api.model
    def get_top_users_data(self, period="month"):
        """Get top users data for the leaderboard.

        Args:
            period: 'today', 'week', 'month', or 'all'

        Returns:
            Dictionary with users list and totals
        """
        # Build domain based on period
        domain = []
        today = fields.Date.today()

        if period == "today":
            domain = [("request_date_day", "=", today)]
        elif period == "week":
            week_ago = today - timedelta(days=7)
            domain = [("request_date_day", ">=", week_ago)]
        elif period == "month":
            month_start = today.replace(day=1)
            domain = [("request_date_day", ">=", month_start)]

        logs = self.search(domain)

        # Aggregate by user
        user_stats = {}
        for log in logs:
            user = log.user_id
            if not user:
                continue
            user_id = user.id
            if user_id not in user_stats:
                user_stats[user_id] = {
                    "user_id": user_id,
                    "name": user.name,
                    "email": user.login or "",
                    "requests": 0,
                    "tokens": 0,
                    "cost": 0,
                }
            user_stats[user_id]["requests"] += 1
            user_stats[user_id]["tokens"] += log.tokens_total or 0
            user_stats[user_id]["cost"] += log.cost or 0

        # Sort by requests and add rank
        sorted_users = sorted(user_stats.values(), key=lambda x: x["requests"], reverse=True)

        # Calculate totals and percentages
        total_requests = sum(u["requests"] for u in sorted_users)
        total_tokens = sum(u["tokens"] for u in sorted_users)
        total_cost = sum(u["cost"] for u in sorted_users)

        for i, user in enumerate(sorted_users):
            user["rank"] = i + 1
            user["percent"] = (user["requests"] / total_requests * 100) if total_requests else 0

        return {
            "users": sorted_users[:20],  # Top 20 users
            "totals": {
                "requests": total_requests,
                "tokens": total_tokens,
                "cost": total_cost,
            }
        }

    @api.model
    def get_feedback_data(self, period="month"):
        """Get feedback data for the feedback dashboard.

        Args:
            period: 'today', 'week', 'month', or 'all'

        Returns:
            Dictionary with feedback stats and breakdowns
        """
        # Build domain based on period
        domain = [("feedback", "!=", False)]
        today = fields.Date.today()

        if period == "today":
            domain.append(("request_date_day", "=", today))
        elif period == "week":
            week_ago = today - timedelta(days=7)
            domain.append(("request_date_day", ">=", week_ago))
        elif period == "month":
            month_start = today.replace(day=1)
            domain.append(("request_date_day", ">=", month_start))

        logs = self.search(domain, order="request_date desc")

        # Calculate stats
        total_likes = len(logs.filtered(lambda r: r.feedback == "like"))
        total_dislikes = len(logs.filtered(lambda r: r.feedback == "dislike"))
        total_feedback = total_likes + total_dislikes
        satisfaction_rate = (total_likes / total_feedback * 100) if total_feedback else 0

        # By model
        model_data = {}
        for log in logs:
            model_name = log.model_name or (log.model_id.name if log.model_id else "Unknown")
            if model_name not in model_data:
                model_data[model_name] = {"likes": 0, "dislikes": 0}
            if log.feedback == "like":
                model_data[model_name]["likes"] += 1
            else:
                model_data[model_name]["dislikes"] += 1

        by_model = []
        for model, data in sorted(model_data.items(), key=lambda x: x[1]["likes"] + x[1]["dislikes"], reverse=True)[:5]:
            total = data["likes"] + data["dislikes"]
            by_model.append({
                "model": model,
                "likes": data["likes"],
                "dislikes": data["dislikes"],
                "like_percent": (data["likes"] / total * 100) if total else 0,
                "dislike_percent": (data["dislikes"] / total * 100) if total else 0,
            })

        # By user
        user_data = {}
        for log in logs:
            user = log.user_id
            if not user:
                continue
            user_id = user.id
            if user_id not in user_data:
                user_data[user_id] = {"user_id": user_id, "user": user.name, "likes": 0, "dislikes": 0}
            if log.feedback == "like":
                user_data[user_id]["likes"] += 1
            else:
                user_data[user_id]["dislikes"] += 1

        by_user = []
        for data in sorted(user_data.values(), key=lambda x: x["likes"] + x["dislikes"], reverse=True)[:5]:
            total = data["likes"] + data["dislikes"]
            by_user.append({
                "user_id": data["user_id"],
                "user": data["user"],
                "likes": data["likes"],
                "dislikes": data["dislikes"],
                "like_percent": (data["likes"] / total * 100) if total else 0,
                "dislike_percent": (data["dislikes"] / total * 100) if total else 0,
            })

        # Recent feedback
        recent = []
        for log in logs[:10]:
            recent.append({
                "id": log.id,
                "date": log.request_date.strftime("%Y-%m-%d %H:%M") if log.request_date else "",
                "user": log.user_id.name if log.user_id else "Unknown",
                "model": log.model_name or (log.model_id.name if log.model_id else "Unknown"),
                "feedback": log.feedback,
            })

        return {
            "stats": {
                "total_feedback": total_feedback,
                "total_likes": total_likes,
                "total_dislikes": total_dislikes,
                "satisfaction_rate": satisfaction_rate,
            },
            "by_model": by_model,
            "by_user": by_user,
            "recent": recent,
        }
