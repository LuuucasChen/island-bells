# 岛屿铃钱记 — 生产部署指南

> 线下牌桌铃钱记分工具，网页版多人德州扑克  
> 部署方式：MySQL Docker 容器 + FastAPI 直接运行 + Nginx 反向代理  
> 适用系统：Ubuntu 22.04 LTS（或其它 systemd 发行版）  
> 代码仓库：https://github.com/LuuucasChen/island-bells

---

## 环境要求

| 项目 | 要求 |
|------|------|
| **系统** | Ubuntu 22.04 LTS（或其它 systemd 发行版） |
| **Python** | 3.11+ |
| **Docker** | 20.10+（运行 MySQL 容器） |
| **Node.js** | 18+（仅构建前端时需要） |
| **内存** | 最低 1GB，推荐 2GB |
| **端口** | 安全组需开放 `22`(SSH)、`80`(HTTP)；有域名时额外开放 `443`(HTTPS) |

---

## 架构概览

```
                    ┌─────────┐
    用户浏览器 ───▶ │  Nginx  │ :80 / :443
                    │ (反向代理)│
                    └────┬────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
         /v1/* API   /ws/* WS   静态文件
              │          │       web/dist/
              ▼          ▼
        ┌──────────────────────┐
        │  FastAPI (uvicorn)   │ :8000
        │  127.0.0.1:8000      │
        └──────────┬───────────┘
                   │
        ┌──────────▼───────────┐
        │  MySQL 8.0 (Docker)  │ :3306
        │  island_bells_mysql  │
        └──────────────────────┘
```

### 环境区分

| | 本地开发 | 云端生产 |
|---|---------|---------|
| **数据库** | SQLite（零配置） | MySQL 8.0（Docker 容器） |
| **启动方式** | `python run_dev.py` | systemd + `deploy/.env` |
| **配置来源** | `config.py` 默认值 | `deploy/.env` 环境变量 |
| **环境变量** | `APP_ENV=dev` | `APP_ENV=prod` |

---

## 1. 从 GitHub 拉取代码

```bash
cd /opt
sudo git clone https://github.com/LuuucasChen/island-bells.git island_bells
sudo chown -R www-data:www-data island_bells
```

> **无域名部署**：没有域名时，直接用服务器公网 IP 访问。Nginx 配置 `server_name _;` 已兼容 IP 直接访问。

---

## 2. 安装 Docker

```bash
# 安装 Docker（如未安装）
curl -fsSL https://get.docker.com | sudo sh

# 将当前用户加入 docker 组（免 sudo）
sudo usermod -aG docker $USER
# 重新登录生效

# 验证
docker --version
```

---

## 3. 配置环境变量

```bash
cd /opt/island_bells/deploy

# 从模板创建配置文件
cp .env.example .env
```

默认配置已可正常使用。如需自定义，编辑 `.env`：

```ini
# 环境标识
APP_ENV=prod

# MySQL 连接串（用户名密码需与下方容器密码一致）
DATABASE_URL=mysql+pymysql://bells:nookring2024@localhost:3306/island_bells?charset=utf8mb4

# MySQL 容器密码
MYSQL_ROOT_PASSWORD=tanukichi_root
MYSQL_PASSWORD=nookring2024
MYSQL_DATABASE=island_bells
MYSQL_USER=bells

# JWT 密钥
JWT_SECRET=island-bells-jwt-nook-secret

# 房间配置
ROOM_CODE_LENGTH=6
MAX_PLAYERS=9
```

> 生成随机 JWT 密钥：`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

---

## 4. 启动 MySQL 容器

### 方式 A：使用 docker-compose（推荐）

```bash
cd /opt/island_bells/backend

# 链接 .env 供 docker-compose 读取
ln -sf ../deploy/.env .env

# 启动 MySQL 容器（-d 后台运行）
docker-compose up -d
```

### 方式 B：手动 docker run

```bash
docker run -d \
    --name island_bells_mysql \
    --restart unless-stopped \
    -p 3306:3306 \
    -e MYSQL_ROOT_PASSWORD=tanukichi_root \
    -e MYSQL_DATABASE=island_bells \
    -e MYSQL_USER=bells \
    -e MYSQL_PASSWORD=nookring2024 \
    -v island_bells_data:/var/lib/mysql \
    mysql:8.0 \
    --character-set-server=utf8mb4 \
    --collation-server=utf8mb4_unicode_ci
```

### 验证 MySQL 就绪

```bash
# 等待初始化（约 15-30 秒）
docker exec island_bells_mysql mysqladmin ping -h localhost --silent
# 返回 "mysqld is alive" 即就绪

# 测试连接
docker exec -it island_bells_mysql mysql -u bells -pnookring2024 island_bells -e "SELECT 1"
```

> **表结构无需手动创建**，后端首次启动时自动建表。

---

## 5. 安装后端依赖

```bash
cd /opt/island_bells/backend

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

---

## 6. 构建前端

```bash
cd /opt/island_bells/web

# 安装依赖
npm install

# 构建生产版本
npm run build
```

构建产物输出到 `web/dist/`，由 Nginx 直接提供静态服务。

> **注意**：`animal-island-ui` 组件库位于 `_reference_ui/` 目录，npm install 时自动通过 `file:` 协议链接安装。

---

## 7. 配置 systemd 服务

```bash
# 复制服务文件
sudo cp /opt/island_bells/deploy/island-bells.service /etc/systemd/system/

# 创建日志目录
sudo mkdir -p /opt/island_bells/logs
sudo chown www-data:www-data /opt/island_bells/logs

# 重新加载并启动
sudo systemctl daemon-reload
sudo systemctl enable island-bells
sudo systemctl start island-bells

# 查看状态
sudo systemctl status island-bells
```

验证后端运行正常：

```bash
curl http://127.0.0.1:8000/health
# 应返回: {"status":"ok","app":"岛屿铃钱记"}
```

> systemd 服务自动从 `deploy/.env` 加载环境变量，首次启动自动建表。

---

## 8. 安装并配置 Nginx

```bash
sudo apt update
sudo apt install nginx -y

# 创建日志目录（如不存在）
sudo mkdir -p /opt/island_bells/logs
sudo chown www-data:www-data /opt/island_bells/logs

# 复制站点配置
sudo cp /opt/island_bells/deploy/nginx.conf /etc/nginx/sites-available/island-bells
sudo ln -sf /etc/nginx/sites-available/island-bells /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 检查配置并重启
sudo nginx -t
sudo systemctl restart nginx
```

验证：浏览器访问 `http://<服务器公网IP>`，应看到前端页面。

---

## 9. 配置日志轮转

日志输出到 `/opt/island_bells/logs/`，包含 warning 级别以上的后端日志和 Nginx 访问/错误日志。  
每 15 分钟自动轮转，1 小时前的旧日志自动清理。

```bash
# 赋予执行权限
chmod +x /opt/island_bells/deploy/rotate_logs.sh

# 安装 cron 定时任务
crontab -e
# 添加以下行：
*/15 * * * * /opt/island_bells/deploy/rotate_logs.sh
```

### 日志文件说明

| 文件 | 内容 |
|------|------|
| `backend.log` | 后端 uvicorn 访问日志 + 应用日志 (warning+) |
| `backend-error.log` | 后端错误输出 (warning+) |
| `nginx-access.log` | Nginx 访问日志 |
| `nginx-error.log` | Nginx 错误日志 (warn+) |

轮转后文件名带时间戳，如 `backend.log.20250527_1430`。

---

## 10. 配置 HTTPS（有域名时可选）

> 没有域名则跳过此步骤，直接用 `http://<公网IP>` 访问。

```bash
sudo apt install certbot python3-certbot-nginx -y

# 替换为你的域名
sudo certbot --nginx -d your-domain.com

# 自动续期测试
sudo certbot renew --dry-run
```

---

## 11. 防火墙配置

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
# 有域名并配置 HTTPS 时再开放 443
# sudo ufw allow 443/tcp
sudo ufw enable
```

> **注意**：MySQL 3306 端口**不要**对外开放，仅后端通过 localhost 访问。

---

## 12. 日常运维

### 服务管理

```bash
# 查看后端状态
sudo systemctl status island-bells

# 查看后端实时日志
sudo journalctl -u island-bells -f

# 重启后端
sudo systemctl restart island-bells
```

### MySQL 容器管理

```bash
# 查看容器状态
docker ps | grep island_bells_mysql

# 查看 MySQL 日志
docker logs island_bells_mysql --tail 50

# 重启 MySQL 容器
docker restart island_bells_mysql

# 进入 MySQL 命令行
docker exec -it island_bells_mysql mysql -u bells -pnookring2024 island_bells
```

### 查看应用日志

```bash
# 实时查看后端日志
tail -f /opt/island_bells/logs/backend.log

# 查看 Nginx 错误日志
tail -f /opt/island_bells/logs/nginx-error.log

# 查看已轮转的历史日志
ls -la /opt/island_bells/logs/*.log.*
```

### 更新代码

```bash
cd /opt/island_bells

# 拉取最新代码
sudo git pull

# 更新后端依赖
cd backend && source venv/bin/activate && pip install -r requirements.txt

# 重新构建前端
cd ../web && npm run build

# 重启服务
sudo systemctl restart island-bells
```

> MySQL 表结构如有变更，后端重启时 `Base.metadata.create_all()` 自动处理新增表。如需字段变更，使用 Alembic 迁移或手动 ALTER TABLE。

---

## 13. 故障排查

| 现象 | 排查方法 |
|------|----------|
| 页面无法访问 | `sudo systemctl status island-bells nginx` |
| API 返回 502 | 后端未启动，`journalctl -u island-bells -n 50` |
| API 返回数据库错误 | MySQL 容器未运行，`docker ps \| grep mysql` |
| WebSocket 断开 | 检查 Nginx `proxy_read_timeout` 是否够大 |
| 前端白屏 | 确认 `web/dist/` 目录存在且包含 `index.html` |
| 提示 CORS 错误 | 检查 Nginx 是否正确代理 `/v1/` 路径 |
| 容器启动失败 | `docker logs island_bells_mysql`，检查端口 3306 是否被占用 |
| 日志目录权限错误 | `sudo chown -R www-data:www-data /opt/island_bells/logs` |

---

## 目录结构（服务器端）

```
/opt/island_bells/
├── backend/
│   ├── app/                 # FastAPI 应用代码
│   │   ├── api/             # REST + WebSocket 路由
│   │   ├── engine/          # 德州扑克引擎（发牌、评估、结算）
│   │   ├── models/          # SQLAlchemy 数据模型
│   │   ├── schemas/         # Pydantic 请求/响应模型
│   │   └── utils/           # 工具函数（JWT、动物名等）
│   ├── venv/                # Python 虚拟环境
│   ├── tests/               # 单元测试
│   ├── requirements.txt     # Python 依赖
│   ├── docker-compose.yml   # MySQL 容器配置
│   └── run_dev.py           # 本地开发启动脚本（SQLite）
├── web/                     # React 网页版前端
│   ├── src/
│   ├── dist/                # 构建产物（Nginx 指向此处）
│   └── package.json
├── _reference_ui/           # UI 组件库 (animal-island-ui)
├── logs/                    # 日志目录（自动轮转，1小时后清理）
│   ├── backend.log          # 后端应用日志
│   ├── backend-error.log    # 后端错误输出
│   ├── nginx-access.log     # Nginx 访问日志
│   └── nginx-error.log      # Nginx 错误日志
├── deploy/                  # 部署配置
│   ├── .env                 # 环境变量（⚠️ 不要提交到 Git）
│   ├── .env.example         # 环境变量模板
│   ├── island-bells.service # systemd 服务文件
│   ├── nginx.conf           # Nginx 站点配置
│   ├── rotate_logs.sh       # 日志轮转脚本（cron 调用）
│   └── start_prod.sh        # 一键启动脚本（调试用）
└── DEPLOY.md                # 本文档
```

---

## 快速验证清单

- [ ] Docker 已安装并运行 (`docker --version`)
- [ ] 代码已 clone 到 `/opt/island_bells`
- [ ] `deploy/.env` 已创建
- [ ] MySQL 容器已运行 (`docker ps | grep mysql`)
- [ ] 后端虚拟环境已创建，依赖已安装
- [ ] 前端已构建，`web/dist/index.html` 存在
- [ ] `logs/` 目录已创建
- [ ] systemd 服务已启用 (`systemctl status island-bells`)
- [ ] Nginx 已安装并配置正确 (`nginx -t`)
- [ ] 日志轮转 cron 已安装 (`crontab -l`)
- [ ] 防火墙已开放 80（有域名时再开 443）
- [ ] `curl http://127.0.0.1:8000/health` 返回正常
- [ ] 浏览器访问 `http://<公网IP>` 看到前端页面

---

## 附：一键部署脚本（快速体验）

如果不需要 systemd/Nginx，可直接用脚本快速启动：

```bash
cd /opt/island_bells
chmod +x deploy/start_prod.sh
./deploy/start_prod.sh
```

> 此脚本会自动启动 MySQL 容器 + 后端服务（前台运行），并配置日志轮转 cron。  
> 仅用于演示/调试，正式部署请使用 systemd + Nginx 方案。
