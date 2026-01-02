# Cloudflare Solver

自动解决 Cloudflare Turnstile Challenge，获取 cf_clearance cookie。

搭配 [sora2api](https://github.com/TheSmallHanCat/sora2api) 使用。

## 特性

- 无头模式运行，适合服务器部署
- 自动重试机制，遇到人机验证自动重启浏览器
- 结果缓存，30 分钟内复用
- 后台管理，可视化配置

## 部署

一句话部署：
```bash
docker run -d --name cloudflare-solver -p 8005:8005 --shm-size=2g -v ./data:/app/data ghcr.io/genz27/sorasolver:latest
```

或使用 docker-compose：
```bash
docker-compose up -d
```

访问：
- 首页: http://localhost:8005
- 管理后台: http://localhost:8005/admin
- API 文档: http://localhost:8005/docs

## 管理后台

默认账号: `admin` / `admin123`

可管理：
- 系统配置（并发数、缓存时间等）
- API Key（添加/删除/启用/禁用）
- 修改管理员密码

## API

### GET `/v1/challenge`

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| url | string | 目标 URL | https://sora.chatgpt.com |
| proxy | string | 代理地址，格式: `http://host:port` 或 `socks5://host:port` | 无 |
| timeout | int | 超时秒数，范围 10-300 | 60 |
| skip_cache | bool | 是否跳过缓存，设为 `true` 强制重新获取 | false |

```bash
# 基本请求（使用缓存）
curl "http://localhost:8005/v1/challenge"

# 强制跳过缓存，重新获取
curl "http://localhost:8005/v1/challenge?skip_cache=true"

# 指定目标 URL 和代理
curl "http://localhost:8005/v1/challenge?url=https://example.com&proxy=http://127.0.0.1:7890"

# 使用 API Key（开启验证时）
curl -H "X-API-Key: your-key" "http://localhost:8005/v1/challenge"
```

响应示例：
```json
{
  "success": true,
  "cf_clearance": "xxx",
  "cookies": {"cf_clearance": "xxx", ...},
  "user_agent": "Mozilla/5.0 ...",
  "elapsed_seconds": 12.34,
  "request_id": "abc12345",
  "from_cache": false
}
```

`from_cache` 字段表示结果是否来自缓存。

### API Key 验证

默认关闭。在管理后台将 `require_api_key` 设为 `1` 开启。

开启后请求需携带 Key：
- 请求头: `X-API-Key: your-key`
- 或查询参数: `?api_key=your-key`

不设置密码时可随便填或留空。

## 性能配置

| 配置项 | 说明 | 默认值 | 环境变量 |
|--------|------|--------|----------|
| max_workers | 并发浏览器数，同时运行的浏览器实例数量 | 3 | MAX_WORKERS |
| pool_size | 预热浏览器数，启动时预先创建的浏览器数量 | 2 | POOL_SIZE |
| semaphore_limit | 并发请求限制，同时处理的请求数量 | 3 | SEMAPHORE_LIMIT |
| cache_ttl | 缓存过期时间(秒)，cf_clearance 的缓存有效期 | 1800 | CACHE_TTL |
| require_api_key | 是否启用 API Key 验证，`1` 启用 `0` 禁用 | 0 | - |

可通过管理后台或环境变量修改。环境变量优先级高于数据库配置。

```yaml
# docker-compose.yml 示例
environment:
  - MAX_WORKERS=5
  - POOL_SIZE=3
  - SEMAPHORE_LIMIT=5
  - CACHE_TTL=3600
```

## 资源需求

| 内存 | 建议并发 |
|------|----------|
| 2G | 2-3 |
| 4G | 3-5 |
| 8G | 5-8 |

Docker 必须设置 `shm_size: 2gb`，否则 Chrome 会崩溃。

## 数据持久化

```yaml
volumes:
  - ./data:/app/data  # 配置数据库
```

## 工作原理

1. 使用无头 Chrome 浏览器访问目标页面
2. 等待 Cloudflare 验证自动通过
3. 如果遇到人机验证（需要点击），自动关闭浏览器并重新打开重试
4. 最多重试 5 次
5. 成功后返回 cf_clearance cookie
