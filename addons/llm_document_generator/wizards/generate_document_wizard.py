from odoo import api, fields, models


class GenerateDocumentWizard(models.TransientModel):
    _name = "llm.generate.document.wizard"
    _description = "Generate Document Wizard"

    # Template selection (includes category)
    template_id = fields.Many2one(
        "llm.document.template",
        string="Document Type",
        required=True,
    )
    category_id = fields.Many2one(
        related="template_id.category_id",
        string="Category",
        readonly=True,
    )

    # Requirements
    requirements = fields.Text(
        string="Requirements",
        required=True,
        help="Describe the requirements for the document to be generated",
    )

    # LLM Model Selection
    model_id = fields.Many2one(
        "llm.model",
        string="AI Model",
        domain="[('model_use', 'in', ['chat', 'completion'])]",
        required=True,
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

    def action_generate(self):
        """Create generation record and redirect to form (don't generate yet)"""
        self.ensure_one()

        # Generate name from template + timestamp
        from datetime import datetime
        name = f"{self.template_id.name} - {datetime.now().strftime('%d/%m/%Y %H:%M')}"

        vals = {
            "name": name,
            "template_id": self.template_id.id,
            "requirements": self.requirements,
            "selected_model_id": self.model_id.id,
            "state": "draft",  # Start in draft, user will click Generate
        }

        generation = self.env["llm.document.generation"].create(vals)

        # Return action to view the generation form
        # User will click "Generate" button there to see loading
        return {
            "type": "ir.actions.act_window",
            "name": "Generated Document",
            "res_model": "llm.document.generation",
            "res_id": generation.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_generate_now(self):
        """Create generation record and generate immediately"""
        self.ensure_one()

        # Generate name from template + timestamp
        from datetime import datetime
        name = f"{self.template_id.name} - {datetime.now().strftime('%d/%m/%Y %H:%M')}"

        vals = {
            "name": name,
            "template_id": self.template_id.id,
            "requirements": self.requirements,
            "selected_model_id": self.model_id.id,
        }

        generation = self.env["llm.document.generation"].create(vals)

        # Start generation immediately
        generation.action_generate()

        # Return action to view the generation
        return {
            "type": "ir.actions.act_window",
            "name": "Generated Document",
            "res_model": "llm.document.generation",
            "res_id": generation.id,
            "view_mode": "form",
            "target": "current",
        }
