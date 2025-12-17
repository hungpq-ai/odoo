import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DocumentGeneration(models.Model):
    _name = "llm.document.generation"
    _description = "Generated Document"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(required=True, tracking=True)
    template_id = fields.Many2one(
        "llm.document.template",
        string="Loại tài liệu",
        required=True,
        tracking=True,
        ondelete="restrict",
    )
    category_id = fields.Many2one(
        related="template_id.category_id",
        string="Thể loại",
        store=True,
    )

    # User input - this is the main content for generation
    requirements = fields.Text(
        string="Yêu cầu",
        required=True,
        help="Yêu cầu chi tiết cho tài liệu cần tạo",
    )

    # Generated content
    generated_content = fields.Html(string="Nội dung")
    generated_markdown = fields.Text(string="Markdown")

    # Status
    state = fields.Selection(
        [
            ("draft", "Nháp"),
            ("generating", "Đang tạo"),
            ("done", "Hoàn thành"),
            ("error", "Lỗi"),
        ],
        default="draft",
        tracking=True,
    )
    error_message = fields.Text(string="Thông báo lỗi", readonly=True)

    # LLM Selection
    selected_model_id = fields.Many2one(
        "llm.model",
        string="Model AI",
        domain="[('model_use', 'in', ['chat', 'completion'])]",
        required=True,
    )

    def action_generate(self):
        """Generate document using LLM"""
        for record in self:
            try:
                record.state = "generating"
                record._cr.commit()

                # Get template
                template = record.template_id

                # Get model
                model = record.selected_model_id
                if not model:
                    raise UserError("Vui lòng chọn Model AI.")

                # Format user prompt - requirements is the main content
                user_prompt = template.get_formatted_prompt(
                    context=record.requirements,  # Use requirements as context
                    requirements="",
                )

                # Build all messages as prepend_messages (list of dicts)
                # since provider.chat expects messages as mail.message recordset
                prepend_messages = []
                if template.system_prompt:
                    prepend_messages.append({
                        "role": "system",
                        "content": template.system_prompt
                    })
                # Add user message
                prepend_messages.append({
                    "role": "user",
                    "content": user_prompt
                })

                # Call LLM with empty recordset for messages, all content in prepend_messages
                empty_messages = self.env["mail.message"].browse()
                response_content = ""
                response = model.chat(
                    messages=empty_messages,
                    prepend_messages=prepend_messages,
                    stream=False,
                )

                # Extract content from response
                if isinstance(response, dict):
                    response_content = response.get("content", "")
                elif isinstance(response, str):
                    response_content = response
                elif hasattr(response, "__iter__"):
                    # Handle streaming response (shouldn't happen with stream=False)
                    for chunk in response:
                        if isinstance(chunk, dict) and chunk.get("content"):
                            response_content += chunk["content"]
                        elif isinstance(chunk, str):
                            response_content += chunk
                else:
                    response_content = str(response)

                if response_content:
                    # Store markdown
                    record.generated_markdown = response_content

                    # Convert to HTML for display
                    import markdown
                    import re

                    # Pre-process: convert <br> tags to proper line breaks
                    processed_content = re.sub(r'<br\s*/?>', '  \n', response_content)

                    # Convert markdown to HTML using python-markdown with tables extension
                    # Note: Don't use nl2br as it can break table formatting
                    md = markdown.Markdown(extensions=['tables', 'fenced_code'])
                    html_content = md.convert(processed_content)

                    # Add inline styles to tables (Odoo strips <style> tags)
                    html_content = re.sub(
                        r'<table>',
                        '<table style="border-collapse: collapse; width: 100%; margin: 15px 0;">',
                        html_content
                    )
                    html_content = re.sub(
                        r'<th>',
                        '<th style="border: 1px solid #dee2e6; padding: 10px 12px; text-align: left; background-color: #f8f9fa; font-weight: bold;">',
                        html_content
                    )
                    html_content = re.sub(
                        r'<td>',
                        '<td style="border: 1px solid #dee2e6; padding: 10px 12px; text-align: left; vertical-align: top;">',
                        html_content
                    )

                    record.generated_content = html_content

                    record.state = "done"
                    record.message_post(
                        body="Tạo tài liệu thành công!",
                        message_type="notification",
                    )
                else:
                    raise UserError("Không nhận được phản hồi từ AI")

            except Exception as e:
                _logger.error(f"Error generating document {record.id}: {str(e)}")
                record.state = "error"
                record.error_message = str(e)
                record.message_post(
                    body=f"Lỗi tạo tài liệu: {str(e)}",
                    message_type="notification",
                )

    def action_regenerate(self):
        """Regenerate the document"""
        self.write({
            "state": "draft",
            "generated_content": False,
            "generated_markdown": False,
            "error_message": False,
        })
        return self.action_generate()

    def action_reset_draft(self):
        """Reset to draft state"""
        self.write({
            "state": "draft",
            "error_message": False,
        })

    def _parse_markdown_table(self, lines, start_idx):
        """Parse markdown table starting at given index, return (table_data, end_idx)"""
        table_rows = []
        idx = start_idx

        while idx < len(lines):
            line = lines[idx].strip()
            # Check if line is a table row (starts and ends with |)
            if line.startswith("|") and "|" in line[1:]:
                # Parse cells
                cells = [cell.strip() for cell in line.split("|")[1:-1]]
                # Skip separator row (contains only dashes and colons)
                if not all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
                    table_rows.append(cells)
                idx += 1
            else:
                break

        return table_rows, idx

    def _add_table_to_docx(self, doc, table_data):
        """Add a table to DOCX document with proper formatting"""
        if not table_data:
            return

        import re
        from docx.shared import Pt, Inches

        # Create table
        num_cols = max(len(row) for row in table_data)
        table = doc.add_table(rows=len(table_data), cols=num_cols)
        table.style = "Table Grid"

        # Fill table
        for row_idx, row_data in enumerate(table_data):
            row = table.rows[row_idx]
            for col_idx, cell_text in enumerate(row_data):
                if col_idx < num_cols:
                    cell = row.cells[col_idx]
                    # Clear default paragraph
                    cell.text = ""
                    paragraph = cell.paragraphs[0]

                    # Process cell text with formatting
                    self._add_formatted_text(paragraph, cell_text)

                    # Bold header row
                    if row_idx == 0:
                        for run in paragraph.runs:
                            run.bold = True

    def _clean_text(self, text):
        """Clean markdown/html artifacts from text"""
        import re
        # Replace <br> and <br/> with newline
        text = re.sub(r'<br\s*/?>', '\n', text)
        # Remove ** markers (will handle bold separately)
        return text

    def _add_formatted_text(self, paragraph, text):
        """Add text with bold formatting and line breaks to paragraph"""
        import re
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        # First handle <br> tags - replace with newline
        text = re.sub(r'<br\s*/?>', '\n', text)

        # Split by bold markers
        parts = re.split(r'(\*\*.*?\*\*)', text)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                inner_text = part[2:-2]
                # Handle newlines within bold text
                lines = inner_text.split('\n')
                for i, line in enumerate(lines):
                    run = paragraph.add_run(line)
                    run.bold = True
                    if i < len(lines) - 1:
                        # Add line break
                        run.add_break()
            else:
                # Handle newlines in regular text
                lines = part.split('\n')
                for i, line in enumerate(lines):
                    paragraph.add_run(line)
                    if i < len(lines) - 1:
                        # Add line break
                        paragraph.add_run().add_break()

    def action_export_docx(self):
        """Export as DOCX file with table support"""
        self.ensure_one()
        if not self.generated_markdown:
            raise UserError("Không có nội dung để xuất")

        import base64
        import io
        import re

        try:
            from docx import Document
            from docx.shared import Pt, Inches
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            raise UserError("Cần cài đặt thư viện python-docx để xuất file DOCX")

        # Create DOCX document
        doc = Document()

        # Convert markdown to docx paragraphs (no auto title)
        lines = self.generated_markdown.split("\n")
        idx = 0

        while idx < len(lines):
            line = lines[idx]
            stripped = line.strip()

            if not stripped:
                doc.add_paragraph()
                idx += 1
            # Check for table start
            elif stripped.startswith("|") and "|" in stripped[1:]:
                table_data, idx = self._parse_markdown_table(lines, idx)
                if table_data:
                    self._add_table_to_docx(doc, table_data)
                    doc.add_paragraph()  # Add space after table
            elif stripped.startswith("# "):
                doc.add_heading(stripped[2:], level=1)
                idx += 1
            elif stripped.startswith("## "):
                doc.add_heading(stripped[3:], level=2)
                idx += 1
            elif stripped.startswith("### "):
                doc.add_heading(stripped[4:], level=3)
                idx += 1
            elif stripped.startswith("#### "):
                doc.add_heading(stripped[5:], level=4)
                idx += 1
            elif stripped.startswith("- ") or stripped.startswith("* "):
                p = doc.add_paragraph(style="List Bullet")
                self._add_formatted_text(p, stripped[2:])
                idx += 1
            elif re.match(r'^\d+\.\s', stripped):
                # Handle numbered list (any number)
                text = re.sub(r'^\d+\.\s', '', stripped)
                p = doc.add_paragraph(style="List Number")
                self._add_formatted_text(p, text)
                idx += 1
            elif stripped.startswith("**") and stripped.endswith("**"):
                p = doc.add_paragraph()
                p.add_run(stripped[2:-2]).bold = True
                idx += 1
            else:
                p = doc.add_paragraph()
                self._add_formatted_text(p, stripped)
                idx += 1

        # Save to bytes
        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        # Create attachment
        attachment = self.env["ir.attachment"].create({
            "name": f"{self.name}.docx",
            "type": "binary",
            "datas": base64.b64encode(file_stream.read()),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def action_export_markdown(self):
        """Export as markdown file"""
        self.ensure_one()
        if not self.generated_markdown:
            raise UserError("Không có nội dung để xuất")

        import base64

        # Create attachment
        attachment = self.env["ir.attachment"].create({
            "name": f"{self.name}.md",
            "type": "binary",
            "datas": base64.b64encode(self.generated_markdown.encode("utf-8")),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "text/markdown",
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def action_export_html(self):
        """Export as HTML file"""
        self.ensure_one()
        if not self.generated_content:
            raise UserError("No content to export")

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{self.name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
    </style>
</head>
<body>
{self.generated_content}
</body>
</html>"""

        attachment = self.env["ir.attachment"].create({
            "name": f"{self.name}.html",
            "type": "binary",
            "datas": html_content.encode("utf-8"),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "text/html",
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def _get_html_for_pdf(self):
        """Get HTML content formatted for PDF export"""
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{self.name}</title>
    <style>
        @page {{
            size: A4;
            margin: 2cm;
        }}
        body {{
            font-family: 'DejaVu Sans', Arial, sans-serif;
            font-size: 12pt;
            line-height: 1.6;
            color: #333;
        }}
        h1 {{
            font-size: 18pt;
            text-align: center;
            margin-bottom: 20px;
            color: #000;
        }}
        h2 {{
            font-size: 14pt;
            margin-top: 15px;
            margin-bottom: 10px;
            color: #000;
        }}
        h3 {{
            font-size: 12pt;
            margin-top: 12px;
            margin-bottom: 8px;
            color: #000;
        }}
        p {{
            margin: 8px 0;
            text-align: justify;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 15px 0;
        }}
        th, td {{
            border: 1px solid #333;
            padding: 8px 10px;
            text-align: left;
        }}
        th {{
            background-color: #f0f0f0;
            font-weight: bold;
        }}
        ul, ol {{
            margin: 10px 0;
            padding-left: 25px;
        }}
        li {{
            margin: 5px 0;
        }}
    </style>
</head>
<body>
    {self.generated_content}
</body>
</html>"""

    def action_export_pdf(self):
        """Export as PDF file using wkhtmltopdf"""
        self.ensure_one()
        if not self.generated_content:
            raise UserError("Không có nội dung để xuất")

        import base64
        import subprocess
        import tempfile
        import os

        html_content = self._get_html_for_pdf()

        # Create temp files
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as html_file:
            html_file.write(html_content)
            html_path = html_file.name

        pdf_path = html_path.replace('.html', '.pdf')

        try:
            # Use wkhtmltopdf (available in Odoo container)
            cmd = [
                'wkhtmltopdf',
                '--encoding', 'utf-8',
                '--page-size', 'A4',
                '--margin-top', '20mm',
                '--margin-bottom', '20mm',
                '--margin-left', '20mm',
                '--margin-right', '20mm',
                '--enable-local-file-access',
                html_path,
                pdf_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if not os.path.exists(pdf_path):
                _logger.error(f"wkhtmltopdf error: {result.stderr}")
                raise UserError(f"Lỗi tạo PDF: {result.stderr}")

            # Read PDF content
            with open(pdf_path, 'rb') as pdf_file:
                pdf_data = pdf_file.read()

            # Create attachment
            attachment = self.env["ir.attachment"].create({
                "name": f"{self.name}.pdf",
                "type": "binary",
                "datas": base64.b64encode(pdf_data),
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": "application/pdf",
            })

            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{attachment.id}?download=true",
                "target": "self",
            }

        finally:
            # Cleanup temp files
            if os.path.exists(html_path):
                os.unlink(html_path)
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)
