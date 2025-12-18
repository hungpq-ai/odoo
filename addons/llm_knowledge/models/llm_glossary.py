import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class LLMGlossary(models.Model):
    """Glossary for managing internal terms and definitions.

    Can be shared across multiple collections and prompts.
    """
    _name = "llm.glossary"
    _description = "Glossary for AI Context"
    _order = "name"
    _inherit = ["mail.thread"]

    name = fields.Char(
        string="Name",
        required=True,
        tracking=True,
        help="Name of this glossary (e.g., 'Project ABC Terms', 'Company Abbreviations')",
    )
    description = fields.Text(
        string="Description",
        help="Description of this glossary",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
    )
    term_ids = fields.One2many(
        "llm.glossary.term",
        "glossary_id",
        string="Terms",
        help="Terms and definitions in this glossary",
    )
    term_count = fields.Integer(
        string="Term Count",
        compute="_compute_term_count",
    )
    # Many2many to collections
    collection_ids = fields.Many2many(
        "llm.knowledge.collection",
        "llm_glossary_collection_rel",
        "glossary_id",
        "collection_id",
        string="Collections",
        help="Collections that use this glossary",
    )

    @api.depends("term_ids")
    def _compute_term_count(self):
        for record in self:
            record.term_count = len(record.term_ids)

    def get_formatted_context(self):
        """Get formatted glossary context for AI prompt.

        Returns:
            str: Formatted glossary text
        """
        self.ensure_one()

        terms = self.term_ids.filtered(lambda t: t.active)
        if not terms:
            return ""

        glossary_lines = []
        for term in terms.sorted(key=lambda t: t.term):
            glossary_lines.append(f"- **{term.term}**: {term.definition}")

        return f"## Glossary: {self.name}\n" + "\n".join(glossary_lines)

    @api.model
    def get_glossary_context(self, collection_ids=None, glossary_ids=None):
        """Get formatted glossary context for given collections or glossaries.

        Args:
            collection_ids: Collection recordset or list of IDs
            glossary_ids: Glossary recordset or list of IDs

        Returns:
            str: Formatted glossary text for AI context
        """
        glossaries = self.env["llm.glossary"]

        # Get glossaries from collections
        if collection_ids:
            if hasattr(collection_ids, 'ids'):
                collection_ids = collection_ids.ids
            if collection_ids:
                collections = self.env["llm.knowledge.collection"].browse(collection_ids)
                glossaries |= collections.mapped("glossary_ids")

        # Add directly specified glossaries
        if glossary_ids:
            if hasattr(glossary_ids, 'ids'):
                glossary_ids = glossary_ids.ids
            if glossary_ids:
                glossaries |= self.browse(glossary_ids)

        # Filter active glossaries
        glossaries = glossaries.filtered(lambda g: g.active)

        if not glossaries:
            return ""

        # Combine all glossary contexts
        contexts = []
        for glossary in glossaries:
            ctx = glossary.get_formatted_context()
            if ctx:
                contexts.append(ctx)

        return "\n\n".join(contexts)


class LLMGlossaryTerm(models.Model):
    """Individual term in a glossary."""
    _name = "llm.glossary.term"
    _description = "Glossary Term"
    _order = "term"

    glossary_id = fields.Many2one(
        "llm.glossary",
        string="Glossary",
        required=True,
        ondelete="cascade",
        index=True,
    )
    term = fields.Char(
        string="Term",
        required=True,
        index=True,
        help="The term or abbreviation to define",
    )
    definition = fields.Text(
        string="Definition",
        required=True,
        help="The definition or explanation of the term",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
    )

    _sql_constraints = [
        (
            "term_glossary_unique",
            "UNIQUE(term, glossary_id)",
            "Term must be unique within a glossary!",
        ),
    ]
