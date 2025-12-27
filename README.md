# Cloudflare Turnstile Challenge Solver

使用 DrissionPage 自动解决 Cloudflare Turnstile Challenge，获取 `cf_clearance` cookie。

## 安装

```bash
pip install -r requirements.txt
```

## API 服务

### 启动服务

```bash
python server.py
```

服务默认运行在 `http://localhost:8000`

### API 接口

#### GET /v1/challenge

解决 Cloudflare challenge，每次请求都会启动新浏览器获取全新的 cookie。

**参数：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| url | string | https://sora.chatgpt.com | 目标 URL |
| proxy | string | 无 | 代理地址 (ip:port) |
| timeout | int | 60 | 超时时间（秒） |
| headless | bool | true | 是否无头模式 |

**请求示例：**
```bash
# 基本请求
curl "http://localhost:8000/v1/challenge"

# 使用代理
curl "http://localhost:8000/v1/challenge?proxy=127.0.0.1:7897"

# 完整参数
curl "http://localhost:8000/v1/challenge?url=https://sora.chatgpt.com&proxy=127.0.0.1:7897&timeout=60&headless=true"
```

**响应示例：**
```json
{
  "success": true,
  "cf_clearance": "7Tuxj1emDBod.7iGTddNEm5tSzzm3rvO_qONZHjczoM-1766818023-1.2.1.1-...",
  "cookies": {
    "cf_clearance": "7Tuxj1emDBod...",
    "__cf_bm": "NwnQUekk13O1...",
    "_cfuvid": "otCL9nbM5oqQ..."
  },
  "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...",
  "elapsed_seconds": 5.23,
  "request_id": "a1b2c3d4"
}
```

**错误响应：**
```json
{
  "success": false,
  "error": "等待 Cloudflare 验证超时 (60s)",
  "request_id": "a1b2c3d4",
  "elapsed_seconds": 60.12
}
```

### 在代码中使用

```python
import requests

# 获取 Cloudflare cookie
response = requests.get(
    "http://localhost:8000/v1/challenge",
    params={"proxy": "127.0.0.1:7897"}
)
data = response.json()

if data["success"]:
    # 使用获取到的 cookie 访问目标网站
    headers = {"User-Agent": data["user_agent"]}
    cookies = data["cookies"]
    
    result = requests.get(
        "https://sora.chatgpt.com/backend/me",
        headers=headers,
        cookies=cookies
    )
```

## 使用方法

### 命令行

```bash
# 基本用法（默认解决 sora.chatgpt.com）
python cloudflare_solver.py

# 指定 URL
python cloudflare_solver.py https://example.com

# 使用代理
python cloudflare_solver.py -p 127.0.0.1:7897

# 显示浏览器窗口（调试用）
python cloudflare_solver.py --no-headless

# 输出到 JSON 文件
python cloudflare_solver.py -o cookies.json

# 完整示例
python cloudflare_solver.py https://sora.chatgpt.com -p 127.0.0.1:7897 --no-headless -o cookies.json
```

### Python 代码

```python
from cloudflare_solver import CloudflareSolver, CloudflareError

solver = CloudflareSolver(
    proxy="127.0.0.1:7897",  # 可选
    headless=True,           # 无头模式
    timeout=60               # 超时时间
)

try:
    solution = solver.solve("https://sora.chatgpt.com")
    
    print(f"cf_clearance: {solution.cf_clearance}")
    print(f"user_agent: {solution.user_agent}")
    print(f"cookies: {solution.cookies}")
    
    # 在请求中使用
    import requests
    response = requests.get(
        "https://sora.chatgpt.com/backend/me",
        cookies=solution.cookies,
        headers={"User-Agent": solution.user_agent}
    )
    
except CloudflareError as e:
    print(f"解决失败: {e}")
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `url` | 目标 URL | `https://sora.chatgpt.com` |
| `-p, --proxy` | 代理地址 (ip:port) | 无 |
| `--headless` | 无头模式 | True |
| `--no-headless` | 显示浏览器窗口 | False |
| `-t, --timeout` | 超时时间（秒） | 60 |
| `-o, --output` | 输出 JSON 文件路径 | 无 |

## 输出示例

```
==================================================
Cloudflare Turnstile Challenge Solver
==================================================
目标 URL: https://sora.chatgpt.com
代理: 127.0.0.1:7897
无头模式: False
超时: 60s
==================================================
🌐 正在访问: https://sora.chatgpt.com
⏳ 等待 Cloudflare 验证中... (2.1s)
✅ Cloudflare 验证通过，耗时 5.3s

==================================================
✅ Challenge solved successfully!
==================================================
cf_clearance: Bcg6jNLzTVaa3IsFhtDI.e4_LX8p7q7zFYHF7wiHPo...
user_agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...

Cookies (3):
  cf_clearance: Bcg6jNLzTVaa3IsFhtDI.e4_LX8p7q7zFYHF7wiHPo...
  __cf_bm: NwnQUekk13O1FYsAlP1whm9NQF8pFVSLSudfpD_59l0...
  _cfuvid: otCL9nbM5oqQxPwHnWGBFKjDUJeUTdlsfvGQjmK86fA...

📋 Cookie 字符串 (可直接使用):
cf_clearance=Bcg6jNLz...; __cf_bm=NwnQUekk...; _cfuvid=otCL9nbM...
```

## 注意事项

1. **代理要求**：建议使用静态代理或粘性代理，轮换代理可能导致验证失败
2. **IP 封禁**：如果代理 IP 被 Cloudflare 严重标记，即使浏览器也可能无法通过验证
3. **Cookie 有效期**：`cf_clearance` cookie 通常有效 30 分钟左右
4. **User-Agent**：使用获取到的 `user_agent` 发送后续请求，保持一致性

## Docker 部署

### 一句话部署

```bash
docker run -d --name sora-solver -p 8000:8000 --cap-add=SYS_ADMIN --security-opt seccomp=unconfined --shm-size=2g ghcr.io/genz27/sorasolver:latest
```

### 使用 docker-compose

```yaml
version: '3.8'
services:
  sora-solver:
    image: ghcr.io/genz27/sorasolver:latest
    ports:
      - "8000:8000"
    cap_add:
      - SYS_ADMIN
    security_opt:
      - seccomp=unconfined
    shm_size: '2gb'
    restart: unless-stopped
```

```bash
docker-compose up -d
```

### Docker 注意事项

- 需要 `--cap-add=SYS_ADMIN` 和 `--security-opt seccomp=unconfined` 权限运行 Chrome
- 需要 `--shm-size=2g` 共享内存，否则 Chrome 可能崩溃

```bash
# 使用
curl "http://localhost:8000/v1/challenge"
```
