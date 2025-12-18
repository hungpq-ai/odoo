{
    "name": "LLM Security",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "summary": "Security features for LLM modules: API Key encryption, Error handling, RAG Access Control",
    "description": """
LLM Security Module
===================

This module provides essential security features for LLM integration:

1. **API Key Encryption** (1.1.1)
   - Secure storage of API keys using Fernet encryption
   - Keys stored in ir.config_parameter with encryption
   - Automatic encryption/decryption on read/write

2. **Error Handling & Retry** (1.1.2)
   - Decorator for API calls with exponential backoff
   - Handles timeout, rate limit, and connection errors
   - Configurable retry attempts and delays

3. **RAG Access Control** (1.3.1)
   - Override search to enforce record rules
   - Users can only search vectors they have read access to
   - Integrates with Odoo's existing security model

4. **Vector Store Enhancement**
   - Direct res_model/res_id linking in vector store
   - Improved traceability and access control
    """,
    "author": "Your Company",
    "website": "https://github.com/your-repo",
    "license": "LGPL-3",
    "depends": [
        "llm",
        "llm_knowledge",
        "llm_pgvector",
    ],
    "data": [
        "security/llm_security_security.xml",
        "security/ir.model.access.csv",
        "views/llm_resource_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
