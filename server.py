"""
Cloudflare Challenge API Server

提供 /v1/challenge 接口，每次请求都会启动浏览器获取新的 cf_clearance
串行处理模式：一次只处理一个请求，其他请求排队等待
"""
import time
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from cloudflare_solver import CloudflareSolver, CloudflareError

# 串行锁 - 确保同一时间只有一个请求在处理
request_lock = asyncio.Lock()
# 单线程执行器 - 运行同步的浏览器代码
executor = ThreadPoolExecutor(max_workers=1)
# 当前队列状态
queue_status = {"waiting": 0, "processing": False}

app = FastAPI(
    title="Cloudflare Challenge API",
    description="自动解决 Cloudflare Turnstile Challenge，获取 cf_clearance cookie",
    version="1.0.0"
)


class ChallengeResponse(BaseModel):
    """Challenge 响应模型"""
    success: bool
    cf_clearance: str
    cookies: dict
    user_agent: str
    elapsed_seconds: float
    request_id: str


class ErrorResponse(BaseModel):
    """错误响应模型"""
    success: bool = False
    error: str
    request_id: str


# 首页 HTML 模板函数
def get_index_html(host: str = "localhost:8000") -> str:
    return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cloudflare Solver API</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }}
        .container {{ background: white; border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); max-width: 600px; width: 100%; padding: 40px; }}
        h1 {{ color: #333; margin-bottom: 10px; font-size: 28px; }}
        .subtitle {{ color: #666; margin-bottom: 30px; }}
        .status {{ display: flex; align-items: center; gap: 10px; padding: 15px; background: #d4edda; border-radius: 8px; margin-bottom: 15px; }}
        .status-dot {{ width: 12px; height: 12px; background: #28a745; border-radius: 50%; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .queue-status {{ padding: 15px; background: #e7f3ff; border-radius: 8px; margin-bottom: 25px; display: flex; justify-content: space-between; align-items: center; }}
        .queue-item {{ text-align: center; }}
        .queue-number {{ font-size: 24px; font-weight: 700; color: #0066cc; }}
        .queue-label {{ font-size: 12px; color: #666; margin-top: 4px; }}
        .processing {{ color: #28a745 !important; }}
        .endpoint {{ background: #f8f9fa; border-radius: 8px; padding: 20px; margin-bottom: 15px; }}
        .endpoint-title {{ font-weight: 600; color: #333; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }}
        .method {{ background: #28a745; color: white; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
        .endpoint-url {{ font-family: monospace; color: #6c757d; font-size: 14px; }}
        .endpoint-desc {{ color: #666; font-size: 14px; margin-top: 8px; }}
        .example {{ background: #2d3748; color: #e2e8f0; border-radius: 8px; padding: 15px; margin-top: 25px; overflow-x: auto; }}
        .example-title {{ color: #a0aec0; font-size: 12px; margin-bottom: 10px; }}
        .example code {{ font-family: 'Monaco', 'Menlo', monospace; font-size: 13px; line-height: 1.6; }}
        .links {{ margin-top: 25px; display: flex; gap: 15px; }}
        .links a {{ color: #667eea; text-decoration: none; font-weight: 500; }}
        .links a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ Cloudflare Solver API</h1>
        <p class="subtitle">自动解决 Cloudflare Turnstile Challenge</p>
        
        <div class="status">
            <div class="status-dot"></div>
            <span style="color: #155724; font-weight: 500;">服务运行中</span>
        </div>
        
        <div class="queue-status">
            <div class="queue-item">
                <div class="queue-number" id="waiting">-</div>
                <div class="queue-label">排队等待</div>
            </div>
            <div class="queue-item">
                <div class="queue-number processing" id="processing">-</div>
                <div class="queue-label">正在处理</div>
            </div>
        </div>
        
        <div class="endpoint">
            <div class="endpoint-title">
                <span class="method">GET</span>
                <span>/v1/challenge</span>
            </div>
            <div class="endpoint-url">解决 Cloudflare challenge，获取 cf_clearance cookie</div>
            <div class="endpoint-desc">
                参数: url (目标URL), proxy (代理), timeout (超时), headless (无头模式)
            </div>
        </div>
        
        <div class="endpoint">
            <div class="endpoint-title">
                <span class="method">GET</span>
                <span>/v1/queue</span>
            </div>
            <div class="endpoint-url">获取当前队列状态</div>
        </div>
        
        <div class="endpoint">
            <div class="endpoint-title">
                <span class="method">GET</span>
                <span>/health</span>
            </div>
            <div class="endpoint-url">健康检查接口</div>
        </div>
        
        <div class="example">
            <div class="example-title">使用示例</div>
            <code>curl "http://{host}/v1/challenge"</code>
        </div>
        
        <div class="links">
            <a href="/docs">📚 API 文档</a>
            <a href="/health">💚 健康检查</a>
            <a href="https://github.com/genz27/SoraSolver" target="_blank">📦 GitHub</a>
        </div>
    </div>
    
    <script>
        function updateQueue() {{
            fetch('/v1/queue')
                .then(r => r.json())
                .then(data => {{
                    document.getElementById('waiting').textContent = data.waiting;
                    document.getElementById('processing').textContent = data.processing ? '1' : '0';
                }})
                .catch(() => {{}});
        }}
        updateQueue();
        setInterval(updateQueue, 2000);
    </script>
</body>
</html>
"""


@app.get("/v1/queue")
async def get_queue_status():
    """获取当前队列状态"""
    return {
        "waiting": queue_status["waiting"],
        "processing": queue_status["processing"]
    }


@app.get("/v1/challenge", response_model=ChallengeResponse, responses={
    500: {"model": ErrorResponse, "description": "Challenge 解决失败"}
})
async def solve_challenge(
    url: str = Query(default="https://sora.chatgpt.com", description="目标 URL"),
    proxy: Optional[str] = Query(default=None, description="代理地址 (ip:port 或 http://ip:port)"),
    timeout: int = Query(default=60, ge=10, le=300, description="超时时间（秒）"),
    headless: bool = Query(default=True, description="是否无头模式")
):
    """
    解决 Cloudflare Turnstile Challenge（串行排队模式）
    
    每次请求都会启动新的浏览器实例，获取全新的 cf_clearance cookie。
    请求按顺序排队处理，同一时间只有一个请求在执行。
    
    - **url**: 目标网站 URL（默认 sora.chatgpt.com）
    - **proxy**: 代理地址，格式 ip:port 或 http://ip:port
    - **timeout**: 等待验证超时时间（10-300秒）
    - **headless**: 是否使用无头模式（默认 True）
    """
    request_id = str(uuid.uuid4())[:8]
    
    # 进入排队
    queue_status["waiting"] += 1
    queue_position = queue_status["waiting"]
    print(f"[{request_id}] 📥 请求进入队列，当前排队: {queue_position}")
    
    try:
        # 获取锁 - 串行处理
        async with request_lock:
            queue_status["waiting"] -= 1
            queue_status["processing"] = True
            
            start_time = time.time()
            print(f"[{request_id}] 🚀 开始解决 Cloudflare challenge")
            print(f"[{request_id}]    URL: {url}")
            print(f"[{request_id}]    Proxy: {proxy or '无'}")
            print(f"[{request_id}]    Headless: {headless}")
            
            solver = CloudflareSolver(
                proxy=proxy,
                headless=headless,
                timeout=timeout
            )
            
            try:
                # 在线程池中运行同步代码，避免阻塞事件循环
                loop = asyncio.get_event_loop()
                solution = await loop.run_in_executor(executor, lambda: solver.solve(url))
                elapsed = time.time() - start_time
                
                print(f"[{request_id}] ✅ Challenge 解决成功，耗时 {elapsed:.2f}s")
                
                return ChallengeResponse(
                    success=True,
                    cf_clearance=solution.cf_clearance,
                    cookies=solution.cookies,
                    user_agent=solution.user_agent,
                    elapsed_seconds=round(elapsed, 2),
                    request_id=request_id
                )
                
            except CloudflareError as e:
                elapsed = time.time() - start_time
                print(f"[{request_id}] ❌ Challenge 解决失败: {e}")
                
                raise HTTPException(
                    status_code=500,
                    detail={
                        "success": False,
                        "error": str(e),
                        "request_id": request_id,
                        "elapsed_seconds": round(elapsed, 2)
                    }
                )
            except Exception as e:
                elapsed = time.time() - start_time
                print(f"[{request_id}] ❌ 未知错误: {e}")
                
                raise HTTPException(
                    status_code=500,
                    detail={
                        "success": False,
                        "error": f"Internal error: {str(e)}",
                        "request_id": request_id,
                        "elapsed_seconds": round(elapsed, 2)
                    }
                )
            finally:
                queue_status["processing"] = False
    except asyncio.CancelledError:
        queue_status["waiting"] -= 1
        print(f"[{request_id}] ⚠️ 请求被取消")
        raise


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "cloudflare-challenge-api"}


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """首页"""
    host = request.headers.get("host", "localhost:8000")
    return get_index_html(host)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
