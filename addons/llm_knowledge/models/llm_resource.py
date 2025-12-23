import hashlib
import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class LLMResource(models.Model):
    _name = "llm.resource"
    _description = "LLM Resource for Document Management"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _sql_constraints = [
        (
            "unique_resource_reference",
            "UNIQUE(model_id, res_id)",
            "A resource already exists for this record. Please use the existing resource.",
        ),
    ]

    name = fields.Char(
        string="Name",
        required=True,
        tracking=True,
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Related Model",
        required=True,
        tracking=True,
        ondelete="cascade",
        help="The model of the referenced document",
    )
    res_model = fields.Char(
        string="Model Name",
        related="model_id.model",
        store=True,
        readonly=True,
        help="Technical name of the related model",
    )
    res_id = fields.Integer(
        string="Record ID",
        required=True,
        tracking=True,
        help="The ID of the referenced record",
    )
    content = fields.Text(
        string="Content",
        help="Markdown representation of the resource content",
    )
    content_hash = fields.Char(
        string="Content Hash",
        readonly=True,
        index=True,
        help="SHA256 hash of content for change detection",
    )
    lang = fields.Selection(
        selection="_get_available_languages",
        string="Language",
        default="vi",
        help="Primary language of the resource content",
    )
    external_url = fields.Char(
        string="External URL",
        compute="_compute_external_url",
        store=True,
        help="External URL from the related record if available",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("retrieved", "Retrieved"),
            ("parsed", "Parsed"),
            ("chunked", "Chunked"),
            ("ready", "Ready"),
        ],
        string="State",
        default="draft",
        tracking=True,
    )
    lock_date = fields.Datetime(
        string="Lock Date",
        tracking=True,
        help="Date when the resource was locked for processing",
    )
    kanban_state = fields.Selection(
        [
            ("normal", "Ready"),
            ("blocked", "Blocked"),
            ("done", "Done"),
        ],
        string="Kanban State",
        compute="_compute_kanban_state",
        store=True,
    )

    collection_ids = fields.Many2many(
        "llm.knowledge.collection",
        relation="llm_knowledge_resource_collection_rel",
        column1="resource_id",
        column2="collection_id",
        string="Collections",
    )

    @api.depends("res_model", "res_id")
    def _compute_external_url(self):
        for resource in self:
            resource.external_url = False
            if not resource.res_model or not resource.res_id:
                continue

            resource.external_url = self._get_record_external_url(
                resource.res_model, resource.res_id
            )

    def _get_record_external_url(self, res_model, res_id):
        """
        Get the external URL for a record based on its model and ID.

        This method can be extended by other modules to support additional models.

        :param res_model: The model name
        :param res_id: The record ID
        :return: The external URL or False
        """
        try:
            # Get the related record
            if res_model in self.env:
                record = self.env[res_model].browse(res_id)
                if not record.exists():
                    return False

                # Case 1: Handle ir.attachment with type 'url'
                if res_model == "ir.attachment" and hasattr(record, "type"):
                    if record.type == "url" and hasattr(record, "url"):
                        return record.url

                # Case 2: Check if record has an external_url field
                elif hasattr(record, "external_url"):
                    return record.external_url

        except Exception as e:
            _logger.warning(
                "Error computing external URL for resource model %s, id %s: %s",
                res_model,
                res_id,
                str(e),
            )

        return False

    @api.model
    def _get_available_languages(self):
        """Get available languages for resources"""
        return [
            ("vi", "Tiếng Việt"),
            ("en", "English"),
            ("zh", "中文"),
            ("ja", "日本語"),
            ("ko", "한국어"),
            ("fr", "Français"),
            ("de", "Deutsch"),
            ("es", "Español"),
            ("pt", "Português"),
            ("ru", "Русский"),
            ("ar", "العربية"),
            ("th", "ไทย"),
            ("id", "Bahasa Indonesia"),
            ("ms", "Bahasa Melayu"),
        ]

    def _compute_content_hash(self, content):
        """Compute SHA256 hash of content"""
        if not content:
            return False
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _check_content_changed(self):
        """Check if content has changed by comparing hash"""
        self.ensure_one()
        if not self.content:
            return False
        new_hash = self._compute_content_hash(self.content)
        return new_hash != self.content_hash

    @api.depends("lock_date")
    def _compute_kanban_state(self):
        for record in self:
            record.kanban_state = "blocked" if record.lock_date else "normal"

    def _lock(self, state_filter=None, stale_lock_minutes=10):
        """Lock resources for processing and return the ones successfully locked"""
        now = fields.Datetime.now()
        stale_lock_threshold = now - timedelta(minutes=stale_lock_minutes)

        # Find resources that are not locked or have stale locks
        domain = [
            ("id", "in", self.ids),
            "|",
            ("lock_date", "=", False),
            ("lock_date", "<", stale_lock_threshold),
        ]
        if state_filter:
            domain.append(("state", "=", state_filter))

        unlocked_docs = self.env["llm.resource"].search(domain)

        if unlocked_docs:
            unlocked_docs.write({"lock_date": now})

        return unlocked_docs

    def _unlock(self):
        """Unlock resources after processing"""
        return self.write({"lock_date": False})

    def process_resource(self):
        """
        Process resources through retrieval, parsing, chunking and embedding.
        Can handle multiple resources at once, processing them through
        as many pipeline stages as possible based on their current states.
        """
        # Stage 1: Retrieve content for draft resources
        draft_docs = self.filtered(lambda d: d.state == "draft")
        if draft_docs:
            draft_docs.retrieve()

        # Stage 2: Parse retrieved resources
        retrieved_docs = self.filtered(lambda d: d.state == "retrieved")
        if retrieved_docs:
            retrieved_docs.parse()

        # Process chunking and embedding
        inconsistent_docs = self.filtered(
            lambda d: d.state in ["chunked", "ready"] and not d.chunk_ids
        )

        if inconsistent_docs:
            inconsistent_docs.write({"state": "parsed"})

        # Process chunks for parsed documents
        parsed_docs = self.filtered(lambda d: d.state == "parsed")
        if parsed_docs:
            parsed_docs.chunk()

        # Embed chunked documents
        chunked_docs = self.filtered(lambda d: d.state == "chunked")
        if chunked_docs:
            chunked_docs.embed()

        return True

    def action_open_resource(self):
        """Open the resource in form view."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "llm.resource",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def action_mass_process_resources(self):
        """
        Server action handler for mass processing resources.
        This will be triggered from the server action in the UI.
        """
        active_ids = self.env.context.get("active_ids", [])
        if not active_ids:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No Resources Selected"),
                    "message": _("Please select resources to process."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        resources = self.browse(active_ids)
        # Process all selected resources
        result = resources.process_resource()

        if result:
            return {
                "type": "ir.actions.client",
                "tag": "reload",
            }

        else:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Processing Failed"),
                    "message": _("Mass processing resources failed"),
                    "sticky": False,
                    "type": "danger",
                },
            }

    def action_mass_unlock(self):
        """
        Mass unlock action for the server action.
        """
        # Unlock the resources
        self._unlock()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Resources Unlocked"),
                "message": _("%(count)s resources have been unlocked", count=len(self)),
                "sticky": False,
                "type": "success",
            },
        }

    def action_mass_reset(self):
        """
        Mass reset action for the server action.
        Resets all non-draft resources back to draft state.
        """
        # Get active IDs from context
        active_ids = self.env.context.get("active_ids", [])
        if not active_ids:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No Resources Selected"),
                    "message": _("Please select resources to reset."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        resources = self.browse(active_ids)
        # Filter resources that are not in draft state
        non_draft_resources = resources.filtered(lambda r: r.state != "draft")

        if not non_draft_resources:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No Resources Reset"),
                    "message": _("No resources found that need resetting."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        # Reset resources to draft state and unlock them
        non_draft_resources.write(
            {
                "state": "draft",
                "lock_date": False,
            }
        )

        # Reload the view to reflect changes
        return {
            "type": "ir.actions.client",
            "tag": "reload",
            "params": {
                "menu_id": self.env.context.get("menu_id"),
                "action": self.env.context.get("action"),
            },
        }

    def action_embed(self):
        """Action handler for embedding document chunks"""
        result = self.embed()
        # Return appropriate notification
        if result:
            self._post_styled_message(
                _("Document embedding process completed successfully."),
                "success",
            )
            return True
        else:
            message = (
                _(
                    "Document embedding process did not complete properly, check logs on resources."
                ),
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Embedding"),
                    "message": message,
                    "type": "warning",
                    "sticky": False,
                },
            }

    def action_recompute_hash(self):
        """Recompute content hash and check if re-indexing is needed"""
        reindex_needed = self.env["llm.resource"]

        for resource in self:
            if not resource.content:
                resource._post_styled_message(
                    _("No content to hash"),
                    "warning",
                )
                continue

            new_hash = resource._compute_content_hash(resource.content)
            old_hash = resource.content_hash

            if old_hash != new_hash:
                # Content changed - update hash and mark for re-index
                resource.write({"content_hash": new_hash})
                if resource.state == "ready":
                    reindex_needed |= resource
                resource._post_styled_message(
                    _("Hash updated: content has changed. Old: %(old)s... → New: %(new)s...") % {
                        "old": (old_hash or "None")[:16],
                        "new": new_hash[:16],
                    },
                    "info",
                )
            else:
                resource._post_styled_message(
                    _("Hash verified: content unchanged (%(hash)s...)") % {"hash": new_hash[:16]},
                    "success",
                )

        # Trigger re-index for changed resources
        if reindex_needed:
            reindex_needed.write({"state": "parsed"})
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Hash Recomputed"),
                    "message": _("%(count)s resources have changed and will be re-indexed.") % {"count": len(reindex_needed)},
                    "type": "info",
                },
            }

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Hash Verified"),
                "message": _("Content hash verified for %(count)s resources.") % {"count": len(self)},
                "type": "success",
            },
        }

    def action_reindex(self):
        """Reindex a single resource's chunks"""
        self.ensure_one()

        # Get all collections this resource belongs to
        collections = self.collection_ids
        if not collections:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Reindexing"),
                    "message": _("Resource does not belong to any collections."),
                    "type": "warning",
                },
            }

        # Get all chunks for this resource
        chunks = self.chunk_ids
        if not chunks:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Reindexing"),
                    "message": _("No chunks found for this resource."),
                    "type": "warning",
                },
            }

        # Set resource back to chunked state to trigger re-embedding
        self.write({"state": "chunked"})

        # Delete chunks from each collection's store
        for collection in collections:
            if collection.store_id:
                # Remove chunks from this resource from the store
                try:
                    collection.delete_vectors(ids=chunks.ids)
                except Exception as e:
                    _logger.warning(
                        f"Error removing vectors for chunks from collection {collection.id}: {str(e)}"
                    )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Reindexing"),
                "message": _(
                    f"Reset resource for re-embedding in {len(collections)} collections."
                ),
                "type": "success",
            },
        }

    def action_mass_reindex(self):
        """Reindex multiple resources at once"""
        collections = self.env["llm.knowledge.collection"]
        for resource in self:
            # Add to collections set
            collections |= resource.collection_ids

        # Reindex each affected collection
        for collection in collections:
            collection.reindex_collection()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Reindexing"),
                "message": _(
                    f"Reindexing request submitted for {len(collections)} collections."
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def embed(self):
        """
        Embed resource chunks in collections by calling the collection's embed_resources method.
        Called after chunking to create vector representations.

        Returns:
            bool: True if any resources were successfully embedded, False otherwise
        """
        # Filter to only get resources in chunked state
        chunked_docs = self.filtered(lambda d: d.state == "chunked")

        if not chunked_docs:
            self._post_styled_message(
                _("No resources in 'chunked' state to embed."),
                "warning",
            )
            return False

        # Get all collections for these resources
        collections = self.env["llm.knowledge.collection"]
        for doc in chunked_docs:
            collections |= doc.collection_ids

        # If no collections, resources can't be embedded
        if not collections:
            self._post_styled_message(
                _("No collections found for the selected resources."),
                "warning",
            )
            return False

        # Track if any resources were embedded
        any_embedded = False

        # Let each collection handle the embedding
        for collection in collections:
            result = collection.embed_resources(specific_resource_ids=chunked_docs.ids)
            # Check if result is not None before trying to access .get()
            if (
                result
                and result.get("success")
                and result.get("processed_resources", 0) > 0
            ):
                any_embedded = True

        if not any_embedded:
            self._post_styled_message(
                _(
                    "No resources could be embedded. Check that resources have correct collections and collections have valid embedding models and stores."
                ),
                "warning",
            )
        # Return True only if resources were actually embedded
        return any_embedded

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to handle collection_ids, apply chunking settings, and auto-process"""
        # Create the resources first
        resources = super().create(vals_list)

        # Process each resource that has collections
        for resource in resources:
            if resource.collection_ids and resource.state not in ["chunked", "ready"]:
                # Get the first collection's settings
                collection = resource.collection_ids[0]
                # Update the resource with the collection's settings
                update_vals = {
                    "target_chunk_size": collection.default_chunk_size,
                    "target_chunk_overlap": collection.default_chunk_overlap,
                    "chunker": collection.default_chunker,
                    "parser": collection.default_parser,
                }
                resource.write(update_vals)

                # Auto-process resource immediately (retrieve -> parse -> chunk -> embed)
                try:
                    resource.process_resource()
                    _logger.info(
                        f"Auto-processed resource {resource.id} ({resource.name}) on creation - state: {resource.state}"
                    )
                    resource._post_styled_message(
                        _("Auto-processed: chunked and embedded successfully"),
                        "success",
                    )
                except Exception as e:
                    _logger.error(
                        f"Failed to auto-process resource {resource.id} on creation: {e}",
                        exc_info=True
                    )
                    resource._post_styled_message(
                        _("Auto-process failed: %s") % str(e),
                        "error",
                    )
            elif not resource.collection_ids:
                _logger.info(
                    f"Resource {resource.id} ({resource.name}) created without collection - skipping auto-process"
                )

        return resources

    def _reset_state_if_needed(self):
        """Reset resource state to 'chunked' if it's in 'ready' state and not in any collection."""
        self.ensure_one()
        if self.state == "ready" and not self.collection_ids:
            self.write({"state": "chunked"})
            _logger.info(
                f"Reset resource {self.id} to 'chunked' state after removal from all collections"
            )
            self._post_styled_message(
                _("Reset to 'chunked' state after removal from all collections"),
                "info",
            )
        return True

    def _handle_collection_ids_change(self, old_collections_by_resource):
        """Handle changes to collection_ids field.

        Args:
            old_collections_by_resource: Dictionary mapping resource IDs to their previous collection IDs
        """
        for resource in self:
            old_collection_ids = old_collections_by_resource.get(resource.id, [])
            current_collection_ids = resource.collection_ids.ids

            # Find collections that the resource was removed from
            removed_collection_ids = [
                cid for cid in old_collection_ids if cid not in current_collection_ids
            ]

            # Clean up vectors in those collections' stores
            if removed_collection_ids:
                collections = self.env["llm.knowledge.collection"].browse(
                    removed_collection_ids
                )
                for collection in collections:
                    # Use the collection's method to handle resource removal
                    collection._handle_removed_resources([resource.id])

        return True

    def write(self, vals):
        """Override write to handle collection_ids changes, content hash updates, and cleanup vectors if needed"""
        # Track collections before the write
        resources_collections = {}
        if "collection_ids" in vals:
            for resource in self:
                resources_collections[resource.id] = resource.collection_ids.ids

        # Handle content changes - compute hash and trigger re-index if needed
        content_changed_resources = self.env["llm.resource"]
        if "content" in vals and vals.get("content"):
            new_hash = self._compute_content_hash(vals["content"])
            vals["content_hash"] = new_hash
            # Track resources where content actually changed
            for resource in self:
                if resource.content_hash != new_hash and resource.state == "ready":
                    content_changed_resources |= resource

        # Perform the write operation
        result = super().write(vals)

        # Handle collection changes
        if "collection_ids" in vals:
            self._handle_collection_ids_change(resources_collections)

        # Trigger re-index for resources with changed content
        if content_changed_resources:
            _logger.info(
                f"Content changed for {len(content_changed_resources)} resources, triggering re-index"
            )
            for resource in content_changed_resources:
                resource._post_styled_message(
                    _("Content changed detected, resource will be re-indexed"),
                    "info",
                )
            # Reset state to trigger re-processing
            content_changed_resources.write({"state": "parsed"})

        return result

    # ==========================================
    # Cron Job Methods for Auto-Indexing
    # ==========================================

    @api.model
    def _cron_auto_process_resources(self, batch_size=50):
        """
        Cron job to automatically process resources through the pipeline.

        This method:
        1. Finds all resources not yet in 'ready' state
        2. Processes them through retrieve -> parse -> chunk -> embed
        3. Runs in batches to avoid timeout

        Args:
            batch_size: Number of resources to process per run (default: 50)

        Returns:
            dict: Summary of processed resources
        """
        _logger.info("Starting auto-process resources cron job")

        # Find resources that need processing (not in ready state, not locked)
        now = fields.Datetime.now()
        stale_lock_threshold = now - timedelta(minutes=10)

        domain = [
            ("state", "!=", "ready"),
            ("collection_ids", "!=", False),  # Must belong to at least one collection
            "|",
            ("lock_date", "=", False),
            ("lock_date", "<", stale_lock_threshold),
        ]

        resources_to_process = self.search(domain, limit=batch_size)

        if not resources_to_process:
            _logger.info("No resources to auto-process")
            return {"processed": 0, "success": True}

        _logger.info(f"Found {len(resources_to_process)} resources to auto-process")

        processed_count = 0
        error_count = 0

        for resource in resources_to_process:
            try:
                resource.process_resource()
                processed_count += 1
                _logger.info(f"Auto-processed resource {resource.id}: {resource.name}")
            except Exception as e:
                error_count += 1
                _logger.error(f"Error auto-processing resource {resource.id}: {str(e)}")
                # Unlock the resource so it can be retried
                resource._unlock()

        _logger.info(
            f"Auto-process cron completed: {processed_count} processed, {error_count} errors"
        )

        return {
            "processed": processed_count,
            "errors": error_count,
            "success": error_count == 0,
        }

    @api.model
    def _cron_auto_index_attachments(self, collection_id=None, batch_size=20):
        """
        Cron job to automatically index new ir.attachments into collections.

        This method:
        1. Finds attachments not yet linked to any llm.resource
        2. Creates llm.resource records for them
        3. Adds them to the specified collection (or default collection)
        4. Triggers processing

        Args:
            collection_id: Specific collection ID to add resources to (optional)
            batch_size: Number of attachments to process per run (default: 20)

        Returns:
            dict: Summary of indexed attachments
        """
        _logger.info("Starting auto-index attachments cron job")

        # Get existing attachment IDs that are already resources
        existing_attachment_ids = self.search([
            ("res_model", "=", "ir.attachment")
        ]).mapped("res_id")

        # Find attachments that are not yet indexed
        # Filter: PDF, DOC, TXT files that are binary type
        attachment_domain = [
            ("id", "not in", existing_attachment_ids),
            ("type", "=", "binary"),
            ("mimetype", "in", [
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "text/plain",
                "text/markdown",
                "text/html",
            ]),
        ]

        attachments = self.env["ir.attachment"].sudo().search(
            attachment_domain, limit=batch_size
        )

        if not attachments:
            _logger.info("No new attachments to index")
            return {"indexed": 0, "success": True}

        _logger.info(f"Found {len(attachments)} attachments to index")

        # Get collection to add resources to
        collection = None
        if collection_id:
            collection = self.env["llm.knowledge.collection"].browse(collection_id)
            if not collection.exists():
                _logger.warning(f"Collection {collection_id} not found")
                collection = None

        # If no specific collection, try to find a default one
        if not collection:
            collection = self.env["llm.knowledge.collection"].search([
                ("active", "=", True),
                ("store_id", "!=", False),
                ("embedding_model_id", "!=", False),
            ], limit=1)

        if not collection:
            _logger.warning("No valid collection found for auto-indexing")
            return {"indexed": 0, "success": False, "error": "No collection available"}

        # Get ir.model for ir.attachment
        attachment_model = self.env["ir.model"].sudo().search([
            ("model", "=", "ir.attachment")
        ], limit=1)

        if not attachment_model:
            _logger.error("ir.attachment model not found")
            return {"indexed": 0, "success": False, "error": "Model not found"}

        indexed_count = 0
        error_count = 0

        for attachment in attachments:
            try:
                # Create llm.resource for this attachment
                resource = self.create({
                    "name": attachment.name or f"Attachment {attachment.id}",
                    "model_id": attachment_model.id,
                    "res_id": attachment.id,
                    "collection_ids": [(4, collection.id)],
                })
                indexed_count += 1
                _logger.info(f"Created resource {resource.id} for attachment {attachment.id}")

            except Exception as e:
                error_count += 1
                _logger.error(f"Error indexing attachment {attachment.id}: {str(e)}")

        _logger.info(
            f"Auto-index attachments completed: {indexed_count} indexed, {error_count} errors"
        )

        return {
            "indexed": indexed_count,
            "errors": error_count,
            "collection": collection.name,
            "success": error_count == 0,
        }
