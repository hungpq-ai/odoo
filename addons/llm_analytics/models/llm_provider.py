import logging
import time
from odoo import api, models

_logger = logging.getLogger(__name__)


class LLMProviderAnalytics(models.Model):
    """Extend LLM Provider to auto-log usage analytics."""

    _inherit = "llm.provider"

    def _estimate_tokens(self, text):
        """Estimate token count from text.

        Uses a simple heuristic: ~4 characters per token for English,
        ~2 characters for Asian languages (CJK).
        This is a rough approximation.

        Args:
            text: String to estimate tokens for

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        text = str(text)

        # Count CJK characters (Chinese, Japanese, Korean)
        cjk_count = sum(1 for char in text if '\u4e00' <= char <= '\u9fff'
                       or '\u3040' <= char <= '\u309f'  # Hiragana
                       or '\u30a0' <= char <= '\u30ff'  # Katakana
                       or '\uac00' <= char <= '\ud7af')  # Korean

        # Non-CJK characters
        other_count = len(text) - cjk_count

        # CJK: ~1.5 tokens per character, Other: ~0.25 tokens per character (4 chars per token)
        estimated = int(cjk_count * 1.5 + other_count * 0.25)

        return max(1, estimated)  # At least 1 token

    def _estimate_messages_tokens(self, messages, prepend_messages=None):
        """Estimate input tokens from messages.

        Args:
            messages: mail.message recordset or list
            prepend_messages: Optional list of prepend message dicts

        Returns:
            Estimated input token count
        """
        total = 0

        # Estimate prepend messages
        if prepend_messages:
            for msg in prepend_messages:
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Handle multimodal content
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            total += self._estimate_tokens(item.get("text", ""))
                else:
                    total += self._estimate_tokens(content)

        # Estimate mail.message records
        if hasattr(messages, 'mapped'):
            # It's a recordset
            for msg in messages:
                total += self._estimate_tokens(msg.body or "")
        elif isinstance(messages, list):
            for msg in messages:
                if isinstance(msg, dict):
                    total += self._estimate_tokens(msg.get("content", ""))

        return total

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

        # Estimate input tokens before the call
        tokens_input = self._estimate_messages_tokens(messages, prepend_messages)

        try:
            result = super().chat(
                messages,
                model=model,
                stream=stream,
                tools=tools,
                prepend_messages=prepend_messages,
                **kwargs,
            )

            # Try to extract usage info if available (non-streaming)
            if not stream and isinstance(result, dict):
                usage = result.get("usage", {})
                # Use actual usage if available, otherwise keep estimate
                actual_input = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                actual_output = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
                if actual_input:
                    tokens_input = actual_input
                if actual_output:
                    tokens_output = actual_output
                elif result.get("content"):
                    # Estimate output tokens from response content
                    tokens_output = self._estimate_tokens(result.get("content", ""))

            # For streaming, we can't get output tokens here
            # They will be logged separately via log_stream_output if needed

            return result

        except Exception as e:
            status = "error"
            error_message = str(e)
            _logger.error(f"LLM chat error: {e}")
            raise

        finally:
            response_time = time.time() - start_time
            try:
                # For streaming, we'll estimate output later or log 0 for now
                # The actual output will be logged when stream completes
                self._log_usage(
                    model=model_record,
                    request_type="chat",
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    response_time=response_time,
                    status=status,
                    error_message=error_message,
                    is_streaming=stream,
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
        is_streaming=False,
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
            is_streaming: Whether this is a streaming request (output tokens may be updated later)
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

        log = UsageLog.create(vals)

        # For streaming requests, store the log ID so output tokens can be updated later
        if is_streaming:
            return log.id
        return log.id

    def log_stream_output(self, log_id, output_content):
        """Update a usage log with output tokens after streaming completes.

        Args:
            log_id: ID of the usage log to update
            output_content: The complete output content from the stream

        Returns:
            Updated log record or None
        """
        if not log_id or not output_content:
            return None

        try:
            UsageLog = self.env["llm.usage.log"].sudo()
            log = UsageLog.browse(log_id)
            if log.exists():
                tokens_output = self._estimate_tokens(output_content)
                # Recalculate cost with output tokens
                model = log.model_id if log.model_id else None
                cost = self._estimate_cost(model, log.tokens_input, tokens_output)
                log.write({
                    "tokens_output": tokens_output,
                    "cost": cost,
                })
                return log
        except Exception as e:
            _logger.warning(f"Failed to update stream output tokens: {e}")
        return None

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
