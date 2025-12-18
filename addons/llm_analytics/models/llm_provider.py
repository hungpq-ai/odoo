import logging
import time
from odoo import api, models

_logger = logging.getLogger(__name__)


class LLMProviderAnalytics(models.Model):
    """Extend LLM Provider to auto-log usage analytics."""

    _inherit = "llm.provider"

    def chat(
        self,
        messages,
        model=None,
        stream=False,
        tools=None,
        prepend_messages=None,
        **kwargs,
    ):
        """Override chat to log usage analytics."""
        start_time = time.time()
        model_record = self.get_model(model, "chat")
        error_message = None
        status = "success"
        tokens_input = 0
        tokens_output = 0

        try:
            result = super().chat(
                messages,
                model=model,
                stream=stream,
                tools=tools,
                prepend_messages=prepend_messages,
                **kwargs,
            )

            # Try to extract usage info if available
            if not stream and isinstance(result, dict):
                usage = result.get("usage", {})
                tokens_input = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                tokens_output = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)

            return result

        except Exception as e:
            status = "error"
            error_message = str(e)
            _logger.error(f"LLM chat error: {e}")
            raise

        finally:
            response_time = time.time() - start_time
            try:
                self._log_usage(
                    model=model_record,
                    request_type="chat",
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    response_time=response_time,
                    status=status,
                    error_message=error_message,
                )
            except Exception as log_error:
                _logger.warning(f"Failed to log usage: {log_error}")

    def embedding(self, texts, model=None):
        """Override embedding to log usage analytics."""
        start_time = time.time()
        model_record = self.get_model(model, "embedding")
        error_message = None
        status = "success"

        try:
            result = super().embedding(texts, model=model)
            return result

        except Exception as e:
            status = "error"
            error_message = str(e)
            raise

        finally:
            response_time = time.time() - start_time
            tokens_input = sum(len(text.split()) for text in texts) if texts else 0

            try:
                self._log_usage(
                    model=model_record,
                    request_type="embedding",
                    tokens_input=tokens_input,
                    tokens_output=0,
                    response_time=response_time,
                    status=status,
                    error_message=error_message,
                )
            except Exception as log_error:
                _logger.warning(f"Failed to log usage: {log_error}")

    def generate(self, input_data, model=None, stream=False, **kwargs):
        """Override generate to log usage analytics."""
        start_time = time.time()
        model_record = self.get_model(model, "chat") if model else None
        error_message = None
        status = "success"

        try:
            result = super().generate(input_data, model=model, stream=stream, **kwargs)
            return result

        except Exception as e:
            status = "error"
            error_message = str(e)
            raise

        finally:
            response_time = time.time() - start_time
            try:
                self._log_usage(
                    model=model_record,
                    request_type="generation",
                    tokens_input=0,
                    tokens_output=0,
                    response_time=response_time,
                    status=status,
                    error_message=error_message,
                )
            except Exception as log_error:
                _logger.warning(f"Failed to log usage: {log_error}")

    def _log_usage(
        self,
        model=None,
        request_type="chat",
        tokens_input=0,
        tokens_output=0,
        response_time=0.0,
        status="success",
        error_message=None,
    ):
        """Log usage to llm.usage.log.

        Args:
            model: llm.model record
            request_type: Type of request
            tokens_input: Input token count
            tokens_output: Output token count
            response_time: Response time in seconds
            status: Request status
            error_message: Error message if any
        """
        UsageLog = self.env["llm.usage.log"].sudo()

        # Calculate cost (rough estimate based on common pricing)
        cost = self._estimate_cost(model, tokens_input, tokens_output)

        vals = {
            "request_type": request_type,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "cost": cost,
            "response_time": response_time,
            "status": status,
            "error_message": error_message,
        }

        if model:
            vals["model_id"] = model.id
            vals["model_name"] = model.name

        UsageLog.create(vals)

    def _estimate_cost(self, model, tokens_input, tokens_output):
        """Estimate cost based on model and token usage.

        This is a rough estimate. For accurate costs, providers should
        override this method with their specific pricing.

        Args:
            model: llm.model record
            tokens_input: Input token count
            tokens_output: Output token count

        Returns:
            Estimated cost in USD
        """
        if not model:
            return 0.0

        # Default pricing tiers (per 1K tokens)
        # These are rough estimates - actual pricing varies by provider/model
        model_name = (model.name or "").lower()

        # GPT-4 class models
        if "gpt-4" in model_name or "claude-3-opus" in model_name:
            input_rate = 0.03  # $0.03 per 1K input tokens
            output_rate = 0.06  # $0.06 per 1K output tokens
        # GPT-3.5 / Claude Sonnet class
        elif "gpt-3.5" in model_name or "claude-3-sonnet" in model_name or "claude-3-5" in model_name:
            input_rate = 0.003
            output_rate = 0.006
        # Claude Haiku / smaller models
        elif "haiku" in model_name or "mini" in model_name:
            input_rate = 0.00025
            output_rate = 0.00125
        # Embedding models
        elif "embed" in model_name:
            input_rate = 0.0001
            output_rate = 0.0
        # Default for unknown models
        else:
            input_rate = 0.002
            output_rate = 0.002

        cost = (tokens_input / 1000 * input_rate) + (tokens_output / 1000 * output_rate)
        return round(cost, 6)
