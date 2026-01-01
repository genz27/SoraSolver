# Cloudflare Solver

自动解决 Cloudflare Turnstile Challenge，获取 cf_clearance cookie。

搭配 [sora2api](https://github.com/TheSmallHanCat/sora2api) 使用。

## 特性

- 并发处理，支持多请求并行
- 结果缓存，30 分钟内复用
- 浏览器池预热，减少冷启动
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

| 参数 | 说明 | 默认值 |
|------|------|--------|
| url | 目标 URL | https://sora.chatgpt.com |
| proxy | 代理地址 | 无 |
| timeout | 超时秒数 | 60 |
| skip_cache | 跳过缓存 | false |

```bash
curl "http://localhost:8005/v1/challenge"

# 使用 API Key（开启验证时）
curl -H "X-API-Key: your-key" "http://localhost:8005/v1/challenge"
```

### API Key 验证

默认关闭。在管理后台将 `require_api_key` 设为 `1` 开启。

开启后请求需携带 Key：
- 请求头: `X-API-Key: your-key`
- 或查询参数: `?api_key=your-key`

不设置密码时可随便填或留空。

## 性能配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| max_workers | 并发浏览器数 | 3 |
| pool_size | 预热浏览器数 | 2 |
| semaphore_limit | 并发请求限制 | 3 |
| cache_ttl | 缓存过期时间(秒) | 1800 |

可通过管理后台或环境变量修改。

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
