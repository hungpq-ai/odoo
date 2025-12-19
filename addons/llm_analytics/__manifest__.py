{
    "name": "LLM Analytics Dashboard",
    "summary": "Track and analyze AI/LLM usage across your organization",
    "description": """
        LLM Usage Analytics Dashboard for Odoo.

        Features:
        - Track all AI/LLM API calls with token usage and costs
        - Real-time Dashboard with KPI cards and charts
        - Metrics: Requests/day, Top users, Token usage, Cost analysis
        - Feedback tracking (Like/Dislike)
        - Filter by model, provider, user, date range
    """,
    "category": "Productivity",
    "version": "18.0.1.0.0",
    "depends": ["llm", "llm_thread", "web"],
    "author": "Apexive Solutions LLC",
    "website": "https://github.com/apexive/odoo-llm",
    "license": "AGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
    "data": [
        "security/ir.model.access.csv",
        "views/llm_usage_log_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "llm_analytics/static/src/dashboard/**/*",
        ],
    },
}
