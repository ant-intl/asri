# Skill 系统

Skill（技能）是 ASRI 中复杂多步骤能力的抽象。每个 Skill 包含完整的决策树或流程文档，Agent 可在推理过程中加载技能内容作为参考依据。技能系统支持**租户隔离**，不同租户拥有独立的技能集合。

---

## BaseSkill 抽象基类

**文件**: `apps/integrations/skill/base.py`

```python
class BaseSkill(ABC):
    name: str = ''          # 技能名称
    description: str = ''   # 技能描述

    @abstractmethod
    async def execute(self, input_text: str, context: Any) -> str:
        """执行技能，返回结果字符串。"""
```

---

## SkillRegistry（租户隔离）

**文件**: `apps/integrations/skill/base.py`

SkillRegistry 使用两级字典实现租户隔离：

```
{
    None: {skill_name: BaseSkill},          # 全局默认
    'tenant_a': {skill_name: BaseSkill},    # 租户 A
    'tenant_b': {skill_name: BaseSkill},    # 租户 B
}
```

### 核心方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `register` | `register(skill, tenant_id=None)` | 注册技能到指定租户桶 |
| `get_skill` | `get_skill(name) → BaseSkill | None` | 获取当前租户的技能（自动从 contextvars 解析） |
| `list_skills` | `list_skills() → list[str]` | 列出当前租户的所有技能名称 |
| `clear` | `clear(tenant_id=_SENTINEL)` | 清除缓存。不传参清除全部，传参清除指定租户 |

### 租户解析机制

查询方法（`get_skill`, `list_skills`）自动通过 `get_current_tenant_id()` 获取当前请求的租户 ID，无需调用方显式传递。

**没有降级**：当租户无技能配置时返回空列表，不会回退到全局默认桶。

### 使用示例

```python
from apps.integrations.skill.base import SkillRegistry

# 注册（通常在启动时由 SkillLoader 完成）
SkillRegistry.register(my_skill, tenant_id='my_tenant')

# 查询（在请求上下文中，自动使用当前租户）
skill = SkillRegistry.get_skill('退款流程')
if skill:
    result = await skill.execute('用户想退款', context)

# 列出所有技能
names = SkillRegistry.list_skills()
```

---

## SkillRegistry 扩展方法

**文件**: `apps/integrations/skill/registry.py`

```python
SkillRegistry.list_skills_with_descriptions() → list[dict]
```

返回当前租户所有技能的名称和描述列表：

```python
[
    {'name': '退款流程', 'description': '处理退款相关问题'},
    {'name': '账户管理', 'description': '账户注册、认证、设置'},
]
```

此方法主要用于**系统提示注入**——在 SkillDecisionPrompt 和 InterleavedThinkingPrompt 中将技能列表写入 System Prompt。

---

## FilesystemSkill

**文件**: `apps/integrations/skill/filesystem_skill.py`

从文件系统加载的技能实现（当前主路径）。每个技能对应一个独立目录，包含 `SKILL.md` 文件，`execute()` 返回完整的 Markdown 内容供 Agent 参考。

### 目录结构

```
{SKILLS_ROOT}/{tenant_id}/skills/{skill_name}/
└── SKILL.md          # 技能文档（必须包含 name: 和 description: 元数据）
```

`SKILLS_ROOT` 由环境变量 `ASRI_SKILLS_DIR` 控制，默认为 `<project_root>/data/tenant/`。

### SKILL.md 格式

```markdown
name: 退款流程
description: 处理用户退款相关问题

## 退款步骤
1. 进入订单页面
2. 选择需要退款的订单
3. 点击"申请退款"
4. 填写退款原因
5. 等待审核（1-3个工作日）
```

- `name:` 和 `description:` 是必填的元数据字段（Markdown 首部）
- `name:` 缺失时，目录名作为回退值

---

## SkillLoader（启动扫描）

**文件**: `apps/services/skill_service.py`

Django 启动时自动扫描各租户目录，将所有 `SKILL.md` 注册到 `SkillRegistry`：

```python
class ChatbotConfig(AppConfig):
    def ready(self):
        # 遍历所有租户，按各自目录扫描技能
        for tenant_id in get_all_tenant_ids():
            base_dir = get_tenant_skills_dir(tenant_id)
            scan_skills(base_dir=base_dir, tenant_id=tenant_id)
```

路径工具函数（`apps/utils/skill_paths.py`）：

```python
from apps.utils.skill_paths import get_tenant_skills_dir

# 返回：{SKILLS_ROOT}/{tenant_id}/skills/
base_dir = get_tenant_skills_dir('my_tenant')
```

### 环境变量配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ASRI_SKILLS_DIR` | `<project_root>/data/tenant/` | 技能根目录，可设为 `~/.asri` 等外部路径 |

---

## Agent 中的 skill_load 工具

ChatAgent 提供 `skill_load` 工具函数，允许 LLM 按需加载技能详情：

```python
SKILL_LOAD_SCHEMA = FunctionSchema(
    name="skill_load",
    description="当你认为需要加载技能树的时候，调用此工具。",
    properties={
        "skill_name": {
            "type": "string",
            "description": "要加载的技能名称 (skill name)",
        },
    },
    required=["skill_name"],
)
```

此工具**始终注册**（不依赖 AgentContext 的能力标志），因为技能名称已在 System Prompt 中列出。

调用流程：
1. LLM 发出 `skill_load(skill_name="退款流程")` 工具调用
2. handler 通过 `SkillRegistry.get_skill()` 查找（自动使用当前租户）
3. 返回 `{name, description, content}` 供 LLM 继续推理
4. 找不到时返回 `{error, available_skills}` 列表

---

## 相关文档

- Tool 系统 → [tool-guide.md](tool-guide.md)
- 多租户系统 → 租户通过 `X-Tenant-Id` header 指定，实现配置、技能、数据隔离
- 扩展新 Skill → [extension-guide.md](extension-guide.md)
