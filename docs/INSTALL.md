# Installation Guide

This guide provides detailed instructions for installing ASRI in various environments.

## System Requirements

### Minimum Requirements

- **Python**: 3.10 or higher
- **Node.js**: 18 or higher
- **npm**: 9 or higher
- **Git**: 2.0 or higher

### Database (Choose One)

- **MySQL**: 8.0+ (production)
- **SQLite**: 3.35+ (development only)

### Optional

- **Redis**: 6.0+ (production WebSocket support)
- **Docker**: 20.10+ (containerized deployment)

---

## Method 1: Quick Start (Recommended)

```bash
# Clone repository
git clone https://github.com/your-org/asri.git
cd asri

# One-command setup (venv + pip + npm + build + migrate + seed)
./setup.sh

# Start the server
./start.sh
```

That's it! The `setup.sh` script automates all steps below.

## Method 2: Step-by-Step Local Development

### Prerequisites

- **Python**: 3.10 or higher
- **Node.js**: 18 or higher
- **npm**: 9 or higher

### Step 1: Clone Repository

```bash
git clone https://github.com/your-org/asri.git
cd asri
```

### Step 2: Set Up Python Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate (Linux/Mac)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate
```

### Step 3: Install Backend Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### Step 4: Install Frontend Dependencies

```bash
cd ../frontend
npm install
```

### Step 5: Configure Environment (Optional)

```bash
# Copy environment template (optional, defaults work out-of-the-box)
cp .env.example .env
```

**Key Environment Variables**:

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_HOST` | Database host (MySQL) | `127.0.0.1` |
| `DB_NAME` | Database name (MySQL) | `asri` |
| `DB_USER` | Database user (MySQL) | `root` |
| `DB_PASSWORD` | Database password (MySQL) | - |

> **Note**: SQLite is used by default (zero configuration). Set the above DB variables only when using MySQL.
> **Note**: LLM Provider configuration is done through the Admin page (http://127.0.0.1:8000/admin/), not via environment variables.

### Step 6: Database Setup

```bash
cd backend

# Run migrations
python manage.py migrate

# Create default tenant and seed data
python manage.py seed_data
```

### Step 7: Start Services

```bash
# From project root directory

# Production mode (builds frontend, starts Daphne)
./start.sh

# Development mode (hot reload for frontend)
./start.sh dev

# Backend only
./start.sh backend
```

### Step 8: Verify Installation

1. **Health Check**: Visit http://127.0.0.1:8000/health_check/
   - Should return: `{"status": "ok"}`

2. **Admin Panel**: Visit http://127.0.0.1:8000/admin/
   - Login with superuser credentials

3. **Chat Interface**: Visit http://127.0.0.1:8000/
   - Should display the chat UI

---

## Method 3: Docker Compose

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+

### Build and Start

```bash
# Clone repository
git clone https://github.com/your-org/asri.git
cd asri

# Build and start all services
docker compose up --build -d

# View logs
docker compose logs -f

# Stop services
docker compose down
```

### Configuration

Set environment variables in `docker-compose.yml` or create a `.env` file:

```bash
# LLM providers are configured via Admin page, not environment variables
# See: http://127.0.0.1:8000/admin/

# Optional: MySQL instead of SQLite
DB_HOST=mysql
DB_NAME=asri
DB_USER=root
DB_PASSWORD=your-password
```

---

## Method 4: Production Deployment

### Server Requirements

- **CPU**: 2+ cores
- **RAM**: 4GB+
- **Disk**: 20GB+
- **OS**: Ubuntu 20.04+ / CentOS 8+

### Step 1: Install System Dependencies

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3-pip nodejs npm mysql-client redis-server nginx

# CentOS/RHEL
sudo yum install -y python3.10 nodejs npm mysql redis nginx
```

### Step 2: Set Up Application

```bash
# Clone repository
git clone https://github.com/your-org/asri.git /opt/asri
cd /opt/asri

# Create virtual environment
python3.10 -m venv .venv
source .venv/bin/activate

# Install dependencies
cd backend
pip install -r requirements.txt
# Note: ASRI uses Daphne (ASGI) as its production server, not Gunicorn (WSGI)
```

### Step 3: Configure Environment

```bash
cp .env.example .env
# Edit .env with production configuration
```

**Production Checklist**:
- [ ] Set strong `DJANGO_SECRET_KEY` (50+ characters)
- [ ] Set `DJANGO_DEBUG=false` to disable debug mode
- [ ] Set production database credentials
- [ ] Configure Redis host and port

### Step 4: Database Setup

```bash
# Create production database
mysql -u root -p -e "CREATE DATABASE asri CHARACTER SET utf8mb4;"

# Run migrations
cd /opt/asri/backend
python manage.py migrate
python manage.py createsuperuser
```

### Step 5: Configure Daphne (ASGI Server)

Create `/etc/systemd/system/asri.service`:

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
# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable asri
sudo systemctl start asri

# Check status
sudo systemctl status asri
```

### Step 6: Configure Nginx

Create `/etc/nginx/sites-available/asri`:

```nginx
upstream asri_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    # Redirect HTTP to HTTPS (recommended)
    # return 301 https://$server_name$request_uri;

    location / {
        proxy_pass http://asri_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # Static files
    location /static/ {
        alias /opt/asri/backend/static/;
        expires 30d;
    }

    # Media files
    location /media/ {
        alias /opt/asri/backend/media/;
        expires 30d;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/asri /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Step 7: SSL/TLS (Recommended)

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal is configured automatically
```

---

## Frontend Development

### Development Mode (Hot Reload)

```bash
cd frontend
npm run dev
# Frontend runs on http://localhost:5173
# Backend API on http://localhost:8000
```

### Production Build

```bash
cd frontend
npm run build
# Output: frontend/dist/
```

The `start.sh` script automatically handles frontend builds and updates Django templates.

---

## Troubleshooting

### Port 8000 Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill process
kill -9 <PID>
```

### Database Connection Error

- Verify MySQL is running: `sudo systemctl status mysql`
- Check credentials in `.env`
- Ensure database exists: `mysql -u root -p -e "SHOW DATABASES;"`
- Test connection: `mysql -h 127.0.0.1 -u root -p asri`

### WebSocket Connection Failed

- Ensure using Daphne, not `runserver`
- Check Redis is running (if configured)
- Verify ASGI routing in `config/asgi.py`
- Check Nginx WebSocket proxy headers (see Step 6)

### Frontend Build Errors

```bash
# Clear npm cache
npm cache clean --force

# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install

# Build again
npm run build
```

### White Screen on Access

- Check browser console for JavaScript errors
- Verify static files are collected: `python manage.py collectstatic`
- Ensure `start.sh` was used (updates template references)
- Check `templates/frontend/index.html` has correct JS/CSS paths

### Migration Errors

```bash
# Show pending migrations
python manage.py showmigrations

# Fake migrations if needed
python manage.py migrate --fake

# Reset migrations (dangerous!)
python manage.py migrate chatbot zero
python manage.py migrate
```

---

## Next Steps

After successful installation:

1. Read the [Architecture Guide](docs/ARCHITECTURE.md) to understand the system
2. Read the [Chat API](docs/chat-api.md) to learn API usage
3. Configure your first LLM Provider in the admin panel
4. Create a test session and start chatting!

For questions or issues, see [CONTRIBUTING.md](CONTRIBUTING.md).
