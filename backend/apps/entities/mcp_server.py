"""
MCP Server configuration model.
"""
from django.db import models
from django.core.exceptions import ValidationError

from .fields import JsonTextField


class McpServerConfig(models.Model):
    """MCP Server configuration.

    Stores MCP server connection details and metadata.
    Supports multiple client types: stdio, http, custom.
    """
    CLIENT_TYPE_CHOICES = [
        ('stdio', 'Stdio (npx/command)'),
        ('http', 'HTTP'),
        ('custom', 'Custom HTTP'),
    ]

    server_id = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')

    # Client type selector
    client_type = models.CharField(
        max_length=20,
        choices=CLIENT_TYPE_CHOICES,
        default='stdio',
        db_index=True,
        help_text='MCP client type: stdio, http, or custom',
    )

    # Stdio client fields (required when client_type='stdio')
    command = models.CharField(max_length=500, blank=True, default='')
    args = JsonTextField(default=list, help_text='Command arguments as JSON array')
    env = JsonTextField(default=dict, help_text='Environment variables as JSON object')

    # Client-specific configuration (HTTP/Custom/SofaPy fields stored as JSON)
    config = JsonTextField(default=dict, help_text='Client-specific configuration')

    is_active = models.BooleanField(default=True, db_index=True)
    tools_cache = JsonTextField(default=list, help_text='Cached list of tools from server')

    tenant_id = models.CharField(max_length=100, db_index=True, blank=True, default='')
    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'mcp_server_config'
        ordering = ['-gmt_create']

    def __str__(self):
        return f'{self.name} ({self.server_id})'

    def clean(self):
        """Validate the model data."""
        if not isinstance(self.args, list):
            raise ValidationError({'args': 'args must be a list'})

        if not isinstance(self.env, dict):
            raise ValidationError({'env': 'env must be a dictionary'})

    def to_dict(self):
        """Convert to dictionary representation."""
        return {
            'id': self.server_id,
            'name': self.name,
            'description': self.description,
            'clientType': self.client_type,
            # Stdio fields
            'command': self.command,
            'args': self.args,
            'env': self.env if self.env else None,
            # Client-specific configuration
            'config': self.config or {},
            # Common
            'isActive': self.is_active,
            'tools': self.tools_cache if self.tools_cache else [],
            'createdAt': self.gmt_create.isoformat(),
            'updatedAt': self.gmt_modified.isoformat(),
        }


class McpToolMockConfig(models.Model):
    """MCP Tool Mock configuration.

    Stores mock settings for individual tools.
    """
    MOCK_MODE_CHOICES = [
        ('fixed', 'Fixed Input-Output Pairs'),
        ('random', 'Random Outputs'),
        ('manual', 'Manual Input-Output'),
    ]

    server_id = models.CharField(max_length=100, db_index=True)
    tool_name = models.CharField(max_length=200, db_index=True)
    enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=20, choices=MOCK_MODE_CHOICES, default='manual')

    tenant_id = models.CharField(
        max_length=100,
        db_index=True,
        default='example',
        help_text='Tenant identifier',
    )

    # For fixed mode: list of {input: {...}, output: {...}} pairs
    pairs = JsonTextField(default=list)

    # For random mode: list of random outputs
    random_outputs = JsonTextField(default=list)

    # For manual mode: single input-output pair
    manual_input = JsonTextField(default=dict)
    manual_output = JsonTextField(default=dict)

    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'mcp_tool_mock_config'
        unique_together = ['tenant_id', 'server_id', 'tool_name']
        ordering = ['-gmt_create']

    def __str__(self):
        return f'{self.server_id}.{self.tool_name} (Mock: {self.enabled})'

    def clean(self):
        """Validate the model data."""
        if self.mode == 'fixed':
            if not isinstance(self.pairs, list):
                raise ValidationError({'pairs': 'pairs must be a list'})
            for pair in self.pairs:
                if not isinstance(pair, dict) or 'input' not in pair or 'output' not in pair:
                    raise ValidationError({'pairs': 'Each pair must have input and output keys'})

        elif self.mode == 'random':
            if not isinstance(self.random_outputs, list):
                raise ValidationError({'random_outputs': 'random_outputs must be a list'})

        elif self.mode == 'manual':
            if not isinstance(self.manual_input, dict):
                raise ValidationError({'manual_input': 'manual_input must be a dictionary'})
            if not isinstance(self.manual_output, dict):
                raise ValidationError({'manual_output': 'manual_output must be a dictionary'})

    def to_dict(self):
        """Convert to dictionary representation."""
        result = {
            'toolName': self.tool_name,
            'mock': {
                'enabled': self.enabled,
                'mode': self.mode,
            }
        }

        if self.mode == 'fixed':
            result['mock']['pairs'] = self.pairs
        elif self.mode == 'random':
            result['mock']['randomOutputs'] = self.random_outputs
        elif self.mode == 'manual':
            result['mock']['manualInput'] = self.manual_input
            result['mock']['manualOutput'] = self.manual_output

        return result