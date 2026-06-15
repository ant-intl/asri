# 参与贡献 ASRI

感谢您对 ASRI 项目的贡献兴趣！本文档提供了贡献的指南和规范。

## 行为准则

请注意，本项目遵循 [贡献者公约行为准则](CODE_OF_CONDUCT_cn.md)。参与即表示您期望遵守此准则。

## 快速开始

### 1. Fork 和克隆

```bash
git clone https://github.com/YOUR_USERNAME/asri.git
cd asri
git remote add upstream https://github.com/ORIGINAL_OWNER/asri.git
```

### 2. 设置开发环境

按照 [安装指南](docs/INSTALL_cn.md) 设置本地开发环境。

### 3. 运行测试

在修改之前确保所有测试通过：

```bash
cd backend
SERVER_ENV=test pytest apps/tests/ -v
```

## 开发工作流

### 分支命名

从 `main` 创建分支，使用以下规范：

- `feature/描述` - 新功能
- `fix/描述` - Bug 修复
- `refactor/描述` - 代码重构
- `docs/描述` - 文档更新

示例：`feature/add-custom-llm-provider`

### 进行修改

1. 创建功能分支：
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. 按照编码规范进行修改（见下文）

3. 充分测试修改

4. 使用 [约定式提交](#提交信息格式) 提交更改

### Pull Request 流程

1. 使用最新的 main 更新您的分支：
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. 推送您的分支：
   ```bash
   git push origin feature/your-feature-name
   ```

3. 在 GitHub 上创建 Pull Request，包含：
   - 清晰的标题和描述
   - 关联相关 issue（如有）
   - 更改列表
   - 测试步骤

4. 处理审查反馈

## 提交信息格式

我们遵循 [约定式提交](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**类型**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

**示例**:
```
feat(agent): 添加 Pipeline Agent 支持原生 function_calling

- 使用 LLM tool_use 实现原生工具调用
- 添加 Frame 处理器链用于流式输出
- 包含完整的测试

Closes #123
```

```
fix(websocket): 修复流式输出中的 token 泄漏

- 从最终输出中过滤 tool_result 标签
- 更新 StreamingTagFilter 逻辑
```

## 编码规范

### Python（后端）

- 遵循 [PEP 8](https://peps.python.org/pep-0008/)，最大行长 120 字符
- 使用类型注解（Python 3.10+ 语法）
- 为所有公开类和方法编写 docstring
- 异步代码使用 `async def`，ORM 调用使用 `sync_to_async`

```python
# 正确: 使用 sync_to_async 调用 ORM
from asgiref.sync import sync_to_async

async def get_session(self, session_id: str):
    return await sync_to_async(ChatSession.objects.get)(session_id=session_id)

# 错误: 在异步函数中阻塞式调用 ORM
async def get_session(self, session_id: str):
    return ChatSession.objects.get(session_id=session_id)  # 会阻塞！
```

### TypeScript/React（前端）

- 使用函数组件和 Hooks
- 使用 CSS Modules 进行样式管理（`.module.css`）
- 永远不要使用 `any` 类型 - 定义明确的接口
- 对象使用 `interface`，联合/交叉类型使用 `type`
- 循环中永远不要使用 `index` 作为 React key

```typescript
// 正确: 正确类型的组件
interface MessageProps {
  content: string;
  role: 'user' | 'assistant';
}

const Message: React.FC<MessageProps> = ({ content, role }) => {
  return <div className={styles.message}>{content}</div>;
};

// 错误: 使用 any
const Message: React.FC<any> = (props) => { ... }
```

### 架构规则

ASRI 遵循严格的分层架构：

```
API 层 → Service 层 → Core 层 → Integration 层 → Persistence 层
```

**规则**:
- Views/API 只处理请求/响应格式转换
- 业务逻辑放在 `services/`，不放在 `models/`
- 禁止跨层调用（例如 API 直接调用 models）
- 每层只能依赖下一层

## 测试要求

### 后端测试

- 为新功能和 Bug 修复编写测试
- 使用 `pytest` 和 `pytest-asyncio` 进行异步测试
- Mock 外部 API 调用

```bash
# 运行所有测试
SERVER_ENV=test pytest apps/tests/ -v

# 运行特定测试文件
SERVER_ENV=test pytest apps/tests/test_agent.py -v

# 运行覆盖率测试
SERVER_ENV=test pytest apps/tests/ --cov=apps --cov-report=html
```

### 前端测试

- 使用 Playwright 进行 E2E 测试
- 提交 PR 前运行测试

```bash
cd frontend
npm run test:e2e
```

## 添加新的 Provider

### LLM Provider

1. 在 `backend/apps/integrations/llm/` 创建新文件
2. 继承 `BaseLLMProvider`
3. 实现 `chat()` 和 `stream_chat()` 方法
4. 在 Registry 中注册
5. 编写测试

### Tool/Skill

1. 在 `backend/apps/integrations/tool/` 或 `skill/` 创建新文件
2. 继承 `BaseTool` 或 `BaseSkill`
3. 实现 `execute()` 方法
4. 在 Registry 中注册

详见 [扩展指南](docs/extension-guide.md)。

## 文档

- 更新任何 API 更改的相关文档
- 为新函数/类添加 docstring
- 如果用户可见行为发生变化，更新 README

## 有问题？

- 提交 [Issue](https://github.com/ORIGINAL_OWNER/asri/issues) 报告 Bug 或提出功能请求
- 发起 [Discussion](https://github.com/ORIGINAL_OWNER/asri/discussions) 提出问题

感谢您的贡献！
