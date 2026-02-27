# pdf2zh-web

基于 [pdf2zh](https://github.com/Byaidu/PDFMathTranslate) 的多用户 PDF 学术文档翻译 Web 服务。

## 特性

- 多用户认证系统（管理员/普通用户）
- 支持 15+ 翻译引擎（OpenAI、DeepL、Google、Ollama、SiliconFlow 等）
- SSE 实时翻译进度推送
- 用户配置加密存储（Fernet）
- SQLite 持久化，零外部依赖
- 翻译历史管理与文件下载
- 多架构 Docker 镜像（amd64 / arm64）

## 快速开始

### Docker Compose（推荐）

```bash
# 克隆仓库
git clone https://github.com/neokotora/pdf2zh-web.git
cd pdf2zh-web

# 启动服务
docker compose up -d
```

服务启动后访问 `http://localhost:7860`，首次访问会引导创建管理员账户。

### 自定义配置

创建 `.env` 文件进行配置：

```bash
# 服务端口（默认 7860）
PORT=7860

# 时区
TZ=Asia/Shanghai

# 最大并发翻译数（默认 2）
MAX_CONCURRENT_TRANSLATIONS=2
```

然后启动：

```bash
docker compose up -d
```

### 直接使用 Docker

```bash
docker run -d \
  --name pdf2zh-web \
  --restart unless-stopped \
  -p 7860:7860 \
  -v pdf2zh-data:/app/data \
  -e TZ=Asia/Shanghai \
  -e MAX_CONCURRENT_TRANSLATIONS=2 \
  ghcr.io/neokotora/pdf2zh-web:latest
```

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `7860` | 服务监听端口 |
| `TZ` | `Asia/Shanghai` | 容器时区 |
| `MAX_CONCURRENT_TRANSLATIONS` | `2` | 最大并发翻译任务数 |

### 数据持久化

所有数据存储在容器内 `/app/data` 目录，通过 Docker Volume 持久化：

```
/app/data/
├── users.db          # 用户、任务、配置数据库（SQLite）
└── users/            # 用户文件目录
    └── <username>/
        ├── uploads/  # 上传的 PDF 文件
        └── outputs/  # 翻译结果文件
```

### 数据备份

```bash
# 备份
docker run --rm -v pdf2zh-data:/data -v $(pwd):/backup alpine \
  tar czf /backup/pdf2zh-backup-$(date +%Y%m%d).tar.gz -C /data .

# 恢复
docker run --rm -v pdf2zh-data:/data -v $(pwd):/backup alpine \
  sh -c "cd /data && tar xzf /backup/pdf2zh-backup-YYYYMMDD.tar.gz"
```

## 支持的翻译引擎

| 引擎 | 需要 API Key | 说明 |
|------|:---:|------|
| SiliconFlow Free | 否 | 默认引擎，免费 |
| SiliconFlow | 是 | SiliconFlow 付费版 |
| OpenAI | 是 | GPT-4o-mini 等 |
| DeepSeek | 是 | DeepSeek Chat |
| Claude | 是 | Claude Sonnet 等 |
| Gemini | 是 | Google Gemini |
| DeepL | 是 | DeepL 翻译 API |
| Azure OpenAI | 是 | Azure 托管的 OpenAI |
| Ollama | 否 | 本地模型，需部署 Ollama |
| Google | 否 | Google 翻译（免费） |
| Bing | 否 | 必应翻译（免费） |
| Tencent | 是 | 腾讯云机器翻译 |
| Zhipu | 是 | 智谱 GLM |

### 搭配 Ollama 使用

如果需要使用本地 Ollama 翻译引擎：

```yaml
services:
  pdf2zh-web:
    image: ghcr.io/neokotora/pdf2zh-web:latest
    container_name: pdf2zh-web
    restart: unless-stopped
    ports:
      - "7860:7860"
    volumes:
      - pdf2zh-data:/app/data
    environment:
      - TZ=Asia/Shanghai
      - MAX_CONCURRENT_TRANSLATIONS=2
    depends_on:
      ollama:
        condition: service_started

  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped
    ports:
      - "11434:11434"
    volumes:
      - ollama-data:/root/.ollama
    # 如需 GPU 加速，取消下方注释
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: all
    #           capabilities: [gpu]

volumes:
  pdf2zh-data:
    driver: local
  ollama-data:
    driver: local
```

启动后在 Web UI 设置页面中将翻译引擎设为 `Ollama`，Host 填写 `http://ollama:11434`。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/ready` | 就绪检查 |
| `GET` | `/api/auth/status` | 检查是否需要初始化 |
| `POST` | `/api/auth/setup` | 初始化管理员账户 |
| `POST` | `/api/auth/login` | 用户登录 |
| `POST` | `/api/auth/logout` | 用户登出 |
| `POST` | `/api/auth/register` | 管理员注册新用户 |
| `GET` | `/api/auth/users` | 获取用户列表（管理员） |
| `POST` | `/api/upload` | 上传 PDF 文件 |
| `POST` | `/api/translate` | 发起翻译任务 |
| `GET` | `/api/translate/status/{task_id}` | 查询翻译状态 |
| `GET` | `/api/translate/stream/{task_id}` | SSE 实时进度流 |
| `GET` | `/api/translate/download/{task_id}` | 下载翻译结果 |
| `GET` | `/api/translate/history` | 获取翻译历史 |
| `GET` | `/api/settings` | 获取用户设置 |
| `POST` | `/api/settings` | 更新用户设置 |
| `GET` | `/api/settings/export` | 导出设置 |
| `POST` | `/api/settings/import` | 导入设置 |

所有 `/api/*` 接口（除 `auth/status`、`auth/setup`、`auth/login`）均需在请求头中携带：

```
Authorization: Bearer <token>
```

## 更新

```bash
docker compose pull
docker compose up -d
```

## 常见问题

### 端口被占用

修改 `.env` 中的 `PORT` 或直接修改 `docker-compose.yml` 中的端口映射：

```yaml
ports:
  - "8080:7860"
```

### 忘记管理员密码

```bash
# 停止服务
docker compose down

# 删除数据库（会清除所有用户数据）
docker run --rm -v pdf2zh-data:/data alpine rm /data/users.db

# 重新启动，重新创建管理员
docker compose up -d
```

### 翻译卡在排队中

检查 `MAX_CONCURRENT_TRANSLATIONS` 设置，适当增大并发数。也可以通过重启服务来恢复卡住的任务（服务启动时会自动将未完成的任务标记为失败）。

### 查看日志

```bash
docker compose logs -f pdf2zh-web
```

## License

AGPL-3.0
