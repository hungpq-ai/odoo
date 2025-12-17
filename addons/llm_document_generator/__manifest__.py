{
    "name": "LLM Document Generator",
    "version": "18.0.1.0.0",
    "category": "Productivity/Documents",
    "summary": "Generate new documents from imported resources using AI",
    "description": """
        LLM Document Generator
        ======================

        This module allows you to generate new documents based on:
        - Imported resources from knowledge base
        - Pre-defined document templates with prompts
        - Customizable document categories

        Features:
        - Document templates with category classification
        - Pre-built prompts for common document types
        - Select source documents from knowledge base
        - AI-powered document generation
        - Export generated documents
    """,
    "author": "Odoo LLM",
    "depends": [
        "llm_knowledge",
        "llm_assistant",
        "mail",
    ],
    "external_dependencies": {
        "python": ["markdown", "python-docx", "pymupdf"],
    },
    "data": [
        "security/ir.model.access.csv",
        "data/document_category_data.xml",
        "data/document_template_data.xml",
        "views/document_category_views.xml",
        "views/document_template_views.xml",
        "views/document_generation_views.xml",
        "wizards/generate_document_wizard_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
