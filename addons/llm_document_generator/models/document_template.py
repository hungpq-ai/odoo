import base64
import io
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def extract_text_from_docx(file_content):
    """Extract text from DOCX file"""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_content))
        paragraphs = []
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text)
        # Also extract tables
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells)
                if row_text.strip():
                    paragraphs.append(row_text)
        return "\n\n".join(paragraphs)
    except ImportError:
        raise UserError("python-docx is not installed. Run: pip install python-docx")
    except Exception as e:
        raise UserError(f"Error reading DOCX file: {e}")


def extract_text_from_pdf(file_content):
    """Extract text from PDF file"""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_content, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n\n".join(text_parts)
    except ImportError:
        try:
            # Fallback to pdfplumber
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                text_parts = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                return "\n\n".join(text_parts)
        except ImportError:
            raise UserError("PyMuPDF or pdfplumber is not installed. Run: pip install pymupdf or pip install pdfplumber")
    except Exception as e:
        raise UserError(f"Error reading PDF file: {e}")


class DocumentTemplate(models.Model):
    _name = "llm.document.template"
    _description = "Document Template"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence, name"

    name = fields.Char(string="Template Name", required=True, tracking=True, translate=True)
    description = fields.Text(string="Description", translate=True)
    category_id = fields.Many2one(
        "llm.document.category",
        string="Category",
        required=True,
        tracking=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(default=True, tracking=True)
    code = fields.Char(string="Code", help="Technical code for this template")

    # Sample template file - user can upload
    sample_file = fields.Binary(
        string="Sample File",
        help="Upload a sample file (DOCX, PDF, TXT) for AI to reference the structure",
    )
    sample_filename = fields.Char(string="Filename")
    sample_content = fields.Text(
        string="Sample Content",
        help="Sample text content - can be entered directly or auto-extracted from file",
    )

    # Knowledge embedding for RAG
    knowledge_collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Knowledge Collection",
        help="Collection to store embedded template. Helps save tokens during generation.",
    )
    knowledge_resource_id = fields.Many2one(
        "llm.resource",
        string="Template Resource",
        readonly=True,
        help="Resource created from this template",
    )
    is_embedded = fields.Boolean(
        string="Embedded",
        compute="_compute_is_embedded",
        store=True,
    )

    @api.depends("knowledge_resource_id", "knowledge_resource_id.state")
    def _compute_is_embedded(self):
        for template in self:
            template.is_embedded = (
                template.knowledge_resource_id
                and template.knowledge_resource_id.state == "ready"
            )

    @api.onchange("sample_file")
    def _onchange_sample_file(self):
        """Auto-extract content when file is uploaded"""
        if not self.sample_file:
            return

        if not self.sample_filename:
            return

        try:
            # Decode file content
            file_content = base64.b64decode(self.sample_file)
            filename_lower = self.sample_filename.lower()

            if filename_lower.endswith(".docx"):
                extracted_text = extract_text_from_docx(file_content)
            elif filename_lower.endswith(".pdf"):
                extracted_text = extract_text_from_pdf(file_content)
            elif filename_lower.endswith(".txt") or filename_lower.endswith(".md"):
                extracted_text = file_content.decode("utf-8", errors="ignore")
            else:
                return {
                    "warning": {
                        "title": "Unsupported Format",
                        "message": f"File {self.sample_filename} is not supported. Supported formats: DOCX, PDF, TXT, MD",
                    }
                }

            if extracted_text:
                self.sample_content = extracted_text.strip()
                return {
                    "warning": {
                        "title": "Extraction Successful",
                        "message": f"Extracted {len(extracted_text)} characters from {self.sample_filename}",
                        "type": "notification",
                    }
                }
        except UserError:
            raise
        except Exception as e:
            _logger.error(f"Error extracting file content: {e}")
            return {
                "warning": {
                    "title": "Extraction Error",
                    "message": f"Could not extract content from file: {e}",
                }
            }

    # Prompt configuration
    system_prompt = fields.Text(
        string="System Prompt",
        required=True,
        help="Instructions for AI about role and writing style",
        default="""You are a professional document drafting expert.

TASK: Create a NEW document based on the PROVIDED TEMPLATE.

MANDATORY RULES:
1. KEEP THE STRUCTURE of the template (headings, sections, order)
2. KEEP THE FORMAT:
   - If template has TABLE → create TABLE with same column structure
   - If template has numbered list → keep numbered list
   - If template has bullet points → keep bullet points
3. REPLACE CONTENT to match new requirements
4. Use Markdown format:
   - Table: | Column 1 | Column 2 |
   - Heading: # ## ###
   - Bold: **text**
   - List: - item or 1. item
5. DO NOT use:
   - Mermaid diagrams (```mermaid)
   - Code blocks for diagrams
   - Instead, describe diagrams using text or tables""",
    )
    user_prompt_template = fields.Text(
        string="User Prompt",
        required=True,
        help="Prompt template. Use {context} for user requirements, {sample} for sample content",
        default="""## ORIGINAL TEMPLATE:

{sample}

---

## NEW DOCUMENT REQUIREMENTS:

{context}

---

Create a new document with EXACTLY THE SAME STRUCTURE as the template above, replacing content according to requirements.
If the template has tables, the new document MUST have tables with the same format.
Output in Markdown.""",
    )

    # Statistics
    generation_count = fields.Integer(compute="_compute_generation_count")

    def _compute_generation_count(self):
        for template in self:
            template.generation_count = self.env["llm.document.generation"].search_count(
                [("template_id", "=", template.id)]
            )

    def action_view_generations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Generated Documents",
            "res_model": "llm.document.generation",
            "view_mode": "list,form",
            "domain": [("template_id", "=", self.id)],
            "context": {"default_template_id": self.id},
        }

    def get_formatted_prompt(self, context, requirements=""):
        """Format the user prompt with context, sample and requirements"""
        self.ensure_one()
        sample = self.sample_content or "(No template)"
        return self.user_prompt_template.format(
            context=context,
            sample=sample,
            requirements=requirements or "",
        )

    def action_embed_template(self):
        """Embed template sample_content into knowledge collection"""
        self.ensure_one()

        if not self.sample_content:
            raise UserError("Please enter sample content before embedding.")

        if not self.knowledge_collection_id:
            raise UserError("Please select a Knowledge Collection before embedding.")

        # Get or create ir.model for llm.document.template
        model = self.env["ir.model"].search([("model", "=", "llm.document.template")], limit=1)
        if not model:
            raise UserError("Model llm.document.template not found")

        # Check if resource already exists
        if self.knowledge_resource_id:
            # Update existing resource
            self.knowledge_resource_id.write({
                "name": f"Template: {self.name}",
                "content": self.sample_content,
                "state": "parsed",  # Reset to parsed to re-chunk
            })
            resource = self.knowledge_resource_id
        else:
            # Create new resource
            resource = self.env["llm.resource"].create({
                "name": f"Template: {self.name}",
                "model_id": model.id,
                "res_id": self.id,
                "content": self.sample_content,
                "state": "parsed",
                "collection_ids": [(4, self.knowledge_collection_id.id)],
            })
            self.knowledge_resource_id = resource

        # Process resource: chunk and embed
        resource.process_resource()

        self.message_post(
            body=f"Template has been embedded into collection '{self.knowledge_collection_id.name}'",
            message_type="notification",
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Embedding Successful",
                "message": f"Template has been embedded into '{self.knowledge_collection_id.name}'",
                "type": "success",
                "sticky": False,
            },
        }

    def get_relevant_sample(self, query, limit=5):
        """Get relevant chunks from embedded template based on query

        Args:
            query: Search query (e.g., section name or requirements)
            limit: Max number of chunks to return

        Returns:
            str: Concatenated relevant chunks or full sample_content if not embedded
        """
        self.ensure_one()

        # If not embedded, return full sample
        if not self.is_embedded or not self.knowledge_collection_id:
            return self.sample_content or ""

        try:
            # Search for relevant chunks
            chunks = self.env["llm.knowledge.chunk"].search(
                [("collection_ids", "=", self.knowledge_collection_id.id)],
                limit=limit,
                vector_search_term=query,
                collection_id=self.knowledge_collection_id.id,
            )

            if chunks:
                # Concatenate chunk contents
                return "\n\n---\n\n".join(chunk.content for chunk in chunks)
            else:
                # Fallback to full sample
                return self.sample_content or ""

        except Exception as e:
            _logger.warning(f"Error searching template chunks: {e}")
            return self.sample_content or ""
