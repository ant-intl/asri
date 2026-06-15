"""
MCP Client wrapper supporting Custom HTTP and stdio clients.

External packages can register additional client types via plugins.
"""
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional, List, Dict

import httpx

logger = logging.getLogger(__name__)


class BaseMCPClient(ABC):
    """Abstract base class for MCP clients."""
    
    @abstractmethod
    async def connect(self) -> None:
        """Connect to MCP server."""
        pass
    
    @abstractmethod
    async def list_tools(self) -> list[dict]:
        """Return list of available tools.
        
        Returns:
            List of tool dicts with format:
            [
                {
                    "name": "tool_name",
                    "description": "Tool description",
                    "inputSchema": {...}
                },
                ...
            ]
        """
        pass
    
    @abstractmethod
    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call a remote tool and return result.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments as dict
            
        Returns:
            Tool execution result (can be any type)
        """
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up resources."""
        pass


class CustomMCPClient(BaseMCPClient):
    """
    Custom HTTP MCP client for non-standard MCP protocol.

    This client handles MCP services that use a custom JSON format
    instead of the standard JSON-RPC protocol.

    Request format:
        - list_tools: {"endpoint": "...", "mcpName": "..."}
        - execute: {"endpoint": "...", "arguments": "...", "toolName": "..."}

    Response format:
        {"data": {...}, "needRetry": bool, "resultCode": "SUCCESS", "success": bool}
    """

    def __init__(self, config):
        # Base URL for the MCP service
        self.base_url = config.endpoint or ""
        # SSE endpoint path
        self.sse_endpoint = config.sse_endpoint or ""
        # MCP service name
        self.mcp_name = config.mcp_name or ""
        # API paths
        self.list_tools_path = config.list_tools_path or "/sample/mcp/listTools"
        self.execute_path = config.execute_path or "/sample/mcp/execute"
        # Timeout
        self.timeout = config.timeout
        self._http_client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Initialize HTTP client with connection pool."""
        self._http_client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(max_keepalive_connections=10),
        )
        logger.info(f"CustomMCPClient connected to {self.base_url}")

    async def list_tools(self) -> list[dict]:
        """
        List available tools from MCP server.

        POST {base_url}/sample/mcp/listTools
        Body: {"endpoint": "...", "mcpName": "..."}
        """
        if not self._http_client:
            raise RuntimeError("CustomMCPClient not connected")

        url = f"{self.base_url}{self.list_tools_path}"
        payload = {
            "endpoint": self.sse_endpoint,
            "mcpName": self.mcp_name,
        }

        try:
            response = await self._http_client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()

            data = response.json()

            # Parse response: {"data": [...], "success": true}
            if data.get("success"):
                return data.get("data", [])
            else:
                logger.warning(
                    f"list_tools failed: {data.get('resultCode')}, {data.get('resultMsg')}"
                )
                return []

        except Exception as e:
            logger.error(f"Failed to list tools: {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """
        Call a remote MCP tool.

        POST {base_url}/sample/mcp/execute
        Body: {"endpoint": "...", "arguments": "...", "toolName": "..."}

        Note: arguments is sent as a JSON string, not an object.
        """
        if not self._http_client:
            raise RuntimeError("CustomMCPClient not connected")

        url = f"{self.base_url}{self.execute_path}"

        # arguments must be a JSON string
        payload = {
            "endpoint": self.sse_endpoint,
            "arguments": json.dumps(arguments),
            "toolName": tool_name,
        }

        logger.debug(f"Calling CustomMCP tool '{tool_name}' with args: {arguments}")

        try:
            response = await self._http_client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            logger.debug(f"Calling CustomMCP tool response: {response.text}")

            data = response.json()
            return self._parse_response(data)

        except Exception as e:
            logger.error(f"CustomMCP tool call failed: {e}")
            raise

    async def cleanup(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            logger.debug("CustomMCPClient cleaned up")

    def _parse_response(self, data: dict) -> Any:
        """
        Parse custom MCP response format.

        Format: {"data": {...}, "needRetry": bool, "resultCode": "SUCCESS", "success": bool}
        """
        # Check business-level success
        if not data.get("success"):
            error_msg = data.get("resultMsg", "Unknown error")
            result_code = data.get("resultCode", "UNKNOWN")
            logger.warning(f"MCP call failed: {result_code} - {error_msg}")
            return {"error": error_msg, "resultCode": result_code}

        # Check if retry is needed
        if data.get("needRetry"):
            logger.warning("MCP returned needRetry=true")

        # Extract data field
        result_data = data.get("data", {})

        # Handle content format (if present)
        if isinstance(result_data, dict) and "content" in result_data:
            try:
                # Similar to existing MCP: content[0].text
                raw_text = result_data["content"][0]["text"]
                # Try to parse as JSON
                try:
                    return json.loads(raw_text)
                except (json.JSONDecodeError, TypeError):
                    return raw_text
            except (KeyError, IndexError) as e:
                logger.warning(f"Failed to extract content text: {e}")
                return result_data

        return result_data


class StdioMCPClient(BaseMCPClient):
    """
    MCP client that communicates via stdio (stdin/stdout) with a subprocess.

    Used for MCP servers started via npx or other commands.
    Communicates using JSON-RPC protocol over stdin/stdout.
    """

    def __init__(self, config):
        """Initialize stdio MCP client.

        Args:
            config: Config object with:
                - command: str (e.g., "npx")
                - args: list[str] (e.g., ["-y", "tavily-mcp@latest"])
                - env: dict[str, str] (environment variables)
                - timeout: int (timeout in seconds)
        """
        self.config = config
        self.command = config.command
        self.args = config.args or []
        self.env = config.env or {}
        self.timeout = config.timeout or 30

        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Start the MCP server subprocess."""
        try:
            # Prepare environment
            import os
            process_env = os.environ.copy()
            process_env.update(self.env)

            # Start subprocess
            full_command = [self.command] + self.args
            logger.info(f"Starting MCP server: {' '.join(full_command)}")

            self._process = await asyncio.create_subprocess_exec(
                *full_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env
            )

            # Start background task to read responses
            self._reader_task = asyncio.create_task(self._read_responses())

            # Initialize MCP connection
            await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "asri-mcp-client",
                    "version": "1.0.0"
                }
            })

            logger.info(f"StdioMCPClient connected to {self.command} {' '.join(self.args)}")

        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            await self.cleanup()
            raise

    async def _send_request(self, method: str, params: dict = None) -> Any:
        """Send JSON-RPC request and wait for response."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("MCP server process not running")

        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method
        }
        if params:
            request["params"] = params

        # Create future for response
        future = asyncio.Future()
        self._pending_requests[request_id] = future

        # Send request
        request_str = json.dumps(request) + "\n"
        self._process.stdin.write(request_str.encode())
        await self._process.stdin.drain()

        # Wait for response with timeout
        try:
            result = await asyncio.wait_for(future, timeout=self.timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise RuntimeError(f"MCP request {method} timed out after {self.timeout}s")

    async def _read_responses(self) -> None:
        """Background task to read responses from stdout."""
        try:
            while self._process and self._process.stdout:
                line = await self._process.stdout.readline()
                if not line:
                    break

                try:
                    response = json.loads(line.decode().strip())

                    # Handle response to a request
                    if "id" in response:
                        request_id = response["id"]
                        future = self._pending_requests.pop(request_id, None)
                        if future and not future.done():
                            if "error" in response:
                                future.set_exception(Exception(response["error"]))
                            else:
                                future.set_result(response.get("result"))

                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse MCP response: {e}")
                except Exception as e:
                    logger.error(f"Error handling MCP response: {e}")

        except asyncio.CancelledError:
            logger.debug("Response reader task cancelled")
        except Exception as e:
            logger.error(f"Response reader task error: {e}")

    async def list_tools(self) -> List[Dict]:
        """List available tools from MCP server."""
        if not self._process:
            raise RuntimeError("StdioMCPClient not connected")

        try:
            result = await self._send_request("tools/list", {})
            tools = result.get("tools", [])

            # Keep MCP format as-is (inputSchema)
            formatted_tools = []
            for tool in tools:
                formatted_tools.append({
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "inputSchema": tool.get("inputSchema", {})
                })

            logger.info(f"Discovered {len(formatted_tools)} tools from stdio MCP server")
            return formatted_tools

        except Exception as e:
            logger.error(f"Failed to list tools: {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call a tool on the MCP server."""
        if not self._process:
            raise RuntimeError("StdioMCPClient not connected")

        try:
            result = await self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments
            })

            # Extract content from MCP response
            content = result.get("content", [])
            if content and len(content) > 0:
                # Return first content item's text
                return content[0].get("text", result)

            return result

        except Exception as e:
            logger.error(f"Tool call failed: {e}")
            raise

    async def cleanup(self) -> None:
        """Clean up subprocess and resources."""
        # Cancel reader task
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        # Terminate process
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("MCP process didn't terminate gracefully, killing...")
                self._process.kill()
                await self._process.wait()
            except Exception as e:
                logger.error(f"Error terminating MCP process: {e}")

        self._process = None
        self._pending_requests.clear()
        logger.debug("StdioMCPClient cleaned up")


class MCPClientWrapper:
    """
    Factory wrapper that selects the right client based on config.
    
    Usage:
        config = MCPServerConfig(name="test", command="npx", args=[...])
        wrapper = MCPClientWrapper(config)
        await wrapper.connect()
        tools = await wrapper.list_tools()
        result = await wrapper.call_tool("tool_name", {"arg": "value"})
        await wrapper.cleanup()
    """
    
    def __init__(self, config):
        self.config = config
        self._client: Optional[BaseMCPClient] = None
        try:
            self._loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
    
    async def connect(self) -> None:
        """Create and connect to appropriate MCP client."""
        if hasattr(self.config, 'command') and self.config.command:
            logger.info(f"Using Stdio MCP client for server '{self.config.name}'")
            self._client = StdioMCPClient(self.config)
        elif hasattr(self.config, 'client_type') and self.config.client_type == "custom":
            logger.info(f"Using Custom MCP client for server '{self.config.name}'")
            self._client = CustomMCPClient(self.config)
        elif hasattr(self.config, 'endpoint') and self.config.endpoint:
            logger.info(f"Using Custom MCP client for server '{self.config.name}'")
            self._client = CustomMCPClient(self.config)
        else:
            raise ValueError(
                f"Cannot determine MCP client type for server '{self.config.name}'. "
                f"Provide either 'command' (for stdio) or 'endpoint' (for custom HTTP)."
            )

        await self._client.connect()
    
    async def list_tools(self) -> list[dict]:
        """List available tools from connected MCP server."""
        if not self._client:
            raise RuntimeError("MCP client not connected. Call connect() first.")
        return await self._client.list_tools()
    
    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call a remote tool via connected MCP server."""
        if not self._client:
            raise RuntimeError("MCP client not connected. Call connect() first.")
        return await self._client.call_tool(tool_name, arguments)
    
    async def cleanup(self) -> None:
        """Clean up MCP client resources."""
        if self._client:
            await self._client.cleanup()
            self._client = None
