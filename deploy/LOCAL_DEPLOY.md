# 服务器本地部署指南

> 适用场景：SSH 登录到服务器后，在服务器上直接操作部署  
> 前置条件：Ubuntu 22.04 LTS，具有 sudo 权限的用户

---

## 快速部署（一键脚本）

如果服务器已有 Docker 和网络环境，可直接运行：

```bash
cd /opt/island_bells
chmod +x deploy/start_prod.sh
./deploy/start_prod.sh
```

> 此脚本会自动完成 MySQL 容器启动 + 依赖安装 + 后端启动。  
> 正式环境建议使用下方的完整步骤。

---

## 完整部署步骤

### 1. 安装 Docker

```bash
# 使用阿里云镜像源（国内服务器推荐）
sudo apt-get update -qq
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://mirrors.aliyun.com/docker-ce/linux/ubuntu \
$(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 将当前用户加入 docker 组（免 sudo，需重新登录生效）
sudo usermod -aG docker $USER
```

**配置镜像加速器**（避免拉镜像超时）：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com",
    "https://docker.mirrors.ustc.edu.cn"
  ]
}
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker
```

**验证**：

```bash
docker --version    # Docker version 29.x.x
docker run hello-world
```

### 2. 克隆项目代码

```bash
cd /opt
sudo git clone https://github.com/LuuucasChen/island-bells.git island_bells
sudo chown -R $USER:$USER island_bells
cd island_bells
```

### 3. 配置环境变量

```bash
# 从模板创建（首次部署）
cp deploy/.env.example deploy/.env

# 按需编辑（默认值已可直接使用）
nano deploy/.env
```

默认配置：

```ini
APP_ENV=prod
DATABASE_URL=mysql+pymysql://bells:nookring2024@localhost:3306/island_bells?charset=utf8mb4
MYSQL_ROOT_PASSWORD=tanukichi_root
MYSQL_PASSWORD=nookring2024
MYSQL_DATABASE=island_bells
MYSQL_USER=bells
JWT_SECRET=island-bells-jwt-nook-secret
```

### 4. 启动 MySQL 容器

```bash
cd /opt/island_bells/backend

# 链接 .env
ln -sf ../deploy/.env .env

# 启动 MySQL 容器
sudo docker compose up -d

# 等待初始化（约 30 秒）
echo "等待 MySQL..."
for i in $(seq 1 15); do
  if sudo docker exec island_bells_mysql mysqladmin ping -h localhost --silent 2>/dev/null; then
    echo "MySQL 就绪!"
    break
  fi
  sleep 3
done
```

### 5. 安装后端依赖

```bash
cd /opt/island_bells/backend

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 6. 构建前端

```bash
cd /opt/island_bells/web

# 安装依赖 + 构建
npm install
npm run build
```

构建产物在 `web/dist/`，由 Nginx 提供静态服务。

### 7. 配置 systemd 服务（后端）

```bash
# 创建日志目录
sudo mkdir -p /opt/island_bells/logs
sudo chown $USER:$USER /opt/island_bells/logs

# 安装服务
sudo cp /opt/island_bells/deploy/island-bells.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable island-bells
sudo systemctl start island-bells

# 验证
sudo systemctl status island-bells
curl http://127.0.0.1:8000/health
# 应返回: {"status":"ok","app":"岛屿铃钱记"}
```

### 8. 配置 Nginx

```bash
# 安装 Nginx
sudo apt install nginx -y

# 安装站点配置
sudo cp /opt/island_bells/deploy/nginx.conf /etc/nginx/sites-available/island-bells
sudo ln -sf /etc/nginx/sites-available/island-bells /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 检查并重载
sudo nginx -t
sudo systemctl restart nginx
```

**验证**：浏览器访问 `http://<服务器IP>`，应看到前端页面。

### 9. 配置日志轮转

```bash
# 赋予执行权限
chmod +x /opt/island_bells/deploy/rotate_logs.sh

# 安装 cron（每 15 分钟轮转，1 小时前的日志自动清理）
(crontab -l 2>/dev/null; echo "*/15 * * * * /opt/island_bells/deploy/rotate_logs.sh") | crontab -

# 验证
crontab -l | grep rotate
```

### 10. 配置防火墙

```bash
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw --force enable
# 如需 HTTPS: sudo ufw allow 443/tcp
```

> **注意**：3306 (MySQL) 端口**不要**对外开放。

---

## 关闭服务

### 停止后端

```bash
sudo systemctl stop island-bells
```

### 停止 MySQL

```bash
sudo docker stop island_bells_mysql
```

### 停止 Nginx

```bash
sudo systemctl stop nginx
```

### 一键全部关闭

```bash
sudo systemctl stop island-bells nginx
sudo docker stop island_bells_mysql
```

---

## 重启服务

```bash
# 重启后端
sudo systemctl restart island-bells

# 重启 MySQL
sudo docker restart island_bells_mysql

# 重启 Nginx
sudo systemctl restart nginx
```

---

## 更新代码

```bash
cd /opt/island_bells

# 1. 拉取最新代码
git pull

# 2. 更新后端依赖
cd backend && source venv/bin/activate && pip install -r requirements.txt

# 3. 重新构建前端
cd ../web && npm run build

# 4. 重启后端
sudo systemctl restart island-bells
```

---

## 查看日志

```bash
# 后端应用日志
tail -f /opt/island_bells/logs/backend.log

# 后端错误日志
tail -f /opt/island_bells/logs/backend-error.log

# Nginx 访问日志
tail -f /opt/island_bells/logs/nginx-access.log

# Nginx 错误日志
tail -f /opt/island_bells/logs/nginx-error.log

# systemd 日志
sudo journalctl -u island-bells -f

# MySQL 容器日志
sudo docker logs island_bells_mysql --tail 50
```

---

## 日常运维命令速查

| 操作 | 命令 |
|------|------|
| 查看后端状态 | `sudo systemctl status island-bells` |
| 查看 MySQL 状态 | `sudo docker ps \| grep mysql` |
| 查看 Nginx 状态 | `sudo systemctl status nginx` |
| 进入 MySQL 命令行 | `sudo docker exec -it island_bells_mysql mysql -u bells -pnookring2024 island_bells` |
| 健康检查 | `curl http://127.0.0.1:8000/health` |
| 查看已轮转日志 | `ls -la /opt/island_bells/logs/*.log.*` |

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| Docker Hub 超时 | 配置 `/etc/docker/daemon.json` 镜像加速器 |
| MySQL 连接失败 | `sudo docker logs island_bells_mysql` 查看错误 |
| 后端启动失败 | `sudo journalctl -u island-bells -n 50` 查看日志 |
| Nginx 502 | 后端未运行，`sudo systemctl start island-bells` |
| 前端白屏 | 确认 `web/dist/index.html` 存在 |
| `docker compose` 找不到 | 确认安装了 `docker-compose-plugin` 包 |
