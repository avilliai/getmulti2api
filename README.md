# Multi AI 2API Gateway

针对 **https://web.getmulti.ai** 开发的自动化注册 (Register) 与 OpenAI 兼容 API 转换网关 (2API)。

---

## 🌟 核心特性

1. **双通道自动注册 (Multi-Channel Registration)**：
   - **Cloudflare 临时域名邮箱**。
   - **Outlook 邮箱池**
   - **虚拟/随机邮箱**：支持直连快速生成测试。

2. **Firebase Auth 原生对接 & 永久免死机制**：
   - 逆向分析 `web.getmulti.ai` 前端认证机制，采用原生 Firebase Auth REST 注册流程并调用 `/api/auth/register` 获取 `multi_auth` 会话凭据。
   - 完整保存每个账号的 `refresh_token`，在 `id_token`（1小时有效期）即将到期前**全自动异步静默刷新**，账号永不过期。

3. **标准 OpenAI 格式 2API 服务**：
   - `POST /v1/chat/completions`：完全兼容 OpenAI 协议。
   - **流式 SSE 深度支持**：支持 `stream: true`，原生透传输出推理思考过程 (`reasoning_content`) 与正文增量 (`content`)。
   - **非流式输出支持**：支持 `stream: false`，全自动聚合流式分块并返回完整标准响应与 Token 统计。
   - `GET /v1/models`：动态同步 upstream 目录中 400+ 个模型及免费模型（如 `nvidia/nemotron-3-ultra-550b-a55b:free`、`google/gemma-4-26b-a4b-it:free` 等）。

4. **高可用账号池管理 (Account Pool Manager)**：
   - 多账号轮询调度（Round-Robin / LRU）。
   - 连续失败熔断、冷却重试 (Cooldown) 与健康恢复。
   - 池空自动扩容：当账号池耗尽时，全自动调用注册接口即时扩容。
   - 本地持久化：账号数据安全存储在 `data/accounts.json`。

5. **现代化可视化控制台 (Web Dashboard)**：
   - 访问根路径 `http://localhost:8000/` 即可进入可视化管理后台。
   - 实时监控账号池健康度、请求数、Token 消耗统计。
   - 支持一键在线选择渠道注册新账号、强制刷新 Token、删除账号。
   - 内置交互式对话测试器，可实时查看模型流式输出与思考过程。

---

## 📁 目录结构

```text
getmulti2api/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── admin.py            # 后台管理接口（账号池列表、状态监控、批处理）
│   │       ├── chat.py             # /v1/chat/completions 核心对话网关
│   │       ├── models.py           # /v1/models 模型列表
│   │       └── register.py         # /v1/register 账号自动化注册
│   ├── core/
│   │   ├── auth.py                 # API Key 鉴权中间件
│   │   ├── config.py               # 环境配置读取与验证
│   │   ├── dependencies.py         # 依赖注入
│   │   └── exceptions.py           # 异常定义
│   ├── services/
│   │   ├── account_manager.py      # 账号池管理器（轮询、健康检查、Token 刷新）
│   │   ├── cf_email_service.py     # Cloudflare 临时域名邮箱服务
│   │   ├── outlook_email_service.py# Outlook 有效账号池服务
│   │   ├── multi_client.py         # Upstream Multi AI 对话与模型客户端
│   │   └── multi_register.py       # Multi AI + Firebase 联合注册服务
│   ├── templates/
│   │   └── dashboard.html          # Web 控制台前端
│   └── main.py                     # FastAPI 应用入口
├── data/
│   ├── accounts.json               # 成功注册并活跃的账号池数据库
│   ├── outlook_valid_accounts.txt  # 从 Privatemodeai 提取的 317 个有效 Outlook 账号
│   └── outlook_pointer.json        # Outlook 账号分配指针记录
├── tests/
│   ├── verify_system.py            # 全流程功能验证脚本
│   └── test_fastapi_server.py      # FastAPI HTTP 接口自动化测试脚本
├── .env                            # 环境变量配置文件
├── .env.example                    # 环境变量模版
├── requirements.txt                # 运行依赖
├── run.py                          # 交互式启动脚本
└── main.py                         # 根目录启动入口
```

---

## ⚙️ 配置说明 (`.env`)

```ini
# 服务基础配置
HOST=0.0.0.0
PORT=8000
RELOAD=false
LOG_LEVEL=INFO

# API Key（留空则不开启鉴权；默认设为 changeme）
API_KEY=changeme

# Upstream Multi AI 配置
MULTI_BASE_URL=https://web.getmulti.ai
FIREBASE_API_KEY=AIzaSyDJ_v8StAeaFVcStQHiuXEWIBVk_3mAvB0
FIREBASE_PROJECT_ID=get-multi

# 账号池与运行控制
ACCOUNT_FILE=data/accounts.json
ACCOUNT_FAILURE_LIMIT=3
ACCOUNT_COOLDOWN_SECONDS=180
AUTO_REGISTER_ON_EMPTY=true
FREE_MODE=true
DEFAULT_MODEL=google/gemma-4-26b-a4b-it:free

# Cloudflare 临时域名邮箱配置
WORKER_DOMAIN=
EMAIL_DOMAIN=
ADMIN_PASSWORD=

# Outlook 账号池
OUTLOOK_ACCOUNT_FILE=data/outlook_valid_accounts.txt

# 可选网络代理（如无需代理请留空）
PROXY=
```

---

## 🚀 启动与运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python main.py
# 或者
python run.py
```

服务启动后：
- **Web 可视化控制台**：`http://localhost:8000/`
- **OpenAPI 交互式文档**：`http://localhost:8000/docs`
- **健康检查接口**：`http://localhost:8000/health`

---

## 🔌 API 调用示例

### 1. 对话补全 (`/v1/chat/completions`)

#### Python (标准 OpenAI SDK)：

```python
from openai import OpenAI

client = OpenAI(
    api_key="changeme",
    base_url="http://localhost:8000/v1"
)

response = client.chat.completions.create(
    model="nvidia/nemotron-3-ultra-550b-a55b:free",
    messages=[{"role": "user", "content": "你好，请介绍一下你自己。"}],
    stream=True
)

for chunk in response:
    content = chunk.choices[0].delta.content or ""
    print(content, end="", flush=True)
```

#### cURL：

```bash
curl -X POST "http://localhost:8000/v1/chat/completions" \
     -H "Authorization: Bearer changeme" \
     -H "Content-Type: application/json" \
     -d '{
       "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
       "messages": [{"role": "user", "content": "Hello!"}],
       "stream": false
     }'
```

### 2. 触发账号注册 (`/v1/register`)

```bash
# 通过 Cloudflare 临时邮箱注册
curl -X POST "http://localhost:8000/v1/register" \
     -H "Authorization: Bearer changeme" \
     -H "Content-Type: application/json" \
     -d '{"provider": "cf_mail"}'

# 通过 Outlook 有效账号池注册
curl -X POST "http://localhost:8000/v1/register" \
     -H "Authorization: Bearer changeme" \
     -H "Content-Type: application/json" \
     -d '{"provider": "outlook"}'
```

---

## 🧪 自动化测试验证

运行已通过的所有端到端测试：

```bash
python tests/verify_system.py
python tests/test_fastapi_server.py
```
