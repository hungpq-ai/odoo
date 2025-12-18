{
    "name": "LLM Knowledge Integration for Document Pages",
    "summary": "Integrate document.page with LLM RAG for knowledge base search and AI review",
    "description": """
        Integrates the Document Page module with LLM RAG.

        Features:
        - Parse document pages into LLM Knowledge resources
        - Include document hierarchy in generated content
        - Maintain metadata like contributors and update dates
        - Create RAG resources from document pages
        - AI Review: Automatically review documents for format, logic, and conflicts
    """,
    "category": "Knowledge",
    "version": "18.0.1.1.0",
    "depends": ["document_page", "llm_knowledge", "mail"],
    "external_dependencies": {
        "python": ["markdownify", "markdown"],
    },
    "author": "Apexive Solutions LLC",
    "website": "https://github.com/apexive/odoo-llm",
    "license": "AGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
    "images": [
        "static/description/banner.jpeg",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizards/document_review_wizard_views.xml",
        "views/document_page_views.xml",
        "wizards/upload_resource_wizard_views.xml",
    ],
}
