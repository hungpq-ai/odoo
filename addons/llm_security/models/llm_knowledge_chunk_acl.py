"""
LLM Knowledge Chunk Access Control
==================================

Implements RAG Access Control (1.3.1):
- Override search to enforce record rules
- Users can only search vectors they have read access to
- Integrates with Odoo's existing security model

Security Logic:
1. Before querying vectors, get record_rules of current user
2. Only query vectors where res_id belongs to records user can read
3. Filter results based on user's access rights to the source documents
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression

_logger = logging.getLogger(__name__)


class LLMKnowledgeChunkACL(models.Model):
    """
    Extends llm.knowledge.chunk with access control for RAG search.

    Security is enforced by:
    1. Checking user's access to the source resource (llm.resource)
    2. Checking user's access to the underlying record (res_model, res_id)
    """
    _inherit = "llm.knowledge.chunk"

    # Cache for user's accessible resource IDs
    _access_cache = {}

    def _get_user_accessible_resource_ids(self, user_id=None):
        """
        Get list of resource IDs that the current user can access.

        This checks:
        1. Resource visibility settings (public/private/restricted)
        2. Owner, allowed_user_ids, allowed_group_ids
        3. Access to the underlying records (res_model, res_id)

        Args:
            user_id: User ID to check access for (default: current user)

        Returns:
            list: List of accessible llm.resource IDs
        """
        if user_id is None:
            user_id = self.env.uid

        # Check cache first
        cache_key = f"user_{user_id}"
        if cache_key in self._access_cache:
            return self._access_cache[cache_key]

        user = self.env["res.users"].browse(user_id)
        user_group_ids = set(user.groups_id.ids)

        # Get all resources
        LLMResource = self.env["llm.resource"].sudo()
        all_resources = LLMResource.search([])

        accessible_ids = []

        for resource in all_resources:
            has_access = False

            # Check 1: Owner always has access
            if resource.owner_id.id == user_id:
                has_access = True

            # Check 2: Visibility-based access
            elif resource.visibility == "public":
                # All internal users have access
                has_access = user.has_group("base.group_user")

            elif resource.visibility == "private":
                # Only owner (already checked above)
                has_access = False

            elif resource.visibility == "restricted":
                # Check allowed_user_ids
                if user_id in resource.allowed_user_ids.ids:
                    has_access = True
                # Check allowed_group_ids
                elif user_group_ids & set(resource.allowed_group_ids.ids):
                    has_access = True
                # Check department group match
                elif resource.department_group_id and resource.department_group_id.id in user_group_ids:
                    has_access = True

            # Check 3: If has visibility access, also check underlying record access
            if has_access and resource.res_model and resource.res_id:
                if resource.res_model in self.env:
                    try:
                        underlying_record = self.env[resource.res_model].browse(resource.res_id)
                        if underlying_record.exists():
                            underlying_record.check_access_rights("read")
                            underlying_record.check_access_rule("read")
                        else:
                            has_access = False
                    except Exception:
                        # User doesn't have access to underlying record
                        has_access = False

            if has_access:
                accessible_ids.append(resource.id)

        # Cache for performance
        self._access_cache[cache_key] = accessible_ids

        _logger.debug(
            f"User {user_id} has access to {len(accessible_ids)} resources "
            f"out of {len(all_resources)} total"
        )

        return accessible_ids

    def _apply_access_control_domain(self, domain):
        """
        Apply access control to a search domain.

        Adds domain filter to only return chunks from resources
        the current user can access.

        Args:
            domain: Original search domain

        Returns:
            list: Domain with access control applied
        """
        # Skip access control for superuser
        if self.env.su:
            return domain

        # Get accessible resource IDs for current user
        accessible_resource_ids = self._get_user_accessible_resource_ids()

        if not accessible_resource_ids:
            # User has no access to any resources, return empty domain
            return [("id", "=", False)]

        # Add resource filter to domain
        access_domain = [("resource_id", "in", accessible_resource_ids)]

        if domain:
            return expression.AND([domain, access_domain])
        else:
            return access_domain

    @api.model
    def search(self, args, offset=0, limit=None, order=None, **kwargs):
        """
        Override search to apply access control.

        This ensures users can only search/find chunks from resources
        they have read access to.
        """
        # Apply access control to domain
        secure_args = self._apply_access_control_domain(args)

        _logger.debug(
            f"RAG search with access control: "
            f"original domain={args}, secure domain={secure_args}"
        )

        return super().search(
            secure_args,
            offset=offset,
            limit=limit,
            order=order,
            **kwargs
        )

    @api.model
    def search_count(self, args, **kwargs):
        """
        Override search_count to apply access control.
        """
        secure_args = self._apply_access_control_domain(args)
        return super().search_count(secure_args, **kwargs)

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        """
        Override read_group to apply access control.
        """
        secure_domain = self._apply_access_control_domain(domain)
        return super().read_group(
            secure_domain, fields, groupby,
            offset=offset, limit=limit, orderby=orderby, lazy=lazy
        )

    def _vector_search_aggregate(
        self,
        collections,
        query_vector,
        vector_search_term,
        model_vector_map,
        search_args,
        min_similarity,
        query_operator,
        offset,
        limit,
        count,
    ):
        """
        Override vector search to apply access control.

        This is the core RAG search function that needs access control.
        Note: Access control is already applied in search() via _apply_access_control_domain(),
        so we don't need to apply it again here. The search_args already contains the
        resource_id filter from the parent search() call.
        """
        # Access control is already applied in search() method via _apply_access_control_domain()
        # Just pass through to parent without adding duplicate filters
        return super()._vector_search_aggregate(
            collections=collections,
            query_vector=query_vector,
            vector_search_term=vector_search_term,
            model_vector_map=model_vector_map,
            search_args=search_args,
            min_similarity=min_similarity,
            query_operator=query_operator,
            offset=offset,
            limit=limit,
            count=count,
        )

    @api.model
    def clear_access_cache(self, user_id=None):
        """
        Clear the access control cache.

        Should be called when:
        - User's access rights change
        - Record rules are modified
        - Resources are created/deleted

        Args:
            user_id: Specific user to clear cache for (None = all users)
        """
        if user_id:
            cache_key = f"user_{user_id}"
            if cache_key in self._access_cache:
                del self._access_cache[cache_key]
                _logger.debug(f"Cleared access cache for user {user_id}")
        else:
            self._access_cache.clear()
            _logger.debug("Cleared all access caches")


class LLMResourceACL(models.Model):
    """
    Extends llm.resource with ownership and access control fields.

    Access Control Logic:
    - If visibility = 'public': All internal users can access
    - If visibility = 'private': Only owner can access
    - If visibility = 'restricted': Only allowed_user_ids and allowed_group_ids can access
    """
    _inherit = "llm.resource"

    # Ownership fields
    owner_id = fields.Many2one(
        "res.users",
        string="Owner",
        default=lambda self: self.env.user,
        index=True,
        help="User who owns this resource. Has full access regardless of visibility settings.",
    )
    # Department field - only available if hr module is installed
    # Using res.groups for department-like access control instead
    department_group_id = fields.Many2one(
        "res.groups",
        string="Department Group",
        index=True,
        help="Group representing the department. Users in this group can access restricted resources.",
    )

    # Visibility settings
    visibility = fields.Selection(
        [
            ("public", "Public (All Internal Users)"),
            ("private", "Private (Owner Only)"),
            ("restricted", "Restricted (Specific Users/Groups)"),
        ],
        string="Visibility",
        default="public",
        required=True,
        help="Controls who can access this resource in RAG search results.",
    )

    # Access control lists
    allowed_user_ids = fields.Many2many(
        "res.users",
        "llm_resource_allowed_users_rel",
        "resource_id",
        "user_id",
        string="Allowed Users",
        help="Users who can access this resource (when visibility is 'restricted').",
    )
    allowed_group_ids = fields.Many2many(
        "res.groups",
        "llm_resource_allowed_groups_rel",
        "resource_id",
        "group_id",
        string="Allowed Groups",
        help="Groups who can access this resource (when visibility is 'restricted').",
    )

    def _check_user_access(self, user_id=None):
        """
        Check if a user has access to this resource based on visibility settings.

        Args:
            user_id: User ID to check (default: current user)

        Returns:
            bool: True if user has access
        """
        self.ensure_one()
        if user_id is None:
            user_id = self.env.uid

        user = self.env["res.users"].browse(user_id)

        # Owner always has access
        if self.owner_id.id == user_id:
            return True

        # Check visibility
        if self.visibility == "public":
            # All internal users have access
            return user.has_group("base.group_user")

        elif self.visibility == "private":
            # Only owner has access (already checked above)
            return False

        elif self.visibility == "restricted":
            # Check if user is in allowed_user_ids
            if user_id in self.allowed_user_ids.ids:
                return True
            # Check if user is in any allowed group
            user_group_ids = set(user.groups_id.ids)
            allowed_group_ids = set(self.allowed_group_ids.ids)
            if user_group_ids & allowed_group_ids:
                return True
            # Check if user is in the department group
            if self.department_group_id and self.department_group_id.id in user_group_ids:
                return True
            return False

        return False

    @api.model_create_multi
    def create(self, vals_list):
        """Set owner on create and auto-set department for managers."""
        user = self.env.user

        for vals in vals_list:
            if "owner_id" not in vals:
                vals["owner_id"] = self.env.uid

            # Auto-set department_group_id and visibility for department managers
            # if they haven't explicitly set these values
            if "department_group_id" not in vals or not vals.get("department_group_id"):
                # Check if user is HR Department Manager
                if user.has_group("llm_security.group_hr_department_manager"):
                    hr_dept_group = self.env.ref("llm_security.group_hr_department", raise_if_not_found=False)
                    if hr_dept_group:
                        vals["department_group_id"] = hr_dept_group.id
                        if "visibility" not in vals:
                            vals["visibility"] = "restricted"
                # Check if user is Sale Department Manager
                elif user.has_group("llm_security.group_sale_department_manager"):
                    sale_dept_group = self.env.ref("llm_security.group_sale_department", raise_if_not_found=False)
                    if sale_dept_group:
                        vals["department_group_id"] = sale_dept_group.id
                        if "visibility" not in vals:
                            vals["visibility"] = "restricted"

        result = super().create(vals_list)
        self.env["llm.knowledge.chunk"].clear_access_cache()
        return result

    def write(self, vals):
        """Clear access cache when resources are modified."""
        result = super().write(vals)
        # Clear cache if access-relevant fields changed
        access_fields = [
            "model_id", "res_id", "res_model", "collection_ids",
            "owner_id", "department_group_id", "visibility",
            "allowed_user_ids", "allowed_group_ids"
        ]
        if any(f in vals for f in access_fields):
            self.env["llm.knowledge.chunk"].clear_access_cache()
        return result

    def unlink(self):
        """
        Override unlink to provide friendly error message when user doesn't have permission.
        """
        for resource in self:
            # Check if user can delete this resource
            can_delete = False
            user = self.env.user

            # Superuser can always delete
            if self.env.su:
                can_delete = True
            # Owner can always delete their own resources
            elif resource.owner_id.id == user.id:
                can_delete = True
            # Check if user is a department manager for this resource's department
            elif resource.department_group_id:
                # HR Department Manager can delete HR Department resources
                if (resource.department_group_id.name == "HR Department" and
                        user.has_group("llm_security.group_hr_department_manager")):
                    can_delete = True
                # Sale Department Manager can delete Sale Department resources
                elif (resource.department_group_id.name == "Sale Department" and
                        user.has_group("llm_security.group_sale_department_manager")):
                    can_delete = True

            if not can_delete:
                raise UserError(
                    "Bạn không có quyền xóa resource này.\n"
                    "Vui lòng liên hệ quản trị viên hoặc chủ sở hữu resource để được hỗ trợ.\n\n"
                    "(You don't have permission to delete this resource. "
                    "Please contact the administrator or resource owner for assistance.)"
                )

        result = super().unlink()
        self.env["llm.knowledge.chunk"].clear_access_cache()
        return result


class LLMKnowledgeCollectionACL(models.Model):
    """
    Extends llm.knowledge.collection with ownership and access control fields.

    Access Control Logic:
    - If visibility = 'public': All internal users can access
    - If visibility = 'private': Only owner can access
    - If visibility = 'restricted': Only department group members can access
    """
    _inherit = "llm.knowledge.collection"

    # Ownership fields
    owner_id = fields.Many2one(
        "res.users",
        string="Owner",
        default=lambda self: self.env.user,
        index=True,
        help="User who owns this collection. Has full access regardless of visibility settings.",
    )
    department_group_id = fields.Many2one(
        "res.groups",
        string="Department Group",
        index=True,
        help="Group representing the department. Users in this group can access restricted collections.",
    )

    # Visibility settings
    visibility = fields.Selection(
        [
            ("public", "Public (All Internal Users)"),
            ("private", "Private (Owner Only)"),
            ("restricted", "Restricted (Department Only)"),
        ],
        string="Visibility",
        default="public",
        required=True,
        help="Controls who can access this collection.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Set owner on create and auto-set department for managers."""
        user = self.env.user

        for vals in vals_list:
            if "owner_id" not in vals:
                vals["owner_id"] = self.env.uid

            # Auto-set department_group_id and visibility for department managers
            if "department_group_id" not in vals or not vals.get("department_group_id"):
                # Check if user is HR Department Manager
                if user.has_group("llm_security.group_hr_department_manager"):
                    hr_dept_group = self.env.ref("llm_security.group_hr_department", raise_if_not_found=False)
                    if hr_dept_group:
                        vals["department_group_id"] = hr_dept_group.id
                        if "visibility" not in vals:
                            vals["visibility"] = "restricted"
                # Check if user is Sale Department Manager
                elif user.has_group("llm_security.group_sale_department_manager"):
                    sale_dept_group = self.env.ref("llm_security.group_sale_department", raise_if_not_found=False)
                    if sale_dept_group:
                        vals["department_group_id"] = sale_dept_group.id
                        if "visibility" not in vals:
                            vals["visibility"] = "restricted"

        return super().create(vals_list)

    def write(self, vals):
        """Clear access cache when collections are modified."""
        result = super().write(vals)
        access_fields = ["owner_id", "department_group_id", "visibility"]
        if any(f in vals for f in access_fields):
            self.env["llm.knowledge.chunk"].clear_access_cache()
        return result

    def unlink(self):
        """
        Override unlink to provide friendly error message when user doesn't have permission.
        """
        for collection in self:
            # Check if user can delete this collection
            can_delete = False
            user = self.env.user

            # Superuser can always delete
            if self.env.su:
                can_delete = True
            # Owner can always delete their own collections
            elif collection.owner_id.id == user.id:
                can_delete = True
            # Check if user is a department manager for this collection's department
            elif collection.department_group_id:
                # HR Department Manager can delete HR Department collections
                if (collection.department_group_id.name == "HR Department" and
                        user.has_group("llm_security.group_hr_department_manager")):
                    can_delete = True
                # Sale Department Manager can delete Sale Department collections
                elif (collection.department_group_id.name == "Sale Department" and
                        user.has_group("llm_security.group_sale_department_manager")):
                    can_delete = True

            if not can_delete:
                raise UserError(
                    "Bạn không có quyền xóa collection này.\n"
                    "Vui lòng liên hệ quản trị viên hoặc chủ sở hữu collection để được hỗ trợ.\n\n"
                    "(You don't have permission to delete this collection. "
                    "Please contact the administrator or collection owner for assistance.)"
                )

        result = super().unlink()
        self.env["llm.knowledge.chunk"].clear_access_cache()
        return result


class ResUsers(models.Model):
    """
    Extends res.users to clear access cache when user rights change.
    """
    _inherit = "res.users"

    def write(self, vals):
        """Clear access cache when user groups change."""
        result = super().write(vals)
        if "groups_id" in vals:
            for user in self:
                self.env["llm.knowledge.chunk"].clear_access_cache(user.id)
        return result


class IrRule(models.Model):
    """
    Extends ir.rule to clear access cache when rules change.
    """
    _inherit = "ir.rule"

    @api.model_create_multi
    def create(self, vals_list):
        """Clear access cache when rules are created."""
        result = super().create(vals_list)
        self.env["llm.knowledge.chunk"].clear_access_cache()
        return result

    def write(self, vals):
        """Clear access cache when rules are modified."""
        result = super().write(vals)
        self.env["llm.knowledge.chunk"].clear_access_cache()
        return result

    def unlink(self):
        """Clear access cache when rules are deleted."""
        result = super().unlink()
        self.env["llm.knowledge.chunk"].clear_access_cache()
        return result
