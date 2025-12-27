# Cloudflare Solver

自动解决 Cloudflare Turnstile Challenge，获取 cf_clearance cookie。

## 部署

```bash
docker-compose up -d
```

## API

**GET** `/v1/challenge`

| 参数 | 说明 | 默认值 |
|------|------|--------|
| url | 目标 URL | https://sora.chatgpt.com |
| proxy | 代理地址 | 无 |
| timeout | 超时秒数 | 60 |
| headless | 无头模式 | true |

```bash
# 无代理
curl "http://localhost:8000/v1/challenge"

# 使用代理
curl "http://localhost:8000/v1/challenge?proxy=http://user:pass@ip:port"
```

**返回:**
```json
{
    "success": true,
    "cf_clearance": "xxx",
    "cookies": {"cf_clearance": "xxx", "__cf_bm": "xxx"},
    "user_agent": "Mozilla/5.0...",
    "elapsed_seconds": 10.5,
    "request_id": "abc123"
}
```

## 代理池

在 `data/proxy.txt` 中配置代理列表，每行一个：

```
# 支持格式
http://ip:port
http://user:pass@ip:port
socks5://ip:port
ip:port
ip:port:user:pass
```

启用代理池后，每次请求轮询使用下一个代理。
