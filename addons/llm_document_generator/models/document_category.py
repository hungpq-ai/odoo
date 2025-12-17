from odoo import api, fields, models


class DocumentCategory(models.Model):
    _name = "llm.document.category"
    _description = "Document Category"
    _parent_name = "parent_id"
    _parent_store = True
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(help="Technical code for this category")
    description = fields.Text(translate=True)
    parent_id = fields.Many2one(
        "llm.document.category",
        string="Parent Category",
        index=True,
        ondelete="cascade",
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many(
        "llm.document.category", "parent_id", string="Child Categories"
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    complete_name = fields.Char(
        compute="_compute_complete_name", store=True, recursive=True
    )
    template_count = fields.Integer(compute="_compute_template_count")

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = (
                    f"{category.parent_id.complete_name} / {category.name}"
                )
            else:
                category.complete_name = category.name

    def _compute_template_count(self):
        for category in self:
            category.template_count = self.env["llm.document.template"].search_count(
                [("category_id", "=", category.id)]
            )

    @api.constrains("parent_id")
    def _check_parent_id(self):
        if self._has_cycle():
            raise models.ValidationError("Error! You cannot create recursive categories.")
