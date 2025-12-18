import logging
from datetime import datetime

from markdownify import markdownify as md

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Default review prompt with checklist
DEFAULT_REVIEW_PROMPT = """You are a professional document reviewer. Review the following document and provide feedback.

## Document to Review:
{content}

## Review Checklist:
Please evaluate the document on the following criteria:

### 1. FORMAT
- [ ] Consistent heading structure
- [ ] Proper use of lists and tables
- [ ] Clear section organization
- [ ] Appropriate formatting (bold, italic, etc.)

### 2. LOGIC
- [ ] Clear and logical flow of information
- [ ] No contradictory statements
- [ ] Complete coverage of the topic
- [ ] Proper cause-effect relationships

### 3. CONTENT QUALITY
- [ ] Accurate information
- [ ] No spelling or grammar errors
- [ ] Appropriate level of detail
- [ ] Clear and concise language

### 4. CONFLICTS
- [ ] No internal contradictions
- [ ] Consistent terminology usage
- [ ] No duplicate information
- [ ] Aligned with document purpose

## Instructions:
1. Review the document against each checklist item
2. Mark items as ✅ (pass), ❌ (fail), or ⚠️ (needs improvement)
3. Provide specific comments for each failed or warning item
4. Suggest concrete improvements where needed
5. Give an overall assessment at the end

Output your review in Vietnamese."""


class DocumentReviewWizard(models.TransientModel):
    _name = "llm.document.review.wizard"
    _description = "AI Document Review Wizard"

    document_id = fields.Many2one(
        "document.page",
        string="Document",
        required=True,
        readonly=True,
    )
    document_name = fields.Char(
        related="document_id.name",
        string="Document Name",
        readonly=True,
    )
    model_id = fields.Many2one(
        "llm.model",
        string="AI Model",
        required=True,
        domain="[('model_use', 'in', ['chat', 'completion'])]",
    )
    review_prompt = fields.Text(
        string="Review Prompt",
        default=DEFAULT_REVIEW_PROMPT,
        help="Customize the review prompt. Use {content} as placeholder for document content.",
    )
    review_result = fields.Html(
        string="Review Result",
        readonly=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("reviewing", "Reviewing..."),
            ("done", "Done"),
        ],
        default="draft",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Auto-select first available model
        if "model_id" in fields_list and not res.get("model_id"):
            model = self.env["llm.model"].search(
                [("model_use", "in", ["chat", "completion"])], limit=1
            )
            if model:
                res["model_id"] = model.id
        return res

    def _get_document_content(self):
        """Get document content as markdown."""
        self.ensure_one()
        if not self.document_id:
            return ""

        # Convert HTML content to markdown
        content = self.document_id.content or ""
        if content:
            content = md(content)

        # Add document metadata
        doc = self.document_id
        metadata = f"# {doc.name}\n\n"
        if doc.parent_id:
            metadata += f"**Parent:** {doc.parent_id.name}\n"
        if doc.create_date:
            metadata += f"**Created:** {doc.create_date.strftime('%Y-%m-%d')}\n"
        if doc.write_date:
            metadata += f"**Last Modified:** {doc.write_date.strftime('%Y-%m-%d')}\n"
        metadata += "\n---\n\n"

        return metadata + content

    def _call_llm(self, system_prompt, user_prompt):
        """Call LLM and get response."""
        self.ensure_one()
        model = self.model_id
        if not model:
            raise UserError("Please select an AI Model.")

        prepend_messages = []
        if system_prompt:
            prepend_messages.append({"role": "system", "content": system_prompt})
        prepend_messages.append({"role": "user", "content": user_prompt})

        empty_messages = self.env["mail.message"].browse()
        response = model.chat(
            messages=empty_messages,
            prepend_messages=prepend_messages,
            stream=False,
        )

        if isinstance(response, dict):
            return response.get("content", "")
        elif isinstance(response, str):
            return response
        elif hasattr(response, "__iter__"):
            content = ""
            for chunk in response:
                if isinstance(chunk, dict) and chunk.get("content"):
                    content += chunk["content"]
                elif isinstance(chunk, str):
                    content += chunk
            return content
        return str(response)

    def _convert_markdown_to_html(self, markdown_content):
        """Convert markdown review result to HTML."""
        import markdown
        import re

        # Convert markdown to HTML
        md_parser = markdown.Markdown(extensions=["fenced_code", "tables"])
        html_content = md_parser.convert(markdown_content)

        # Style checkboxes
        html_content = html_content.replace("✅", '<span style="color: green;">✅</span>')
        html_content = html_content.replace("❌", '<span style="color: red;">❌</span>')
        html_content = html_content.replace("⚠️", '<span style="color: orange;">⚠️</span>')

        # Add some basic styling
        styled_html = f"""
        <div style="font-family: Arial, sans-serif; line-height: 1.6;">
            {html_content}
        </div>
        """
        return styled_html

    def action_review(self):
        """Execute AI review of the document."""
        self.ensure_one()

        if not self.document_id:
            raise UserError("No document selected for review.")

        try:
            self.state = "reviewing"
            self._cr.commit()

            # Get document content
            content = self._get_document_content()
            if not content:
                raise UserError("Document has no content to review.")

            # Prepare prompt
            user_prompt = self.review_prompt.format(content=content)
            system_prompt = "You are a professional document reviewer. Provide detailed, constructive feedback."

            # Call LLM
            _logger.info(f"Starting AI review for document {self.document_id.name}")
            review_result = self._call_llm(system_prompt, user_prompt)

            if not review_result:
                raise UserError("AI did not return any review result.")

            # Convert to HTML
            html_result = self._convert_markdown_to_html(review_result)

            # Update wizard
            self.write({
                "review_result": html_result,
                "state": "done",
            })

            # Update document with review result
            self.document_id.write({
                "last_review_date": datetime.now(),
                "last_review_result": html_result,
                "review_count": self.document_id.review_count + 1,
            })

            # Post review as message on document
            self.document_id.message_post(
                body=f"<strong>AI Review #{self.document_id.review_count}</strong><br/>{html_result}",
                message_type="comment",
                subtype_xmlid="mail.mt_note",
            )

            _logger.info(f"AI review completed for document {self.document_id.name}")

            # Return action to refresh wizard with result
            return {
                "type": "ir.actions.act_window",
                "name": "AI Review Result",
                "res_model": "llm.document.review.wizard",
                "res_id": self.id,
                "view_mode": "form",
                "target": "new",
            }

        except Exception as e:
            _logger.error(f"Error during AI review: {str(e)}")
            self.state = "draft"
            raise UserError(f"Error during review: {str(e)}")

    def action_close(self):
        """Close the wizard."""
        return {"type": "ir.actions.act_window_close"}
