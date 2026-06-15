# 安全政策

## 支持的版本

以下 ASRI 版本目前支持安全更新：

| 版本 | 是否支持          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## 报告漏洞

我们重视 ASRI 的安全性。如果您认为发现了安全漏洞，请按照以下说明报告。

**请不要通过公开的 GitHub issue 报告安全漏洞。**

请通过 GitHub Security Advisory 报告至 https://github.com/your-org/asri/security/advisories/new。您应该在 48 小时内收到回复。如果因某种原因没有收到，请通过同一渠道跟进以确保我们收到了您的原始消息。

**请包含以下信息：**

- 问题类型（例如：缓冲区溢出、SQL 注入、跨站脚本等）
- 与问题表现相关的源文件完整路径
- 受影响源代码的位置（标签/分支/提交或直接 URL）
- 复现问题所需的任何特殊配置
- 复现问题的逐步说明
- 概念验证或利用代码（如有）
- 问题的影响，包括攻击者可能如何利用它

## 安全最佳实践

### API Key 管理

- API key 使用 `cryptography` 库加密存储
- 永远不要在日志中记录 API key 或敏感凭证
- 使用环境变量进行配置
- 定期轮换密钥

### 输入验证

- 所有用户输入都经过验证和清洗
- 使用 Django 内置的表单验证
- 实现适当的内容类型检查
- 通过转义输出防止 XSS

### 认证

- WebSocket 端点需要 Bearer Token 认证
- Token 存储前使用 SHA256 哈希
- 多租户隔离确保数据分离
- 使用强大的随机生成密钥

### 数据库安全

-  exclusively 使用 Django ORM（禁止原始 SQL）
- 这可以防止 SQL 注入攻击
- 数据库凭证永远不要提交
- 使用具有最小权限的独立数据库用户

### 外部 API 调用

- 所有外部 API 调用都有超时限制（≤30 秒）
- 实现速率限制以防止滥用
- 使用连接池提高效率
- 优雅地处理错误而不暴露内部信息

### 日志

- 使用 `logging.getLogger(__name__)` 进行所有日志记录
- 永远不要记录敏感信息（API key、密码、token）
- 记录安全事件（失败的认证尝试、验证错误）
- 实现适当的日志轮换

## 安全架构

### 多租户隔离

ASRI 实现了完整的租户级隔离：

- 每个租户拥有独立的配置
- Skill 和 Tool 是租户范围的
- Session 和 Message 数据隔离
- Bearer Token 认证识别租户上下文

### 基于 Token 的认证

- 所有 API 端点都需要 Bearer Token（本地开发模式除外）
- 每次请求都通过中间件验证 Token
- 租户上下文通过 `contextvars` 传播
- 不可能跨租户访问数据

### WebSocket 安全

- WebSocket 连接需要认证
- 连接时验证 Session 所有权
- 消息限定于认证租户范围
- 应用速率限制防止滥用

## 部署安全检查清单

- [ ] 生产环境设置 `DEBUG = False`
- [ ] 使用强 `DJANGO_SECRET_KEY`（至少 50 字符）
- [ ] 正确配置 `ALLOWED_HOSTS`
- [ ] 为所有端点启用 HTTPS
- [ ] 设置适当的 CORS 头
- [ ] 为 channel layers 使用带认证的 Redis
- [ ] 配置数据库使用 SSL/TLS
- [ ] 实现适当的防火墙规则
- [ ] 设置监控和告警

## 致谢

我们感谢负责任的披露。帮助提高我们安全性的安全研究人员将在此被致谢（经允许）。

## 联系方式

有关安全相关的问题，请通过 GitHub Security Advisory 提交：https://github.com/your-org/asri/security/advisories/new
