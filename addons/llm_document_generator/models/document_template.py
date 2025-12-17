import base64

from odoo import api, fields, models


class DocumentTemplate(models.Model):
    _name = "llm.document.template"
    _description = "Document Template"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence, name"

    name = fields.Char(string="Tên mẫu", required=True, tracking=True, translate=True)
    description = fields.Text(string="Mô tả", translate=True)
    category_id = fields.Many2one(
        "llm.document.category",
        string="Thể loại",
        required=True,
        tracking=True,
    )
    sequence = fields.Integer(string="Thứ tự", default=10)
    active = fields.Boolean(default=True, tracking=True)
    code = fields.Char(string="Mã", help="Mã kỹ thuật cho mẫu")

    # Sample template file - user can upload
    sample_file = fields.Binary(
        string="File mẫu",
        help="Upload file mẫu (DOCX, PDF, TXT) để AI tham khảo cấu trúc",
    )
    sample_filename = fields.Char(string="Tên file")
    sample_content = fields.Text(
        string="Nội dung mẫu",
        help="Nội dung văn bản mẫu - có thể nhập trực tiếp hoặc tự động trích xuất từ file",
    )

    # Prompt configuration
    system_prompt = fields.Text(
        string="System Prompt",
        required=True,
        help="Hướng dẫn cho AI về vai trò và cách viết",
        default="""Bạn là chuyên gia soạn thảo văn bản chuyên nghiệp.

NHIỆM VỤ: Tạo văn bản MỚI dựa trên MẪU được cung cấp.

QUY TẮC BẮT BUỘC:
1. GIỮ NGUYÊN CẤU TRÚC của mẫu (heading, sections, thứ tự)
2. GIỮ NGUYÊN FORMAT:
   - Nếu mẫu có TABLE → tạo TABLE với cùng cấu trúc cột
   - Nếu mẫu có danh sách đánh số → giữ danh sách đánh số
   - Nếu mẫu có bullet points → giữ bullet points
3. THAY THẾ NỘI DUNG phù hợp với yêu cầu mới
4. Sử dụng Markdown format:
   - Table: | Cột 1 | Cột 2 |
   - Heading: # ## ###
   - Bold: **text**
   - List: - item hoặc 1. item
5. KHÔNG sử dụng:
   - Mermaid diagrams (```mermaid)
   - Code blocks cho sơ đồ
   - Thay vào đó, mô tả sơ đồ bằng văn bản hoặc bảng""",
    )
    user_prompt_template = fields.Text(
        string="User Prompt",
        required=True,
        help="Mẫu prompt. Sử dụng {context} cho yêu cầu user, {sample} cho nội dung mẫu",
        default="""## MẪU VĂN BẢN GỐC:

{sample}

---

## YÊU CẦU TẠO VĂN BẢN MỚI:

{context}

---

Hãy tạo văn bản mới GIỐNG ĐÚNG CẤU TRÚC mẫu trên, thay nội dung theo yêu cầu.
Nếu mẫu có bảng (table) thì văn bản mới PHẢI có bảng với cùng format.
Output bằng Markdown.""",
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
        sample = self.sample_content or "(Không có mẫu)"
        return self.user_prompt_template.format(
            context=context,
            sample=sample,
            requirements=requirements or "",
        )
