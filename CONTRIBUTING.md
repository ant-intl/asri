# Contributing to ASRI

Thank you for your interest in contributing to ASRI! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please note that this project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

### 1. Fork and Clone

```bash
git clone https://github.com/YOUR_USERNAME/asri.git
cd asri
git remote add upstream https://github.com/ORIGINAL_OWNER/asri.git
```

### 2. Set Up Development Environment

Follow the [Installation Guide](docs/INSTALL.md) to set up your local development environment.

### 3. Run Tests

Ensure all tests pass before making changes:

```bash
cd backend
SERVER_ENV=test pytest apps/tests/ -v
```

## Development Workflow

### Branch Naming

Create branches from `main` using these conventions:

- `feature/description` - New features
- `fix/description` - Bug fixes
- `refactor/description` - Code refactoring
- `docs/description` - Documentation updates

Example: `feature/add-custom-llm-provider`

### Making Changes

1. Create your feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes following our coding standards (see below)

3. Test your changes thoroughly

4. Commit your changes using [Conventional Commits](#commit-message-format)

### Pull Request Process

1. Update your branch with latest main:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. Push your branch:
   ```bash
   git push origin feature/your-feature-name
   ```

3. Open a Pull Request on GitHub with:
   - Clear title and description
   - Reference related issues (if any)
   - List of changes made
   - Testing steps performed

4. Address any review feedback

## Commit Message Format

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

**Examples**:
```
feat(agent): add Pipeline Agent with function_calling support

- Implement native function calling using LLM tool_use
- Add Frame processor chain for streaming
- Include comprehensive tests

Closes #123
```

```
fix(websocket): resolve token leak in stream output

- Filter tool_result tags from final output
- Update StreamingTagFilter logic
```

## Coding Standards

### Python (Backend)

- Follow [PEP 8](https://peps.python.org/pep-0008/), max line length 120 characters
- Use type annotations (Python 3.10+ syntax)
- Write docstrings for all public classes and methods
- Use `async def` for async code, `sync_to_async` for ORM calls

```python
# Good: Async with sync_to_async for ORM
from asgiref.sync import sync_to_async

async def get_session(self, session_id: str):
    return await sync_to_async(ChatSession.objects.get)(session_id=session_id)

# Bad: Blocking ORM call in async function
async def get_session(self, session_id: str):
    return ChatSession.objects.get(session_id=session_id)  # Blocks!
```

### TypeScript/React (Frontend)

- Use functional components with Hooks
- Use CSS Modules for styling (`.module.css`)
- Never use `any` type - define proper interfaces
- Use `interface` for objects, `type` for unions/intersections
- Never use `index` as React key in loops

```typescript
// Good: Properly typed component
interface MessageProps {
  content: string;
  role: 'user' | 'assistant';
}

const Message: React.FC<MessageProps> = ({ content, role }) => {
  return <div className={styles.message}>{content}</div>;
};

// Bad: Using any
const Message: React.FC<any> = (props) => { ... }
```

### Architecture Rules

ASRI follows strict layered architecture:

```
API Layer → Service Layer → Core Layer → Integration Layer → Persistence Layer
```

**Rules**:
- Views/APIs only handle request/response formatting
- Business logic goes in `services/`, not `models/`
- No cross-layer calls (e.g., API calling models directly)
- Each layer only depends on the layer below it

## Testing Requirements

### Backend Tests

- Write tests for all new features and bug fixes
- Use `pytest` and `pytest-asyncio` for async tests
- Mock external API calls

```bash
# Run all tests
SERVER_ENV=test pytest apps/tests/ -v

# Run specific test file
SERVER_ENV=test pytest apps/tests/test_agent.py -v

# Run with coverage
SERVER_ENV=test pytest apps/tests/ --cov=apps --cov-report=html
```

### Frontend Tests

- E2E tests using Playwright
- Run tests before submitting PR

```bash
cd frontend
npm run test:e2e
```

## Adding New Providers

### LLM Provider

1. Create new file in `backend/apps/integrations/llm/`
2. Inherit from `BaseLLMProvider`
3. Implement `chat()` and `stream_chat()` methods
4. Register in the Registry
5. Write tests

### Tool/Skill

1. Create new file in `backend/apps/integrations/tool/` or `skill/`
2. Inherit from `BaseTool` or `BaseSkill`
3. Implement `execute()` method
4. Register in the Registry

See [Extension Guide](docs/extension-guide.md) for detailed examples.

## Documentation

- Update documentation for any API changes
- Add docstrings to new functions/classes
- Update README if user-facing behavior changes

## Questions?

- Open an [Issue](https://github.com/ORIGINAL_OWNER/asri/issues) for bugs or feature requests
- Start a [Discussion](https://github.com/ORIGINAL_OWNER/asri/discussions) for questions

Thank you for contributing!
