{
    "name": "LLM Knowledge",
    "summary": "RAG vector search: AI knowledge base with semantic document retrieval, embeddings, PDF parsing, and multi-store support (Qdrant, pgvector, Chroma)",
    "description": """
        Complete RAG (Retrieval-Augmented Generation) system for Odoo with document processing,
        vector search, and semantic knowledge base capabilities. Turn your documents into AI-searchable
        knowledge with support for PDFs, web pages, and text files. Compatible with Qdrant, pgvector,
        and Chroma vector stores.
    """,
    "category": "Technical",
    "version": "18.0.1.1.0",
    "depends": ["llm", "llm_store", "llm_thread"],
    "external_dependencies": {
        "python": [
            "requests",
            "markdownify",
            "PyMuPDF",
            "numpy",
            "python-docx",
            "openpyxl",
            "python-pptx",
            # Optional: "pytesseract", "Pillow" for OCR support
        ],
    },
    "author": "Apexive Solutions LLC",
    "website": "https://github.com/apexive/odoo-llm",
    "data": [
        # Security must come first
        "security/ir.model.access.csv",
        # Data / Actions / Cron Jobs
        "data/server_actions.xml",
        "data/ir_cron.xml",
        # Views for models
        "views/llm_resource_views.xml",  # Consolidated llm.resource views
        "views/llm_knowledge_collection_views.xml",
        "views/llm_knowledge_chunk_views.xml",
        "views/llm_glossary_views.xml",
        "views/llm_thread_views.xml",  # RAG settings for chat threads
        # Wizard Views
        "wizards/create_rag_resource_wizard_views.xml",
        "wizards/upload_resource_wizard_views.xml",
        # Menus must come last
        "views/llm_resource_menu.xml",
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "llm_knowledge/static/src/components/**/*.js",
            "llm_knowledge/static/src/components/**/*.xml",
        ],
    },
    "images": [
        "static/description/banner.jpeg",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
