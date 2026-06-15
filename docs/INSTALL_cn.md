# 安装指南

本指南提供了在不同环境下安装 ASRI 的详细说明。

## 系统要求

### 最低要求

- **Python**: 3.10 或更高版本
- **Node.js**: 18 或更高版本
- **npm**: 9 或更高版本
- **Git**: 2.0 或更高版本

### 数据库（选择其一）

- **MySQL**: 8.0+（生产环境）
- **SQLite**: 3.35+（仅开发环境）

### 可选

- **Redis**: 6.0+（生产环境 WebSocket 支持）
- **Docker**: 20.10+（容器化部署）

---

## 方法 1: 快速开始（推荐）

```bash
# 克隆仓库
git clone https://github.com/your-org/asri.git
cd asri

# 一键安装（venv + pip + npm + build + migrate + seed）
./setup.sh

# 启动服务
./start.sh
```

`setup.sh` 脚本会自动完成所有安装步骤。

## 方法 2: 分步安装（本地开发）

### 步骤 1: 克隆仓库

```bash
git clone https://github.com/your-org/asri.git
cd asri
```

### 步骤 2: 设置 Python 环境

```bash
# 创建虚拟环境
python -m venv .venv

# 激活 (Linux/Mac)
source .venv/bin/activate

# 激活 (Windows)
.venv\Scripts\activate

# 验证 Python 版本
python --version  # 应该是 3.10+
```

### 步骤 3: 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

### 步骤 4: 安装前端依赖

```bash
cd ../frontend
npm install
```

### 步骤 5: 配置环境变量（可选）

```bash
# 复制环境配置模板（可选，默认配置开箱即用）
cp .env.example .env
```

**主要环境变量**:

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DB_HOST` | 数据库主机（MySQL） | `127.0.0.1` |
| `DB_NAME` | 数据库名称（MySQL） | `asri` |
| `DB_USER` | 数据库用户（MySQL） | `root` |
| `DB_PASSWORD` | 数据库密码（MySQL） | - |

> **注意**: 默认使用 SQLite（零配置）。仅在使用 MySQL 时需设置上述数据库变量。
> **注意**: LLM Provider 配置通过 Admin 页面（http://127.0.0.1:8000/admin/）完成，不需要通过环境变量设置。

### 步骤 6: 数据库设置

```bash
cd backend

# 运行数据库迁移
python manage.py migrate

# 创建默认租户和初始数据
python manage.py seed_data
```

### 步骤 7: 启动服务

```bash
# 在项目根目录执行

# 生产模式（构建前端，启动 Daphne）
./start.sh

# 开发模式（前端热更新）
./start.sh dev

# 仅后端
./start.sh backend
```

### 步骤 8: 验证安装

1. **健康检查**: 访问 http://127.0.0.1:8000/health_check/
   - 应返回: `{"status": "ok"}`

2. **管理后台**: 访问 http://127.0.0.1:8000/admin/
   - 使用超级用户凭证登录

3. **聊天界面**: 访问 http://127.0.0.1:8000/
   - 应显示聊天 UI

---

## 方法 3: Docker Compose（推荐用于测试）

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+

### 设置

```bash
# 复制环境配置模板
cp .env.example .env
# 编辑 .env 配置
```

### 构建和启动

```bash
# 构建并启动所有服务
docker-compose up --build -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 配置

在 `docker-compose.yml` 中设置环境变量，或创建 `.env` 文件：

```bash
# LLM Provider 通过 Admin 页面配置，不需要环境变量
# 配置页面: http://127.0.0.1:8000/admin/

# 可选：使用 MySQL 替代 SQLite
DB_HOST=mysql
DB_NAME=asri
DB_USER=root
DB_PASSWORD=your-password
```

---

## 方法 4: 生产环境部署

### 服务器要求

- **CPU**: 2+ 核心
- **内存**: 4GB+
- **磁盘**: 20GB+
- **操作系统**: Ubuntu 20.04+ / CentOS 8+

### 步骤 1: 安装系统依赖

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3-pip nodejs npm mysql-client redis-server nginx

# CentOS/RHEL
sudo yum install -y python3.10 nodejs npm mysql redis nginx
```

### 步骤 2: 设置应用

```bash
# 克隆仓库
git clone https://github.com/your-org/asri.git /opt/asri
cd /opt/asri

# 创建虚拟环境
python3.10 -m venv .venv
source .venv/bin/activate

# 安装依赖
cd backend
pip install -r requirements.txt
# 注意：ASRI 使用 Daphne (ASGI) 作为生产服务器，而非 Gunicorn (WSGI)
```

### 步骤 3: 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 使用生产配置
```

**生产环境检查清单**:
- [ ] 使用强 `DJANGO_SECRET_KEY`（50+ 字符）
- [ ] 设置 `DJANGO_DEBUG=false` 关闭调试模式
- [ ] 设置生产数据库凭证
- [ ] 配置 Redis 主机和端口

### 步骤 4: 数据库设置

```bash
# 创建生产数据库
mysql -u root -p -e "CREATE DATABASE asri CHARACTER SET utf8mb4;"

# 运行迁移
cd /opt/asri/backend
python manage.py migrate
python manage.py createsuperuser
```

### 步骤 5: 配置 Daphne (ASGI 服务器)

创建 `/etc/systemd/system/asri.service`:

```ini
[Unit]
Description=ASRI Django ASGI Service
After=network.target mysql.service redis.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/asri
Environment="PATH=/opt/asri/.venv/bin"
ExecStart=/opt/asri/.venv/bin/daphne -b 127.0.0.1 -p 8000 config.asgi:application
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# 启用并启动服务
sudo systemctl daemon-reload
sudo systemctl enable asri
sudo systemctl start asri

# 检查状态
sudo systemctl status asri
```

### 步骤 6: 配置 Nginx

创建 `/etc/nginx/sites-available/asri`:

```nginx
upstream asri_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    # 重定向 HTTP 到 HTTPS（推荐）
    # return 301 https://$server_name$request_uri;

    location / {
        proxy_pass http://asri_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # 超时设置
        proxy_connect_timeout 60s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # 静态文件
    location /static/ {
        alias /opt/asri/backend/static/;
        expires 30d;
    }

    # 媒体文件
    location /media/ {
        alias /opt/asri/backend/media/;
        expires 30d;
    }
}
```

```bash
# 启用站点
sudo ln -s /etc/nginx/sites-available/asri /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 步骤 7: SSL/TLS（推荐）

```bash
# 安装 Certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# 自动续期已默认配置
```

---

## 前端开发

### 开发模式（热更新）

```bash
cd frontend
npm run dev
# 前端运行在 http://localhost:5173
# 后端 API 在 http://localhost:8000
```

### 生产构建

```bash
cd frontend
npm run build
# 输出: frontend/dist/
```

`start.sh` 脚本自动处理前端构建并更新 Django 模板。

---

## 故障排查

### 端口 8000 已被占用

```bash
# 查找使用端口 8000 的进程
lsof -i :8000

# 杀死进程
kill -9 <PID>
```

### 数据库连接错误

- 验证 MySQL 是否运行：`sudo systemctl status mysql`
- 检查 `.env` 中的凭证
- 确保数据库已创建：`mysql -u root -p -e "SHOW DATABASES;"`
- 测试连接：`mysql -h 127.0.0.1 -u root -p asri`

### WebSocket 连接失败

- 确保使用 Daphne，而非 `runserver`
- 检查 Redis 是否运行（如已配置）
- 验证 `config/asgi.py` 中的 ASGI 路由
- 检查 Nginx WebSocket 代理头（见步骤 6）

### 前端构建错误

```bash
# 清除 npm 缓存
npm cache clean --force

# 重新安装依赖
rm -rf node_modules package-lock.json
npm install

# 再次构建
npm run build
```

### 访问白屏

- 检查浏览器控制台的 JavaScript 错误
- 验证静态文件已收集：`python manage.py collectstatic`
- 确保使用 `start.sh`（更新模板引用）
- 检查 `templates/frontend/index.html` 中的 JS/CSS 路径

### 迁移错误

```bash
# 显示待处理的迁移
python manage.py showmigrations

# 如需要伪造迁移
python manage.py migrate --fake

# 重置迁移（危险！）
python manage.py migrate chatbot zero
python manage.py migrate
```

---

## 后续步骤

安装成功后：

1. 阅读 [架构文档](docs/ARCHITECTURE_cn.md) 了解系统
2. 阅读 [聊天 API](docs/chat-api.md) 了解 API 用法
3. 在管理面板中配置第一个 LLM Provider
4. 创建测试会话并开始聊天！

如有问题或遇到 issue，请参阅 [贡献指南](CONTRIBUTING_cn.md)。
