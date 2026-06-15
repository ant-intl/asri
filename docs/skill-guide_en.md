# Skill System

Skill is the abstraction of complex multi-step capabilities in ASRI. Each Skill contains a complete decision tree or process document. The Agent can load skill content as reference during reasoning. The skill system supports **tenant isolation**, with different tenants having independent skill sets.

---

## BaseSkill Abstract Base Class

**File**: `apps/integrations/skill/base.py`

```python
class BaseSkill(ABC):
    name: str = ''          # Skill name
    description: str = ''   # Skill description

    @abstractmethod
    async def execute(self, input_text: str, context: Any) -> str:
        """Execute the skill and return a result string."""
```

---

## SkillRegistry (Tenant-Isolated)

**File**: `apps/integrations/skill/base.py`

SkillRegistry uses a two-level dictionary to implement tenant isolation:

```
{
    None: {skill_name: BaseSkill},          # Global default
    'tenant_a': {skill_name: BaseSkill},    # Tenant A
    'tenant_b': {skill_name: BaseSkill},    # Tenant B
}
```

### Core Methods

| Method | Signature | Description |
|------|------|------|
| `register` | `register(skill, tenant_id=None)` | Register a skill to the specified tenant bucket |
| `get_skill` | `get_skill(name) → BaseSkill \| None` | Get the current tenant's skill (auto-resolved from contextvars) |
| `list_skills` | `list_skills() → list[str]` | List all skill names for the current tenant |
| `clear` | `clear(tenant_id=_SENTINEL)` | Clear cache. No argument clears all; passing a tenant clears that tenant only |

### Tenant Resolution Mechanism

Query methods (`get_skill`, `list_skills`) automatically obtain the current request's tenant ID via `get_current_tenant_id()`, without requiring explicit passing by the caller.

**No fallback**: Returns an empty list when a tenant has no skill configuration, without falling back to the global default bucket.

### Usage Example

```python
from apps.integrations.skill.base import SkillRegistry

# Register (usually done by SkillLoader at startup)
SkillRegistry.register(my_skill, tenant_id='my_tenant')

# Query (in request context, automatically uses current tenant)
skill = SkillRegistry.get_skill('refund_process')
if skill:
    result = await skill.execute('User wants a refund', context)

# List all skills
names = SkillRegistry.list_skills()
```

---

## SkillRegistry Extension Method

**File**: `apps/integrations/skill/registry.py`

```python
SkillRegistry.list_skills_with_descriptions() → list[dict]
```

Returns a list of names and descriptions for all skills of the current tenant:

```python
[
    {'name': 'refund_process', 'description': 'Handle refund-related issues'},
    {'name': 'account_management', 'description': 'Account registration, verification, settings'},
]
```

This method is mainly used for **system prompt injection** — writing the skill list into the System Prompt in SkillDecisionPrompt and InterleavedThinkingPrompt.

---

## FilesystemSkill

**File**: `apps/integrations/skill/filesystem_skill.py`

The primary skill implementation loaded from the file system. Each skill corresponds to an independent directory containing a `SKILL.md` file. `execute()` returns the complete Markdown content for the Agent's reference.

### Directory Structure

```
{SKILLS_ROOT}/{tenant_id}/skills/{skill_name}/
└── SKILL.md          # Skill document (must contain name: and description: metadata)
```

`SKILLS_ROOT` is controlled by the `ASRI_SKILLS_DIR` environment variable, defaulting to `<project_root>/data/tenant/`.

### SKILL.md Format

```markdown
name: refund_process
description: Handle user refund-related issues

## Refund Steps
1. Go to the order page
2. Select the order to refund
3. Click "Apply for Refund"
4. Fill in the refund reason
5. Wait for review (1-3 business days)
```

- `name:` and `description:` are required metadata fields (at the top of the Markdown)
- If `name:` is missing, the directory name is used as a fallback

---

## SkillLoader (Startup Scanner)

**File**: `apps/services/skill_service.py`

At Django startup, automatically scans each tenant's directory and registers all `SKILL.md` files into `SkillRegistry`:

```python
class ChatbotConfig(AppConfig):
    def ready(self):
        # Iterate through all tenants, scan skills by their respective directories
        for tenant_id in get_all_tenant_ids():
            base_dir = get_tenant_skills_dir(tenant_id)
            scan_skills(base_dir=base_dir, tenant_id=tenant_id)
```

Path utility function (`apps/utils/skill_paths.py`):

```python
from apps.utils.skill_paths import get_tenant_skills_dir

# Returns: {SKILLS_ROOT}/{tenant_id}/skills/
base_dir = get_tenant_skills_dir('my_tenant')
```

### Environment Variable Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ASRI_SKILLS_DIR` | `<project_root>/data/tenant/` | Skills root directory; can be set to an external path like `~/.asri` |

---

## skill_load Tool in the Agent

ChatAgent provides the `skill_load` tool function, allowing the LLM to load skill details on demand:

```python
SKILL_LOAD_SCHEMA = FunctionSchema(
    name="skill_load",
    description="Call this tool when you need to load a skill tree.",
    properties={
        "skill_name": {
            "type": "string",
            "description": "The skill name to load",
        },
    },
    required=["skill_name"],
)
```

This tool is **always registered** (independent of AgentContext capability flags) because skill names are already listed in the System Prompt.

Call flow:
1. The LLM issues a `skill_load(skill_name="refund_process")` tool call
2. The handler looks up via `SkillRegistry.get_skill()` (automatically uses current tenant)
3. Returns `{name, description, content}` for the LLM to continue reasoning
4. If not found, returns `{error, available_skills}` list

---

## Related Documentation

- Tool System → [tool-guide.md](tool-guide.md)
- Multi-tenant System → Tenants are identified via the `X-Tenant-Id` header, enabling isolated configuration, skills, and data
- Extending New Skills → [extension-guide.md](extension-guide.md)
