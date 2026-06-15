"""
MCP Server configuration HTTP API.
"""
import asyncio
import logging
from typing import Optional
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ValidationError
import json

from ...entities import McpServerConfig, McpToolMockConfig
from ...tenant.context import get_current_tenant_id
from ...integrations.mcp import MCPClientWrapper, MCPServerConfig

logger = logging.getLogger(__name__)


def _build_mcp_integration_config(db_server):
    """Build MCPServerConfig (integration layer) from database McpServerConfig.

    Args:
        db_server: McpServerConfig model instance from database.

    Returns:
        MCPServerConfig dataclass instance for use with MCPClientWrapper.
    """
    cfg = db_server.config or {}
    return MCPServerConfig(
        name=db_server.name,
        client_type=db_server.client_type or 'stdio',
        # Stdio fields
        command=db_server.command or '',
        args=db_server.args or [],
        env=db_server.env or {},
        # HTTP / Custom fields (from config JSON)
        endpoint=cfg.get('endpoint', ''),
        # Custom client fields
        sse_endpoint=cfg.get('sseEndpoint', cfg.get('sse_endpoint', '')),
        mcp_name=cfg.get('mcpName', cfg.get('mcp_name', '')),
        list_tools_path=cfg.get('listToolsPath', cfg.get('list_tools_path', '/sample/mcp/listTools')),
        execute_path=cfg.get('executePath', cfg.get('execute_path', '/sample/mcp/execute')),
        # Common
        timeout=cfg.get('timeout', 30),
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def mcp_servers(request):
    """List all MCP servers or create a new one.

    GET: List all servers
    POST: Create a new server
    """
    tenant_id = get_current_tenant_id()

    if request.method == 'GET':
        try:
            servers = McpServerConfig.objects.filter(tenant_id=tenant_id)
            data = [server.to_dict() for server in servers]
            return JsonResponse({'providers': data})
        except Exception as e:
            logger.exception(f"Error listing MCP servers: {e}")
            return JsonResponse({'error': str(e)}, status=500)

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            server_id = data.get('id') or data.get('server_id')

            # Auto-generate server_id if not provided
            if not server_id:
                import uuid
                server_id = str(uuid.uuid4())

            # Check if server already exists
            if McpServerConfig.objects.filter(server_id=server_id, tenant_id=tenant_id).exists():
                return JsonResponse({'error': f'Server {server_id} already exists'}, status=400)

            # Collect client-specific fields into config JSON
            if 'config' in data:
                # Use config object directly from request
                config = data['config'] or {}
            else:
                # Backward compatibility: extract individual top-level fields
                config_keys = {
                    'endpoint', 'merchantId', 'userId', 'walletId',
                    'sseEndpoint', 'mcpName', 'listToolsPath', 'executePath',
                    'serviceCode', 'timeout'
                }
                config = {k: v for k, v in data.items() if k in config_keys}

            server = McpServerConfig(
                server_id=server_id,
                name=data.get('name', ''),
                description=data.get('description', ''),
                client_type=data.get('clientType', 'stdio'),
                # Stdio fields
                command=data.get('command', ''),
                args=data.get('args', []),
                env=data.get('env', {}),
                # Client-specific configuration
                config=config,
                is_active=data.get('isActive', True),
                tools_cache=data.get('tools', []),
                tenant_id=tenant_id,
            )
            server.full_clean()
            server.save()

            return JsonResponse(server.to_dict(), status=201)
        except ValidationError as e:
            logger.error(f"Validation error creating MCP server: {e}")
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception(f"Error creating MCP server: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def mcp_server_detail(request, server_id):
    """Get, update or delete a specific MCP server.

    GET: Get server details
    PUT: Update server
    DELETE: Delete server
    """
    tenant_id = get_current_tenant_id()

    try:
        server = McpServerConfig.objects.get(server_id=server_id, tenant_id=tenant_id)
    except McpServerConfig.DoesNotExist:
        return JsonResponse({'error': f'Server {server_id} not found'}, status=404)

    if request.method == 'GET':
        return JsonResponse(server.to_dict())

    elif request.method == 'PUT':
        try:
            data = json.loads(request.body)

            # Update basic fields
            server.name = data.get('name', server.name)
            server.description = data.get('description', server.description)
            server.client_type = data.get('clientType', server.client_type)
            # Stdio fields
            server.command = data.get('command', server.command)
            server.args = data.get('args', server.args)
            server.env = data.get('env', server.env)
            # Client-specific configuration
            if 'config' in data:
                # Use config object directly from request (merge with existing)
                new_config = data['config'] or {}
                existing_config = server.config or {}
                server.config = {**existing_config, **new_config}
            else:
                # Backward compatibility: extract individual top-level fields
                config_keys = {
                    'endpoint', 'merchantId', 'userId', 'walletId',
                    'sseEndpoint', 'mcpName', 'listToolsPath', 'executePath',
                    'serviceCode', 'timeout'
                }
                new_config = {k: v for k, v in data.items() if k in config_keys}
                if new_config:
                    existing_config = server.config or {}
                    server.config = {**existing_config, **new_config}
            # Common
            server.is_active = data.get('isActive', server.is_active)
            server.tools_cache = data.get('tools', server.tools_cache)

            server.full_clean()
            server.save()

            return JsonResponse(server.to_dict())
        except ValidationError as e:
            logger.error(f"Validation error updating MCP server: {e}")
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception(f"Error updating MCP server: {e}")
            return JsonResponse({'error': str(e)}, status=500)

    elif request.method == 'DELETE':
        try:
            # Sync in-memory registries before deleting from DB
            _remove_server_tools(server.name, tenant_id)
            # Delete associated mock configs
            McpToolMockConfig.objects.filter(server_id=server_id).delete()
            server.delete()
            return JsonResponse({'message': 'Server deleted successfully'})
        except Exception as e:
            logger.exception(f"Error deleting MCP server: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["PATCH"])
def mcp_server_toggle(request, server_id):
    """Toggle MCP server active status and sync in-memory registries."""
    tenant_id = get_current_tenant_id()

    try:
        server = McpServerConfig.objects.get(server_id=server_id, tenant_id=tenant_id)
        server.is_active = not server.is_active
        server.save()

        # Sync in-memory registries so the change takes effect immediately
        if server.is_active:
            _reload_server_tools(server, tenant_id)
        else:
            _remove_server_tools(server.name, tenant_id)

        return JsonResponse(server.to_dict())
    except McpServerConfig.DoesNotExist:
        return JsonResponse({'error': f'Server {server_id} not found'}, status=404)
    except Exception as e:
        logger.exception(f"Error toggling MCP server: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET", "PUT"])
def mcp_tool_mock(request, server_id, tool_name):
    """Get or update mock configuration for a tool.

    GET: Get mock config
    PUT: Update mock config
    """
    tenant_id = get_current_tenant_id()

    # Verify server exists
    if not McpServerConfig.objects.filter(server_id=server_id, tenant_id=tenant_id).exists():
        return JsonResponse({'error': f'Server {server_id} not found'}, status=404)

    if request.method == 'GET':
        try:
            mock_config = McpToolMockConfig.objects.filter(
                server_id=server_id,
                tool_name=tool_name,
                tenant_id=tenant_id,
            ).first()

            if mock_config:
                return JsonResponse(mock_config.to_dict())
            else:
                # Return default mock config
                return JsonResponse({
                    'toolName': tool_name,
                    'mock': {
                        'enabled': False,
                        'mode': 'manual',
                    }
                })
        except Exception as e:
            logger.exception(f"Error getting mock config: {e}")
            return JsonResponse({'error': str(e)}, status=500)

    elif request.method == 'PUT':
        try:
            data = json.loads(request.body)
            mock_data = data.get('mock', {})

            mock_config, created = McpToolMockConfig.objects.get_or_create(
                server_id=server_id,
                tool_name=tool_name,
                defaults={
                    'tenant_id': tenant_id,
                    'enabled': mock_data.get('enabled', False),
                    'mode': mock_data.get('mode', 'manual'),
                    'pairs': mock_data.get('pairs', []),
                    'random_outputs': mock_data.get('randomOutputs', []),
                    'manual_input': mock_data.get('manualInput', {}),
                    'manual_output': mock_data.get('manualOutput', {}),
                }
            )

            if not created:
                mock_config.enabled = mock_data.get('enabled', mock_config.enabled)
                mock_config.mode = mock_data.get('mode', mock_config.mode)

                if mock_config.mode == 'fixed':
                    mock_config.pairs = mock_data.get('pairs', [])
                elif mock_config.mode == 'random':
                    mock_config.random_outputs = mock_data.get('randomOutputs', [])
                elif mock_config.mode == 'manual':
                    mock_config.manual_input = mock_data.get('manualInput', {})
                    mock_config.manual_output = mock_data.get('manualOutput', {})

                mock_config.full_clean()
                mock_config.save()

            return JsonResponse(mock_config.to_dict())
        except ValidationError as e:
            logger.error(f"Validation error updating mock config: {e}")
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception(f"Error updating mock config: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["PATCH"])
def mcp_tool_mock_toggle(request, server_id, tool_name):
    """Toggle mock enabled status for a tool."""
    tenant_id = get_current_tenant_id()

    # Verify server exists
    if not McpServerConfig.objects.filter(server_id=server_id, tenant_id=tenant_id).exists():
        return JsonResponse({'error': f'Server {server_id} not found'}, status=404)

    try:
        mock_config, created = McpToolMockConfig.objects.get_or_create(
            server_id=server_id,
            tool_name=tool_name,
            defaults={'tenant_id': tenant_id, 'enabled': True}
        )

        if not created:
            mock_config.enabled = not mock_config.enabled
            mock_config.save()

        return JsonResponse(mock_config.to_dict())
    except Exception as e:
        logger.exception(f"Error toggling mock: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def mcp_server_refresh_tools(request, server_id):
    """Refresh tools list from MCP server by connecting to it."""
    tenant_id = get_current_tenant_id()

    try:
        # Get server config from database
        server = McpServerConfig.objects.get(server_id=server_id, tenant_id=tenant_id)

        # Build integration config from all fields
        config = _build_mcp_integration_config(server)

        # Connect to MCP server and get tools
        async def fetch_tools():
            client = MCPClientWrapper(config)
            try:
                await client.connect()
                tools = await client.list_tools()
                await client.cleanup()
                return tools
            except Exception as e:
                # Ensure cleanup on error
                try:
                    await client.cleanup()
                except:
                    pass
                raise e

        # Run async function
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # If loop is already running (e.g., in async context), create new loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, fetch_tools())
                tools = future.result(timeout=60)
        else:
            tools = loop.run_until_complete(fetch_tools())

        # Update tools_cache in database
        server.tools_cache = tools
        server.save()

        logger.info(f"Refreshed {len(tools)} tools for MCP server {server_id}")

        return JsonResponse(server.to_dict())

    except McpServerConfig.DoesNotExist:
        return JsonResponse({'error': f'Server {server_id} not found'}, status=404)
    except Exception as e:
        logger.exception(f"Error refreshing tools: {e}")
        return JsonResponse({'error': f'Failed to refresh tools: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def mcp_tool_execute(request, server_id, tool_name):
    """Execute a tool on the MCP server."""
    tenant_id = get_current_tenant_id()

    try:
        # Get server config from database
        server = McpServerConfig.objects.get(server_id=server_id, tenant_id=tenant_id)

        # Parse request body
        data = json.loads(request.body)
        arguments = data.get('arguments', {})

        # Build integration config from all fields
        config = _build_mcp_integration_config(server)

        # Connect to MCP server and execute tool
        async def execute_tool():
            client = MCPClientWrapper(config)
            try:
                await client.connect()
                result = await client.call_tool(tool_name, arguments)
                await client.cleanup()
                return result
            except Exception as e:
                # Ensure cleanup on error
                try:
                    await client.cleanup()
                except:
                    pass
                raise e

        # Run async function
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # If loop is already running, create new loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, execute_tool())
                result = future.result(timeout=90)
        else:
            result = loop.run_until_complete(execute_tool())

        logger.info(f"Executed tool {tool_name} on MCP server {server_id}")

        return JsonResponse({
            'success': True,
            'result': result
        })

    except McpServerConfig.DoesNotExist:
        return JsonResponse({'error': f'Server {server_id} not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
    except Exception as e:
        logger.exception(f"Error executing tool {tool_name}: {e}")
        return JsonResponse({'error': f'Failed to execute tool: {str(e)}'}, status=500)


# ---------------------------------------------------------------------------
# Internal helpers for syncing in-memory registries after toggle / delete
# ---------------------------------------------------------------------------

def _remove_server_tools(server_name: str, tenant_id: Optional[str]) -> None:
    """Remove tools from ToolRegistry and server from MCPServerRegistry."""
    from ...integrations.tool.base import ToolRegistry
    from ...integrations.mcp.mcp_server_registry import MCPServerRegistry

    removed = ToolRegistry.unregister_by_server(server_name, tenant_id)
    MCPServerRegistry.unregister_server(server_name, tenant_id)
    logger.info(
        f"Removed {removed} tools and unregistered MCP server "
        f"'{server_name}' (tenant={tenant_id})"
    )


def _reload_server_tools(db_server, tenant_id: Optional[str]) -> None:
    """Re-register a server in MCPServerRegistry and discover its tools.

    Args:
        db_server: McpServerConfig database model instance.
        tenant_id: Tenant ID for isolation.
    """
    from ...integrations.tool.base import ToolRegistry
    from ...integrations.mcp.mcp_server_registry import MCPServerRegistry

    # Build integration config from database model
    mcp_config = _build_mcp_integration_config(db_server)

    # Register server
    MCPServerRegistry.register_server(mcp_config, tenant_id=tenant_id)

    # Discover and register tools (async operation)
    async def _discover_and_register():
        discovered = await MCPServerRegistry.discover_tools(tenant_id)
        count = 0
        for tool in discovered:
            # Only register tools from this specific server
            if getattr(tool, '_server_name', None) == db_server.name:
                ToolRegistry.register(tool, tenant_id=tenant_id)
                count += 1
        return count

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(asyncio.run, _discover_and_register())
        try:
            count = future.result(timeout=60)
            logger.info(
                f"Reloaded {count} tools for MCP server "
                f"'{db_server.name}' (tenant={tenant_id})"
            )
        except Exception as e:
            logger.error(
                f"Failed to reload tools for MCP server "
                f"'{db_server.name}': {e}",
                exc_info=True,
            )
