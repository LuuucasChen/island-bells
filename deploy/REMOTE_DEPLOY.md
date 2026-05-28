# 远程部署指南（从本地电脑部署到云服务器）

> 适用场景：在本地开发完成后，通过 SSH 远程将项目部署到云服务器  
> 前置条件：本地已安装 Python 3.11+、pip、paramiko

---

## 快速开始

### 1. 安装 paramiko（SSH 远程执行）

```bash
pip install paramiko
```

### 2. 执行远程部署

创建 `deploy_remote.py`（或复用本次的 `_remote_deploy.py`），通过 paramiko 连接服务器执行部署命令。

**核心流程**（共 5 步）：

```
检查环境 → 安装 Docker → 拉取代码 + 构建前端 → 启动 MySQL → 配置服务
```

---

## 详细步骤

### Step 1：检查服务器环境

```python
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('服务器IP', username='用户名', password='密码')

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    print(stdout.read().decode())
    return stdout.channel.recv_exit_status()

# 检查基础环境
run("docker --version 2>/dev/null || echo 'Docker: 未安装'")
run("python3 --version 2>/dev/null || echo 'Python3: 未安装'")
run("node --version 2>/dev/null || echo 'Node: 未安装'")
run("ls /opt/island_bells 2>/dev/null || echo '项目: 未克隆'")
```

**预期结果**：
- Python 3.11+ ✓
- Node.js 18+ ✓
- Docker：可能需要安装

### Step 2：安装 Docker（如未安装）

> **注意**：国内服务器 Docker Hub 可能无法访问，需使用阿里云镜像源。

```python
# 1. 添加 Docker 阿里云镜像源
run("""
sudo apt-get update -qq && \
sudo apt-get install -y -qq ca-certificates curl gnupg && \
sudo install -m 0755 -d /etc/apt/keyrings && \
curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
sudo chmod a+r /etc/apt/keyrings/docker.gpg
""")

run("""
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://mirrors.aliyun.com/docker-ce/linux/ubuntu \
$(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
""")

run("sudo apt-get update -qq")

# 2. 安装 Docker（超时设长，约 3-5 分钟）
run("sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin")
run("sudo usermod -aG docker $USER")

# 3. 配置镜像加速器（解决国内拉镜像慢的问题）
run("""
sudo mkdir -p /etc/docker && \
echo '{"registry-mirrors":["https://mirror.ccs.tencentyun.com","https://docker.mirrors.ustc.edu.cn"]}' | \
sudo tee /etc/docker/daemon.json
""")
run("sudo systemctl daemon-reload && sudo systemctl restart docker")
```

**验证**：
```python
run("docker --version")  # 应显示 Docker version 29.x.x
```

### Step 3：拉取代码 + 构建前端

```python
# 1. 克隆项目（首次）或更新代码
run("ls /opt/island_bells/.git 2>/dev/null && echo EXISTS || echo MISSING")
# 如果 MISSING:
run("sudo git clone https://github.com/LuuucasChen/island-bells.git /opt/island_bells")
run("sudo chown -R $USER:$USER /opt/island_bells")
# 如果 EXISTS:
run("cd /opt/island_bells && git stash && git pull")

# 2. 配置环境变量
run("cp -n /opt/island_bells/deploy/.env.example /opt/island_bells/deploy/.env")

# 3. 安装后端依赖
run("cd /opt/island_bells/backend && python3 -m venv venv")
run("cd /opt/island_bells/backend && source venv/bin/activate && pip install -q -r requirements.txt")

# 4. 构建前端
run("cd /opt/island_bells/web && npm install --production=false")
run("cd /opt/island_bells/web && npm run build")

# 5. 创建日志目录
run("mkdir -p /opt/island_bells/logs")
```

### Step 4：启动 MySQL 容器

```python
import time

# 链接 .env 供 docker compose 读取
run("cd /opt/island_bells/backend && ln -sf ../deploy/.env .env")

# 启动 MySQL 容器
run("cd /opt/island_bells/backend && sudo docker compose up -d")

# 等待 MySQL 初始化（首次约 30 秒）
print("等待 MySQL 初始化...")
time.sleep(20)
for i in range(15):
    code = run("sudo docker exec island_bells_mysql mysqladmin ping -h localhost --silent 2>/dev/null")
    if code == 0:
        print("MySQL 就绪!")
        break
    time.sleep(3)
```

### Step 5：配置系统服务 + Nginx

```python
# 1. systemd 服务（后端）
run("sudo cp /opt/island_bells/deploy/island-bells.service /etc/systemd/system/")
run("sudo systemctl daemon-reload")
run("sudo systemctl enable island-bells")
run("sudo systemctl restart island-bells")

# 2. Nginx（前端静态 + 反向代理）
run("sudo apt-get install -y -qq nginx")
run("sudo cp /opt/island_bells/deploy/nginx.conf /etc/nginx/sites-available/island-bells")
run("sudo ln -sf /etc/nginx/sites-available/island-bells /etc/nginx/sites-enabled/")
run("sudo rm -f /etc/nginx/sites-enabled/default")
run("sudo nginx -t && sudo systemctl restart nginx")

# 3. 日志轮转 cron
run("chmod +x /opt/island_bells/deploy/rotate_logs.sh")
run('crontab -l 2>/dev/null | grep -q rotate_logs || (crontab -l 2>/dev/null; echo "*/15 * * * * /opt/island_bells/deploy/rotate_logs.sh") | crontab -')

# 4. 防火墙
run("sudo ufw allow 22/tcp; sudo ufw allow 80/tcp; sudo ufw --force enable")

# 5. 验证
run("curl -s http://127.0.0.1:8000/health")  # {"status":"ok","app":"岛屿铃钱记"}
run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/")  # 200
```

---

## 关闭服务

### 停止后端

```python
run("sudo systemctl stop island-bells")
```

### 停止 MySQL 容器

```python
run("sudo docker stop island_bells_mysql")
```

### 停止 Nginx

```python
run("sudo systemctl stop nginx")
```

### 一键全部关闭

```python
run("sudo systemctl stop island-bells nginx")
run("sudo docker stop island_bells_mysql")
```

---

## 重启服务

```python
# 重启后端（代码更新后）
run("sudo systemctl restart island-bells")

# 重启 MySQL
run("sudo docker restart island_bells_mysql")

# 重启 Nginx
run("sudo systemctl restart nginx")
```

---

## 更新代码

```python
# 1. 拉取最新代码
run("cd /opt/island_bells && git pull")

# 2. 更新后端依赖
run("cd /opt/island_bells/backend && source venv/bin/activate && pip install -q -r requirements.txt")

# 3. 重新构建前端
run("cd /opt/island_bells/web && npm run build")

# 4. 重启后端
run("sudo systemctl restart island-bells")
```

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| Docker Hub 拉镜像超时 | 配置 `daemon.json` 镜像加速器（见 Step 2） |
| SSH 密钥认证失败 | 检查 `~/.ssh` 权限 700，`authorized_keys` 权限 600，家目录权限 755 |
| paramiko 超时 | 对 `apt-get install` 等长命令设置 `timeout=300` |
| `sudo` 需要密码 | paramiko 的 `exec_command` 默认无法交互输入密码，需配置 `NOPASSWD` 或用 `invoke_shell` |
