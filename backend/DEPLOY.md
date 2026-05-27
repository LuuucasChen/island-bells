# 岛屿铃钱记 — 生产部署指南

> 德州扑克铃钱管理工具，支持网页版 + 微信小程序  
> 部署方式：systemd + Nginx（Ubuntu 22.04 LTS）  
> 数据库：SQLite（Demo / 轻量部署）  
> 代码仓库：https://github.com/LuuucasChen/island-bells

---

## 环境要求

| 项目 | 要求 |
|------|------|
| **系统** | Ubuntu 22.04 LTS（或其它 systemd 发行版） |
| **Python** | 3.11+ |
| **Node.js** | 18+（仅构建前端时需要） |
| **内存** | 最低 512MB，推荐 1GB |
| **端口** | 安全组需开放 `22`(SSH)、`80`(HTTP)；有域名时额外开放 `443`(HTTPS) |

---

## 架构概览

```
                    ┌─────────┐
    用户浏览器 ───▶ │  Nginx  │ :80 / :443
    微信小程序      │ (反向代理)│
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
              SQLite DB
         backend/data/island_bells.db
```

---

## 1. 从 GitHub 拉取代码到服务器

```bash
cd /opt
sudo git clone https://github.com/LuuucasChen/island-bells.git island_bells
sudo chown -R www-data:www-data island_bells
```

> **无域名部署说明**：没有域名时，直接用服务器**公网 IP** 访问即可。Nginx 配置中 `server_name _;` 已兼容 IP 直接访问。后续如需绑定域名，修改 `deploy/nginx.conf` 中的 `server_name` 并配置 HTTPS。

---

## 2. 安装后端依赖

```bash
cd /opt/island_bells/backend

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

---

## 3. 构建前端

```bash
cd /opt/island_bells/web

# 安装依赖（包含开发依赖，构建后不再需要）
npm install

# 构建生产版本
npm run build
```

构建产物输出到 `web/dist/`，由 Nginx 直接提供静态服务。

> **注意**：`animal-island-ui` 组件库位于 `_reference_ui/` 目录，npm install 时会自动通过 `file:` 协议链接安装。

---

## 4. 初始化 SQLite 数据库

```bash
cd /opt/island_bells/backend
source venv/bin/activate

# 创建数据目录
mkdir -p data

# 设置环境变量并初始化表结构
DATABASE_URL="sqlite:///./data/island_bells.db" python3 -c "
import os
os.environ['DATABASE_URL'] = 'sqlite:///./data/island_bells.db'
from app.database import Base, engine
from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult, Rebuy
Base.metadata.create_all(bind=engine)
print('✅ 数据库初始化完成')
"
```

验证：

```bash
ls -la data/island_bells.db
# 应看到数据库文件
```

---

## 5. 配置环境变量（可选）

如需自定义配置，创建 `.env` 文件：

```bash
nano /opt/island_bells/backend/.env
```

```ini
# 数据库（默认 MySQL，这里改为 SQLite）
DATABASE_URL=sqlite:///./data/island_bells.db

# JWT 密钥（⚠️ 务必修改为随机字符串）
JWT_SECRET=your-random-secret-string-here

# JWT 过期时间（小时）
JWT_EXPIRE_HOURS=72

# 房间配置
ROOM_CODE_LENGTH=6
MAX_PLAYERS=9

# 微信小程序（如有）
WECHAT_APPID=
WECHAT_SECRET=
```

> **生成随机密钥**：`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

---

## 6. 配置 systemd 服务

```bash
# 复制服务文件
sudo cp /opt/island_bells/deploy/island-bells.service /etc/systemd/system/

# ⚠️ 修改 JWT_SECRET（重要！）
sudo nano /etc/systemd/system/island-bells.service
# 将 Environment=JWT_SECRET=CHANGE_ME_TO_A_RANDOM_STRING 改为你的密钥

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

---

## 7. 安装并配置 Nginx

```bash
sudo apt update
sudo apt install nginx -y

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

## 8. 配置 HTTPS（有域名时可选）

> 如果没有域名，**跳过此步骤**，直接用 `http://<公网IP>` 访问。

```bash
sudo apt install certbot python3-certbot-nginx -y

# 替换为你的域名
sudo certbot --nginx -d your-domain.com

# 自动续期测试
sudo certbot renew --dry-run
```

---

## 9. 防火墙配置

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
# 有域名并配置 HTTPS 时再开放 443
# sudo ufw allow 443/tcp
sudo ufw enable
```

---

## 10. 备份策略

SQLite 数据库是单文件，备份非常简单：

```bash
# 创建备份目录
sudo mkdir -p /opt/backups

# 手动备份
sudo cp /opt/island_bells/backend/data/island_bells.db \
        /opt/backups/island_bells_$(date +%Y%m%d).db

# 添加定时任务（每天凌晨 3 点备份，保留 7 天）
sudo crontab -e
# 添加以下行：
0 3 * * * cp /opt/island_bells/backend/data/island_bells.db /opt/backups/island_bells_$(date +\%Y\%m\%d).db && find /opt/backups -name "island_bells_*.db" -mtime +7 -delete
```

---

## 11. 日常运维

```bash
# 查看服务状态
sudo systemctl status island-bells

# 查看实时日志
sudo journalctl -u island-bells -f

# 重启服务
sudo systemctl restart island-bells

# 查看 Nginx 日志
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
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

---

## 12. 故障排查

| 现象 | 排查方法 |
|------|----------|
| 页面无法访问 | `sudo systemctl status island-bells nginx` |
| API 返回 502 | 后端未启动，检查 `journalctl -u island-bells -n 50` |
| WebSocket 断开 | 检查 Nginx `proxy_read_timeout` 是否够大 |
| 数据库锁定 | SQLite 并发写入有限，重启服务即可 |
| 前端白屏 | 确认 `web/dist/` 目录存在且包含 `index.html` |
| 提示 CORS 错误 | 检查 Nginx 是否正确代理 `/v1/` 路径 |

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
│   │   └── services/        # 业务逻辑层
│   ├── venv/                # Python 虚拟环境
│   ├── data/                # SQLite 数据库文件
│   │   └── island_bells.db
│   ├── tests/               # 单元测试
│   ├── requirements.txt     # Python 依赖
│   └── run_dev.py           # 本地开发启动脚本
├── web/                     # React 网页版前端
│   ├── src/
│   ├── dist/                # 构建产物（Nginx 指向此处）
│   └── package.json
├── miniprogram/             # 微信小程序前端
├── _reference_ui/           # UI 组件库 (animal-island-ui)
├── deploy/                  # 部署配置
│   ├── island-bells.service # systemd 服务文件
│   ├── nginx.conf           # Nginx 站点配置
│   └── start.sh             # 一键启动脚本（调试用）
└── DEPLOY.md                # 本文档
```

---

## 快速验证清单

- [ ] 代码已 clone 到 `/opt/island_bells`
- [ ] 后端虚拟环境已创建，依赖已安装
- [ ] 前端已构建，`web/dist/index.html` 存在
- [ ] SQLite 数据库已初始化，`backend/data/island_bells.db` 存在
- [ ] `.env` 中 `JWT_SECRET` 已修改为随机字符串
- [ ] systemd 服务已启用并运行 (`systemctl status island-bells`)
- [ ] Nginx 已安装并配置正确 (`nginx -t`)
- [ ] 防火墙已开放 80（有域名时再开 443）
- [ ] `curl http://127.0.0.1:8000/health` 返回正常
- [ ] 浏览器访问 `http://<公网IP>` 看到前端页面
- [ ] （可选）HTTPS 证书已配置
- [ ] 备份定时任务已配置

---

## 一键部署脚本（快速体验）

如果想跳过 systemd/Nginx 快速体验，可直接运行：

```bash
cd /opt/island_bells
bash deploy/start.sh
```

> ⚠️ 此方式仅用于演示/调试，正式部署请使用 systemd + Nginx 方案。
