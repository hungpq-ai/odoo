import json
import logging
import subprocess
import threading
import select
import time
import uuid

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MCPManager:
    """Manager for MCP server subprocess communication"""

    _instances = {}
    _lock = threading.Lock()

    def __init__(self, server_id, command, args=None):
        self.server_id = server_id
        self.command = command
        self.args = args or []
        self.process = None
        self.reader_thread = None
        self.running = False
        self.responses = {}
        self.pending_requests = {}
        self.request_id = 0
        self._response_lock = threading.Lock()

    @classmethod
    def get_instance(cls, server_id, command=None, args=None):
        with cls._lock:
            if server_id not in cls._instances:
                if command is None:
                    return None
                cls._instances[server_id] = cls(server_id, command, args)
            return cls._instances[server_id]

    @classmethod
    def remove_instance(cls, server_id):
        with cls._lock:
            if server_id in cls._instances:
                instance = cls._instances.pop(server_id)
                instance.stop()

    def start(self):
        if self.running:
            return True

        try:
            cmd = [self.command] + self.args
            _logger.info(f"Starting MCP server: {' '.join(cmd)}")

            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            self.running = True
            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()

            # Initialize MCP protocol
            return self._initialize()

        except Exception as e:
            _logger.error(f"Failed to start MCP server: {e}")
            self.stop()
            raise

    def stop(self):
        self.running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None

    def _reader_loop(self):
        while self.running and self.process:
            try:
                ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
                if ready:
                    line = self.process.stdout.readline()
                    if line:
                        self._handle_message(line.strip())
                    elif self.process.poll() is not None:
                        _logger.warning("MCP process terminated")
                        self.running = False
                        break
            except Exception as e:
                _logger.error(f"Reader error: {e}")
                break

    def _handle_message(self, line):
        try:
            msg = json.loads(line)
            msg_id = msg.get("id")
            if msg_id is not None:
                with self._response_lock:
                    if msg_id in self.pending_requests:
                        event = self.pending_requests[msg_id]
                        self.responses[msg_id] = msg
                        event.set()
        except json.JSONDecodeError as e:
            _logger.debug(f"Non-JSON message: {line}")

    def _send_request(self, method, params=None, timeout=30):
        if not self.running or not self.process:
            raise UserError(_("MCP server is not running"))

        self.request_id += 1
        req_id = self.request_id

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params:
            request["params"] = params

        event = threading.Event()
        with self._response_lock:
            self.pending_requests[req_id] = event

        try:
            self.process.stdin.write(json.dumps(request) + "\n")
            self.process.stdin.flush()

            if event.wait(timeout=timeout):
                with self._response_lock:
                    response = self.responses.pop(req_id, None)
                    self.pending_requests.pop(req_id, None)

                if response:
                    if "error" in response:
                        raise UserError(_(
                            "MCP Error: %(message)s",
                            message=response["error"].get("message", "Unknown error")
                        ))
                    return response.get("result")
            else:
                raise UserError(_("MCP request timed out"))

        except BrokenPipeError:
            self.running = False
            raise UserError(_("MCP server connection lost"))

    def _initialize(self):
        result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "odoo-llm-mcp",
                "version": "18.0.1.0.0"
            }
        })

        # Send initialized notification
        self.process.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }) + "\n")
        self.process.stdin.flush()

        return result

    def list_tools(self):
        result = self._send_request("tools/list")
        return result.get("tools", []) if result else []

    def call_tool(self, name, arguments=None):
        return self._send_request("tools/call", {
            "name": name,
            "arguments": arguments or {}
        })


class MCPSSEManager:
    """Manager for MCP server communication via SSE (Server-Sent Events)

    MCP SSE transport protocol (based on official MCP Python SDK):
    1. GET /sse -> receives "event: endpoint" with "data: /messages/?session_id=xxx"
    2. POST /messages/?session_id=xxx -> send JSON-RPC requests
    3. Responses come back via SSE stream as "event: message"

    The SSE connection must be kept open continuously for receiving responses.
    """

    _instances = {}
    _lock = threading.Lock()

    def __init__(self, server_id, url, api_key=None):
        self.server_id = server_id
        # Base URL (e.g., https://mcp-mmvn.izysync.com)
        self.base_url = url.rstrip("/")
        if self.base_url.endswith("/sse"):
            self.base_url = self.base_url[:-4]
        self.sse_url = f"{self.base_url}/sse"
        self.api_key = api_key
        self.session_id = None
        self.messages_endpoint = None
        self.running = False
        self.sse_thread = None
        self.responses = {}
        self.pending_requests = {}
        self.request_id = 0
        self._response_lock = threading.Lock()
        self._endpoint_ready = threading.Event()

    @classmethod
    def get_instance(cls, server_id, url=None, api_key=None):
        with cls._lock:
            if server_id not in cls._instances:
                if url is None:
                    return None
                cls._instances[server_id] = cls(server_id, url, api_key)
            return cls._instances[server_id]

    @classmethod
    def remove_instance(cls, server_id):
        with cls._lock:
            if server_id in cls._instances:
                instance = cls._instances.pop(server_id)
                instance.stop()

    def _get_headers(self, for_sse=False):
        if for_sse:
            headers = {
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
            }
        else:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def start(self):
        if self.running:
            return True

        try:
            _logger.info(f"Starting MCP SSE connection to: {self.base_url}")

            self.running = True
            self._endpoint_ready.clear()

            # Start SSE reader thread - it will establish connection and read events
            self.sse_thread = threading.Thread(target=self._sse_reader_loop, daemon=True)
            self.sse_thread.start()

            # Wait for endpoint to be received
            if not self._endpoint_ready.wait(timeout=30):
                self.running = False
                raise UserError(_("Timeout waiting for SSE endpoint"))

            if not self.messages_endpoint:
                self.running = False
                raise UserError(_("Failed to get messages endpoint from SSE"))

            _logger.info(f"SSE connection ready, endpoint: {self.messages_endpoint}")

            # Initialize MCP protocol
            return self._initialize()

        except Exception as e:
            _logger.error(f"Failed to connect to MCP SSE server: {e}")
            self.stop()
            raise

    def stop(self):
        self.running = False
        self.session_id = None
        self.messages_endpoint = None
        self._endpoint_ready.clear()

    def _sse_reader_loop(self):
        """Read SSE events continuously - this runs in a separate thread"""
        _logger.info(f"SSE reader: connecting to {self.sse_url}")

        try:
            # Establish SSE connection
            response = requests.get(
                self.sse_url,
                headers=self._get_headers(for_sse=True),
                stream=True,
                timeout=(10, None),  # 10s connect timeout, no read timeout
            )
            response.raise_for_status()
            _logger.info("SSE reader: connection established")

            current_event = None
            for line in response.iter_lines(decode_unicode=True):
                if not self.running:
                    _logger.info("SSE reader: stopping (running=False)")
                    break

                if line:
                    line = line.strip()

                    if line.startswith(":"):
                        # Comment/ping line, ignore but log occasionally
                        continue

                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        _logger.debug(f"SSE reader: event type = {current_event}")

                    elif line.startswith("data:"):
                        data = line[5:].strip()

                        if current_event == "endpoint":
                            # Got the messages endpoint
                            self.messages_endpoint = data
                            _logger.info(f"SSE reader: got endpoint = {data}")
                            # Extract session_id if present
                            if "session_id=" in data:
                                self.session_id = data.split("session_id=")[1].split("&")[0]
                            # Signal that endpoint is ready
                            self._endpoint_ready.set()

                        elif current_event == "message":
                            # Got a response message
                            _logger.debug(f"SSE reader: message data = {data[:200]}")
                            self._handle_sse_message(data)

                        current_event = None
                else:
                    # Empty line marks end of event
                    current_event = None

        except requests.exceptions.Timeout:
            _logger.error("SSE reader: connection timeout")
        except requests.exceptions.ConnectionError as e:
            _logger.error(f"SSE reader: connection error: {e}")
        except Exception as e:
            _logger.error(f"SSE reader: unexpected error: {e}")
        finally:
            _logger.info("SSE reader: loop ended")
            self.running = False
            self._endpoint_ready.set()  # Unblock any waiters

    def _handle_sse_message(self, data):
        """Handle incoming SSE message"""
        try:
            msg = json.loads(data)
            msg_id = msg.get("id")
            _logger.debug(f"SSE message: id={msg_id}, pending={list(self.pending_requests.keys())}")

            if msg_id is not None:
                with self._response_lock:
                    if msg_id in self.pending_requests:
                        _logger.info(f"SSE message matches request {msg_id}")
                        event = self.pending_requests[msg_id]
                        self.responses[msg_id] = msg
                        event.set()
                    else:
                        _logger.warning(f"SSE message id={msg_id} has no pending request")
        except json.JSONDecodeError:
            _logger.warning(f"Non-JSON SSE message: {data[:100]}")

    def _get_messages_url(self):
        """Get the full URL for sending messages"""
        if not self.messages_endpoint:
            raise UserError(_("Not connected to MCP server"))

        # messages_endpoint might be relative (e.g., /messages/?session_id=xxx)
        # or absolute
        if self.messages_endpoint.startswith("http"):
            return self.messages_endpoint
        return f"{self.base_url}{self.messages_endpoint}"

    def _send_request(self, method, params=None, timeout=60):
        if not self.messages_endpoint:
            raise UserError(_("MCP server is not connected"))

        if not self.running:
            raise UserError(_("MCP SSE connection is not active"))

        self.request_id += 1
        req_id = self.request_id

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params:
            request["params"] = params

        # Set up event for async response
        event = threading.Event()
        with self._response_lock:
            self.pending_requests[req_id] = event

        try:
            messages_url = self._get_messages_url()
            _logger.info(f"MCP request [{req_id}] {method} -> {messages_url}")

            # Send POST request to messages endpoint
            response = requests.post(
                messages_url,
                json=request,
                headers=self._get_headers(for_sse=False),
                timeout=30,  # HTTP timeout for POST
            )
            response.raise_for_status()

            # Server returns 202 Accepted - response comes via SSE
            _logger.info(f"MCP request [{req_id}] POST returned {response.status_code}, waiting for SSE response...")

            # Wait for SSE response with longer timeout for tool execution
            if event.wait(timeout=timeout):
                with self._response_lock:
                    response_msg = self.responses.pop(req_id, None)
                    self.pending_requests.pop(req_id, None)

                if response_msg:
                    _logger.info(f"MCP request [{req_id}] got response")
                    if "error" in response_msg:
                        raise UserError(_(
                            "MCP Error: %(message)s",
                            message=response_msg["error"].get("message", "Unknown error")
                        ))
                    return response_msg.get("result")
                else:
                    _logger.error(f"MCP request [{req_id}] event set but no response found")
                    raise UserError(_("MCP response was lost"))
            else:
                _logger.error(f"MCP request [{req_id}] timed out after {timeout}s")
                raise UserError(_("MCP request timed out after %(timeout)s seconds", timeout=timeout))

        except requests.exceptions.Timeout:
            _logger.error(f"MCP request [{req_id}] HTTP POST timed out")
            raise UserError(_("MCP HTTP request timed out"))
        except requests.exceptions.ConnectionError as e:
            _logger.error(f"MCP request [{req_id}] connection error: {e}")
            self.running = False
            raise UserError(_("MCP server connection lost"))
        except requests.exceptions.HTTPError as e:
            _logger.error(f"MCP request [{req_id}] HTTP error: {e}")
            raise UserError(_("MCP HTTP error: %(error)s", error=str(e)))
        finally:
            # Clean up on error only - success path already cleaned up
            with self._response_lock:
                self.pending_requests.pop(req_id, None)
                self.responses.pop(req_id, None)

    def _initialize(self):
        result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "odoo-llm-mcp",
                "version": "18.0.1.0.0"
            }
        })

        # Send initialized notification (no response expected)
        try:
            messages_url = self._get_messages_url()
            requests.post(
                messages_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized"
                },
                headers=self._get_headers(for_sse=False),
                timeout=10,
            )
        except Exception as e:
            _logger.warning(f"Failed to send initialized notification: {e}")

        return result

    def list_tools(self):
        result = self._send_request("tools/list")
        return result.get("tools", []) if result else []

    def call_tool(self, name, arguments=None):
        return self._send_request("tools/call", {
            "name": name,
            "arguments": arguments or {}
        })


class LLMMCPServer(models.Model):
    _name = "llm.mcp.server"
    _description = "MCP Server Configuration"

    name = fields.Char(string="Name", required=True)
    transport = fields.Selection(
        [
            ("stdio", "Standard I/O"),
            ("sse", "SSE (HTTP)"),
        ],
        string="Transport",
        default="stdio",
        required=True,
    )
    # stdio fields
    command = fields.Char(string="Command", help="Command to start the MCP server")
    args = fields.Char(string="Arguments", help="Space-separated arguments")
    # SSE fields
    url = fields.Char(string="URL", help="MCP server URL (e.g., http://localhost:3000/mcp)")
    api_key = fields.Char(string="API Key", help="Optional API key for authentication")

    is_connected = fields.Boolean(string="Connected", default=False, readonly=True)
    is_active = fields.Boolean(string="Active", default=True)
    auto_connect = fields.Boolean(
        string="Tự động kết nối",
        default=False,
        help="Tự động kết nối và import tools khi Odoo khởi động"
    )

    protocol_version = fields.Char(string="Protocol Version", readonly=True)
    server_info = fields.Text(string="Server Info", readonly=True)

    tool_ids = fields.One2many("llm.tool", "mcp_server_id", string="Tools")

    @api.constrains("transport", "command", "url")
    def _check_transport_config(self):
        for record in self:
            if record.transport == "stdio" and not record.command:
                raise UserError(_("Command is required for stdio transport"))
            if record.transport == "sse" and not record.url:
                raise UserError(_("URL is required for SSE transport"))

    def _get_args_list(self):
        self.ensure_one()
        if not self.args:
            return []
        return self.args.split()

    def _get_manager(self):
        """Get or create the appropriate manager based on transport type"""
        self.ensure_one()
        if self.transport == "stdio":
            return MCPManager.get_instance(
                self.id,
                self.command,
                self._get_args_list()
            )
        elif self.transport == "sse":
            return MCPSSEManager.get_instance(
                self.id,
                self.url,
                self.api_key
            )
        else:
            raise UserError(_("Unknown transport type: %(transport)s", transport=self.transport))

    def _remove_manager(self):
        """Remove the manager instance"""
        self.ensure_one()
        if self.transport == "stdio":
            MCPManager.remove_instance(self.id)
        elif self.transport == "sse":
            MCPSSEManager.remove_instance(self.id)

    def start_server(self):
        self.ensure_one()
        try:
            manager = self._get_manager()
            result = manager.start()

            self.write({
                "is_connected": True,
                "protocol_version": result.get("protocolVersion") if result else None,
                "server_info": json.dumps(result.get("serverInfo", {}), indent=2) if result else None,
            })

            # Fetch tools
            self.list_tools()

            _logger.info(f"MCP Server '{self.name}' started successfully")

        except Exception as e:
            _logger.error(f"Failed to start MCP server: {e}")
            self.write({"is_connected": False})
            raise UserError(_("Failed to start MCP server: %(error)s", error=str(e)))

    def stop_server(self):
        self.ensure_one()
        self._remove_manager()
        self.write({"is_connected": False})
        _logger.info(f"MCP Server '{self.name}' stopped")

    def list_tools(self):
        self.ensure_one()
        manager = self._get_manager()
        if not manager or not manager.running:
            self.start_server()
            manager = self._get_manager()

        tools = manager.list_tools()
        self._update_tools(tools)
        return tools

    def _update_tools(self, tools):
        self.ensure_one()
        Tool = self.env["llm.tool"]

        existing_tools = {t.name: t for t in self.tool_ids}
        server_tool_names = set()

        for tool_data in tools:
            name = tool_data.get("name")
            server_tool_names.add(name)

            vals = {
                "name": name,
                "title": tool_data.get("title", name),
                "description": tool_data.get("description", ""),
                "mcp_server_id": self.id,
                "implementation": "mcp",
                "input_schema": json.dumps(tool_data.get("inputSchema", {})),
                "active": True,
            }

            if name in existing_tools:
                existing_tools[name].write(vals)
            else:
                Tool.create(vals)

        # Deactivate tools no longer on server
        for name, tool in existing_tools.items():
            if name not in server_tool_names:
                tool.write({"active": False})

    def execute_tool(self, tool_name, arguments=None):
        self.ensure_one()
        manager = self._get_manager()

        # Auto-reconnect if manager is not running
        if not manager or not manager.running:
            _logger.info(f"MCP server '{self.name}' manager not running, attempting to reconnect...")
            # Update DB state to reflect actual disconnected state
            if self.is_connected:
                self.write({"is_connected": False})
            self.start_server()
            manager = self._get_manager()
            if not manager or not manager.running:
                raise UserError(_("Failed to reconnect to MCP server"))

        try:
            return manager.call_tool(tool_name, arguments)
        except UserError as e:
            # If connection lost during call, try to reconnect and retry once
            error_msg = str(e)
            if "connection lost" in error_msg.lower() or "not running" in error_msg.lower():
                _logger.warning(f"MCP connection lost during tool call, attempting reconnect...")
                self.write({"is_connected": False})
                self._remove_manager()
                self.start_server()
                manager = self._get_manager()
                if manager and manager.running:
                    return manager.call_tool(tool_name, arguments)
            raise

    @api.model
    def _auto_connect_servers(self):
        """Auto-connect MCP servers that have auto_connect=True.
        Called on Odoo startup via post_init_hook.
        """
        servers = self.search([
            ('auto_connect', '=', True),
            ('is_active', '=', True),
        ])
        for server in servers:
            try:
                _logger.info(f"Auto-connecting MCP server: {server.name}")
                server.start_server()
                _logger.info(f"MCP server '{server.name}' auto-connected successfully")
            except Exception as e:
                _logger.warning(f"Failed to auto-connect MCP server '{server.name}': {e}")
