# Cloudflare Solver

自动解决 Cloudflare Turnstile Challenge，获取 cf_clearance cookie。

## 部署

```bash
docker-compose up -d
```

## API

**GET** `/v1/challenge`

```bash
curl "http://localhost:8000/v1/challenge?url=https://sora.chatgpt.com"
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
