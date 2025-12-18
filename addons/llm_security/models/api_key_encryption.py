"""
API Key Encryption Module
=========================

Provides secure storage for API keys using Fernet symmetric encryption.
Keys are stored encrypted in ir.config_parameter.

Usage:
    # Store encrypted API key
    self.env['llm.api.key'].set_api_key('openai', 'sk-xxx...')

    # Retrieve decrypted API key
    api_key = self.env['llm.api.key'].get_api_key('openai')
"""

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Parameter name for storing the master encryption key
MASTER_KEY_PARAM = "llm.security.master_key"
API_KEY_PREFIX = "llm.api_key."


class LLMApiKeyManager(models.AbstractModel):
    """
    Abstract model for managing encrypted API keys.

    API keys are encrypted using Fernet symmetric encryption.
    The master key is automatically generated and stored securely.
    """
    _name = "llm.api.key"
    _description = "LLM API Key Manager"

    @api.model
    def _get_or_create_master_key(self):
        """
        Get or create the master encryption key.

        The master key is stored in ir.config_parameter.
        If it doesn't exist, a new one is generated.

        Returns:
            bytes: The Fernet-compatible master key
        """
        ICP = self.env["ir.config_parameter"].sudo()
        master_key = ICP.get_param(MASTER_KEY_PARAM)

        if not master_key:
            # Generate a new Fernet key
            master_key = Fernet.generate_key().decode()
            ICP.set_param(MASTER_KEY_PARAM, master_key)
            _logger.info("Generated new LLM API encryption master key")

        return master_key.encode()

    @api.model
    def _get_fernet(self):
        """
        Get a Fernet instance with the master key.

        Returns:
            Fernet: Configured Fernet instance for encryption/decryption
        """
        master_key = self._get_or_create_master_key()
        return Fernet(master_key)

    @api.model
    def set_api_key(self, provider_name, api_key):
        """
        Store an API key securely (encrypted).

        Args:
            provider_name: Identifier for the provider (e.g., 'openai', 'anthropic')
            api_key: The plain text API key to store

        Returns:
            bool: True if successful
        """
        if not api_key:
            return False

        try:
            fernet = self._get_fernet()
            encrypted_key = fernet.encrypt(api_key.encode()).decode()

            param_name = f"{API_KEY_PREFIX}{provider_name}"
            self.env["ir.config_parameter"].sudo().set_param(param_name, encrypted_key)

            _logger.info(f"API key for '{provider_name}' stored securely")
            return True

        except Exception as e:
            _logger.error(f"Failed to encrypt API key for '{provider_name}': {e}")
            raise UserError(f"Failed to store API key: {e}")

    @api.model
    def get_api_key(self, provider_name):
        """
        Retrieve and decrypt an API key.

        Args:
            provider_name: Identifier for the provider

        Returns:
            str: The decrypted API key, or None if not found
        """
        param_name = f"{API_KEY_PREFIX}{provider_name}"
        encrypted_key = self.env["ir.config_parameter"].sudo().get_param(param_name)

        if not encrypted_key:
            return None

        try:
            fernet = self._get_fernet()
            decrypted_key = fernet.decrypt(encrypted_key.encode()).decode()
            return decrypted_key

        except InvalidToken:
            _logger.error(
                f"Failed to decrypt API key for '{provider_name}'. "
                "The master key may have changed."
            )
            return None
        except Exception as e:
            _logger.error(f"Error decrypting API key for '{provider_name}': {e}")
            return None

    @api.model
    def delete_api_key(self, provider_name):
        """
        Delete a stored API key.

        Args:
            provider_name: Identifier for the provider

        Returns:
            bool: True if deleted, False if not found
        """
        param_name = f"{API_KEY_PREFIX}{provider_name}"
        ICP = self.env["ir.config_parameter"].sudo()

        if ICP.get_param(param_name):
            ICP.set_param(param_name, False)
            _logger.info(f"API key for '{provider_name}' deleted")
            return True
        return False

    @api.model
    def list_providers(self):
        """
        List all providers with stored API keys.

        Returns:
            list: List of provider names
        """
        ICP = self.env["ir.config_parameter"].sudo()
        params = ICP.search([("key", "like", API_KEY_PREFIX)])

        providers = []
        for param in params:
            if param.key.startswith(API_KEY_PREFIX):
                provider_name = param.key[len(API_KEY_PREFIX):]
                providers.append(provider_name)

        return providers

    @api.model
    def rotate_master_key(self):
        """
        Rotate the master encryption key.

        This will:
        1. Decrypt all existing API keys with the old key
        2. Generate a new master key
        3. Re-encrypt all API keys with the new key

        Returns:
            dict: Result with success status and count of rotated keys
        """
        providers = self.list_providers()

        # Decrypt all keys with old master key
        decrypted_keys = {}
        for provider in providers:
            key = self.get_api_key(provider)
            if key:
                decrypted_keys[provider] = key

        # Generate new master key
        ICP = self.env["ir.config_parameter"].sudo()
        new_master_key = Fernet.generate_key().decode()
        ICP.set_param(MASTER_KEY_PARAM, new_master_key)

        _logger.info("Master encryption key rotated")

        # Re-encrypt all keys with new master key
        success_count = 0
        for provider, key in decrypted_keys.items():
            if self.set_api_key(provider, key):
                success_count += 1

        return {
            "success": True,
            "rotated_count": success_count,
            "total_providers": len(providers),
        }
