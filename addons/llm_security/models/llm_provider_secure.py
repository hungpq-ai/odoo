"""
LLM Provider Security Enhancement
=================================

Extends llm.provider with:
- Encrypted API key storage
- Automatic retry with exponential backoff
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from .llm_retry_decorator import llm_retry, llm_retry_generator, DEFAULT_RETRY

_logger = logging.getLogger(__name__)


class LLMProviderSecure(models.Model):
    """
    Extends LLM Provider with security features.
    """
    _inherit = "llm.provider"

    # Flag to indicate if API key is stored encrypted
    api_key_encrypted = fields.Boolean(
        string="API Key Encrypted",
        default=False,
        help="Indicates if the API key is stored with encryption",
    )

    # Retry configuration
    retry_enabled = fields.Boolean(
        string="Enable Retry",
        default=True,
        help="Enable automatic retry with exponential backoff for API errors",
    )
    retry_max_attempts = fields.Integer(
        string="Max Retry Attempts",
        default=3,
        help="Maximum number of retry attempts for failed API calls",
    )
    retry_base_delay = fields.Float(
        string="Base Retry Delay (seconds)",
        default=2.0,
        help="Initial delay between retries (will increase exponentially)",
    )

    def write(self, vals):
        """Override write to encrypt API key if provided."""
        if "api_key" in vals and vals["api_key"]:
            # Store encrypted API key
            for record in self:
                self.env["llm.api.key"].set_api_key(
                    f"provider_{record.id}",
                    vals["api_key"]
                )
            # Mark as encrypted and clear plain text
            vals["api_key_encrypted"] = True
            vals["api_key"] = "***ENCRYPTED***"

        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to encrypt API key if provided."""
        records = super().create(vals_list)

        for record, vals in zip(records, vals_list):
            if vals.get("api_key") and vals["api_key"] != "***ENCRYPTED***":
                # Store encrypted API key
                self.env["llm.api.key"].set_api_key(
                    f"provider_{record.id}",
                    vals["api_key"]
                )
                # Mark as encrypted
                record.write({
                    "api_key_encrypted": True,
                    "api_key": "***ENCRYPTED***",
                })

        return records

    def _get_decrypted_api_key(self):
        """
        Get the decrypted API key for this provider.

        Returns:
            str: The decrypted API key, or None if not found
        """
        self.ensure_one()

        if self.api_key_encrypted:
            return self.env["llm.api.key"].get_api_key(f"provider_{self.id}")
        else:
            # Fallback to plain text (for backward compatibility)
            return self.api_key if self.api_key != "***ENCRYPTED***" else None

    @property
    def client(self):
        """
        Override client property to use decrypted API key.
        """
        # Temporarily set decrypted key for client initialization
        original_key = self.api_key
        decrypted_key = self._get_decrypted_api_key()

        if decrypted_key:
            # Use SQL to avoid triggering write encryption
            self.env.cr.execute(
                "UPDATE llm_provider SET api_key = %s WHERE id = %s",
                (decrypted_key, self.id)
            )
            self.invalidate_recordset(["api_key"])

        try:
            client = self._dispatch("get_client")
        finally:
            # Restore masked key
            if decrypted_key:
                self.env.cr.execute(
                    "UPDATE llm_provider SET api_key = %s WHERE id = %s",
                    (original_key or "***ENCRYPTED***", self.id)
                )
                self.invalidate_recordset(["api_key"])

        return client

    def chat(self, messages, model=None, stream=False, tools=None, prepend_messages=None, **kwargs):
        """
        Override chat to add retry logic.
        """
        if not self.retry_enabled:
            return super().chat(
                messages,
                model=model,
                stream=stream,
                tools=tools,
                prepend_messages=prepend_messages,
                **kwargs
            )

        if stream:
            return self._chat_with_retry_stream(
                messages, model, tools, prepend_messages, **kwargs
            )
        else:
            return self._chat_with_retry(
                messages, model, tools, prepend_messages, **kwargs
            )

    def _chat_with_retry(self, messages, model, tools, prepend_messages, **kwargs):
        """Chat with retry logic for non-streaming."""

        @llm_retry(
            max_retries=self.retry_max_attempts,
            base_delay=self.retry_base_delay,
        )
        def _do_chat():
            return super(LLMProviderSecure, self).chat(
                messages,
                model=model,
                stream=False,
                tools=tools,
                prepend_messages=prepend_messages,
                **kwargs
            )

        return _do_chat()

    def _chat_with_retry_stream(self, messages, model, tools, prepend_messages, **kwargs):
        """Chat with retry logic for streaming."""

        @llm_retry_generator(
            max_retries=self.retry_max_attempts,
            base_delay=self.retry_base_delay,
        )
        def _do_stream():
            return super(LLMProviderSecure, self).chat(
                messages,
                model=model,
                stream=True,
                tools=tools,
                prepend_messages=prepend_messages,
                **kwargs
            )

        return _do_stream()

    def embedding(self, texts, model=None):
        """
        Override embedding to add retry logic.
        """
        if not self.retry_enabled:
            return super().embedding(texts, model=model)

        @llm_retry(
            max_retries=self.retry_max_attempts,
            base_delay=self.retry_base_delay,
        )
        def _do_embedding():
            return super(LLMProviderSecure, self).embedding(texts, model=model)

        return _do_embedding()

    def action_test_connection(self):
        """
        Test connection to the provider API.
        """
        self.ensure_one()

        try:
            # Try to get client
            client = self.client
            if client:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Connection Test",
                        "message": f"Successfully connected to {self.name}",
                        "type": "success",
                        "sticky": False,
                    },
                }
        except Exception as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Connection Test Failed",
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }

    def action_migrate_to_encrypted(self):
        """
        Migrate existing plain-text API keys to encrypted storage.
        """
        migrated = 0
        for record in self.search([("api_key_encrypted", "=", False)]):
            if record.api_key and record.api_key != "***ENCRYPTED***":
                self.env["llm.api.key"].set_api_key(
                    f"provider_{record.id}",
                    record.api_key
                )
                record.write({
                    "api_key_encrypted": True,
                    "api_key": "***ENCRYPTED***",
                })
                migrated += 1
                _logger.info(f"Migrated API key for provider {record.name} to encrypted storage")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Migration Complete",
                "message": f"Migrated {migrated} API keys to encrypted storage",
                "type": "success",
                "sticky": False,
            },
        }
