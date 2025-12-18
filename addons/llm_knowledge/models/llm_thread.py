import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LLMThread(models.Model):
    """Extend llm.thread to add RAG capabilities with knowledge collections."""

    _inherit = "llm.thread"

    # Collections to search for RAG
    collection_ids = fields.Many2many(
        "llm.knowledge.collection",
        string="Document Collections",
        help="Collections to search for relevant documents when answering questions",
    )

    # RAG Configuration
    rag_enabled = fields.Boolean(
        string="RAG Enabled",
        default=False,
        help="Enable Retrieval-Augmented Generation to search documents",
    )
    rag_top_k = fields.Integer(
        string="Top K Results",
        default=5,
        help="Number of relevant document chunks to retrieve",
    )
    rag_min_similarity = fields.Float(
        string="Min Similarity",
        default=0.5,
        help="Minimum similarity score (0.0-1.0) for document retrieval",
    )

    @api.onchange("collection_ids")
    def _onchange_collection_ids(self):
        """Auto-enable RAG when collections are added."""
        if self.collection_ids:
            self.rag_enabled = True

    def _search_relevant_documents(self, query, limit=None, min_similarity=None):
        """Search for relevant document chunks using semantic search.

        Args:
            query (str): The user's question/query
            limit (int): Maximum number of chunks to return
            min_similarity (float): Minimum similarity threshold

        Returns:
            recordset: llm.knowledge.chunk records sorted by similarity
        """
        self.ensure_one()

        if not self.collection_ids:
            return self.env["llm.knowledge.chunk"]

        limit = limit or self.rag_top_k
        min_similarity = min_similarity or self.rag_min_similarity

        # Search using vector search across all collections
        chunks = self.env["llm.knowledge.chunk"].search(
            [("collection_ids", "in", self.collection_ids.ids)],
            vector_search_term=query,
            query_min_similarity=min_similarity,
            limit=limit,
        )

        return chunks

    def _format_rag_context(self, chunks):
        """Format retrieved chunks into context string for the prompt.

        Args:
            chunks: llm.knowledge.chunk recordset

        Returns:
            str: Formatted context string
        """
        if not chunks:
            return ""

        context_parts = []
        for chunk in chunks:
            context_parts.append(chunk.content)

        return "\n---\n".join(context_parts)

    def _get_rag_document_downloads(self, chunks):
        """Get download links for documents used in RAG.

        Args:
            chunks: llm.knowledge.chunk recordset

        Returns:
            list: List of dicts with document name and download URL
        """
        if not chunks:
            return []

        # Get unique resources from chunks
        resources = chunks.mapped("resource_id")
        downloads = []
        seen_ids = set()

        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")

        for resource in resources:
            if resource.id in seen_ids:
                continue
            seen_ids.add(resource.id)

            # Check if resource is linked to an ir.attachment
            if resource.res_model == "ir.attachment" and resource.res_id:
                attachment = self.env["ir.attachment"].sudo().browse(resource.res_id)
                if attachment.exists():
                    download_url = f"{base_url}/web/content/{attachment.id}?download=true"
                    downloads.append({
                        "name": resource.name,
                        "url": download_url,
                        "resource_id": resource.id,
                    })

        return downloads

    def get_context(self, base_context=None):
        """Override to add RAG context to the prompt rendering context."""
        context = super().get_context(base_context or {})

        # Add collection info if RAG is enabled
        if self.collection_ids:
            context["collections"] = self.collection_ids
            context["collection_names"] = ", ".join(self.collection_ids.mapped("name"))

        return context

    def get_prepend_messages(self):
        """Override to include RAG context in the system prompt.

        This method:
        1. Gets the user's latest message (query)
        2. Searches for relevant documents using semantic search
        3. Adds the retrieved context to the prompt
        4. Returns messages with RAG context
        """
        self.ensure_one()

        # If RAG not enabled or no collections, use default behavior
        if not self.rag_enabled or not self.collection_ids:
            return super().get_prepend_messages()

        # Get the latest user message to use as search query
        latest_user_message = self._get_latest_user_query()

        if not latest_user_message:
            return super().get_prepend_messages()

        # Search for relevant documents
        chunks = self._search_relevant_documents(latest_user_message)

        # Format RAG context
        rag_context = self._format_rag_context(chunks)

        # Get download links for documents
        doc_downloads = self._get_rag_document_downloads(chunks)

        # Get glossary context from collections
        glossary_context = self.env["llm.glossary"].get_glossary_context(self.collection_ids)

        # Build context for prompt rendering
        prompt_context = self.get_context()
        prompt_context["rag_context"] = rag_context
        prompt_context["glossary_context"] = glossary_context
        prompt_context["user_query"] = latest_user_message
        prompt_context["has_context"] = bool(rag_context)
        prompt_context["doc_downloads"] = doc_downloads

        # If we have a prompt_id, use it with RAG context
        if hasattr(self, "prompt_id") and self.prompt_id:
            try:
                return self.prompt_id.get_messages(prompt_context)
            except Exception as e:
                _logger.error(
                    "Error getting messages from RAG prompt '%s': %s",
                    self.prompt_id.name,
                    str(e),
                )

        # Fallback: return basic system message with RAG context
        if rag_context or glossary_context:
            # Build download links section
            download_section = ""
            if doc_downloads:
                download_links = "\n".join(
                    f"- [{doc['name']}]({doc['url']})" for doc in doc_downloads
                )
                download_section = f"\n\n## Tài liệu tham khảo (có thể tải về):\n{download_links}"

            # Build glossary section
            glossary_section = ""
            if glossary_context:
                glossary_section = f"\n\n{glossary_context}"

            # Build documents section
            documents_section = ""
            if rag_context:
                documents_section = f"## Relevant Documents:\n\n{rag_context}"

            return [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that answers questions based on "
                        "the provided document context.\n\n"
                        f"{documents_section}"
                        f"{glossary_section}"
                        f"{download_section}\n\n"
                        "## Instructions:\n"
                        "- Answer based on the provided documents\n"
                        "- If the answer is not in the documents, say so\n"
                        "- Use the glossary to understand internal terms correctly\n"
                        "- Reference links are already provided above, do not repeat them in your answer"
                    ),
                }
            ]

        return super().get_prepend_messages()

    def _get_latest_user_query(self):
        """Get the latest user message content for RAG search.

        Returns:
            str: The user's latest message text, or empty string
        """
        self.ensure_one()

        # Get latest user message
        domain = [
            ("model", "=", self._name),
            ("res_id", "=", self.id),
            ("llm_role", "=", "user"),
        ]

        latest_message = self.env["mail.message"].search(
            domain, order="create_date DESC, id DESC", limit=1
        )

        if latest_message:
            # Extract text content from body
            body = latest_message.body or ""
            # Strip HTML tags if present
            return re.sub(r"<[^>]+>", "", body).strip()

        return ""
