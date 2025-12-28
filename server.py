"""
Cloudflare Challenge API Server

提供 /v1/challenge 接口，支持并发处理和结果缓存
优化版本：浏览器池 + 结果缓存 + 并发控制 + 性能监控
"""
import time
import uuid
import asyncio
import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from cloudflare_solver import (
    CloudflareSolver, CloudflareError,
    init_browser_pool, get_browser_pool, get_cache
)

# 配置
MAX_WORKERS = 3  # 并发浏览器数量
POOL_SIZE = 2    # 预热浏览器池大小
SEMAPHORE_LIMIT = 3  # 并发请求限制

# 并发控制
request_semaphore: Optional[asyncio.Semaphore] = None
executor: Optional[ThreadPoolExecutor] = None

# 统计信息
stats = {
    "total_requests": 0,
    "success": 0,
    "failed": 0,
    "cache_hits": 0,
    "avg_time": 0.0,
    "total_time": 0.0,
    "queue_waiting": 0,
    "processing": 0,
    "start_time": None
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global request_semaphore, executor
    
    # 启动时初始化
    print("🚀 初始化服务...")
    stats["start_time"] = time.time()
    
    # 初始化并发控制
    request_semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    
    # 初始化浏览器池（后台预热）
    try:
        init_browser_pool(pool_size=POOL_SIZE, headless=True, warmup=True)
    except Exception as e:
        print(f"⚠️ 浏览器池初始化失败: {e}")
    
    print("✅ 服务就绪")
    
    yield
    
    # 关闭时清理
    print("🛑 关闭服务...")
    if executor:
        executor.shutdown(wait=False)
    pool = get_browser_pool()
    if pool:
        pool.shutdown()
    print("✅ 服务已关闭")


app = FastAPI(
    title="Cloudflare Challenge API",
    description="自动解决 Cloudflare Turnstile Challenge，获取 cf_clearance cookie（优化版）",
    version="2.0.0",
    lifespan=lifespan
)


class ChallengeResponse(BaseModel):
    """Challenge 响应模型"""
    success: bool
    cf_clearance: str
    cookies: dict
    user_agent: str
    elapsed_seconds: float
    request_id: str
    from_cache: bool = False


class ErrorResponse(BaseModel):
    """错误响应模型"""
    success: bool = False
    error: str
    request_id: str


class StatsResponse(BaseModel):
    """统计响应模型"""
    total_requests: int
    success: int
    failed: int
    success_rate: str
    cache_hits: int
    avg_time: float
    uptime_seconds: float
    queue_waiting: int
    processing: int
    cache_stats: dict
    pool_stats: Optional[dict]


def get_index_html(host: str = "localhost:8000") -> str:
    return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cloudflare Solver API v2</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }}
        .container {{ background: white; border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); max-width: 700px; width: 100%; padding: 40px; }}
        h1 {{ color: #333; margin-bottom: 10px; font-size: 28px; }}
        .subtitle {{ color: #666; margin-bottom: 30px; }}
        .version {{ background: #667eea; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-left: 10px; }}
        .status {{ display: flex; align-items: center; gap: 10px; padding: 15px; background: #d4edda; border-radius: 8px; margin-bottom: 15px; }}
        .status-dot {{ width: 12px; height: 12px; background: #28a745; border-radius: 50%; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 25px; }}
        .stat-item {{ text-align: center; padding: 15px; background: #f8f9fa; border-radius: 8px; }}
        .stat-number {{ font-size: 24px; font-weight: 700; color: #333; }}
        .stat-number.success {{ color: #28a745; }}
        .stat-number.processing {{ color: #0066cc; }}
        .stat-number.cache {{ color: #fd7e14; }}
        .stat-label {{ font-size: 12px; color: #666; margin-top: 4px; }}
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
        <h1>🛡️ Cloudflare Solver API <span class="version">v2.0</span></h1>
        <p class="subtitle">自动解决 Cloudflare Turnstile Challenge（优化版）</p>
        
        <div class="status">
            <div class="status-dot"></div>
            <span style="color: #155724; font-weight: 500;">服务运行中</span>
        </div>
        
        <div class="stats-grid">
            <div class="stat-item">
                <div class="stat-number" id="total">-</div>
                <div class="stat-label">总请求</div>
            </div>
            <div class="stat-item">
                <div class="stat-number success" id="success-rate">-</div>
                <div class="stat-label">成功率</div>
            </div>
            <div class="stat-item">
                <div class="stat-number processing" id="processing">-</div>
                <div class="stat-label">处理中</div>
            </div>
            <div class="stat-item">
                <div class="stat-number cache" id="cache-rate">-</div>
                <div class="stat-label">缓存命中</div>
            </div>
        </div>
        
        <div class="endpoint">
            <div class="endpoint-title">
                <span class="method">GET</span>
                <span>/v1/challenge</span>
            </div>
            <div class="endpoint-url">解决 Cloudflare challenge，获取 cf_clearance cookie</div>
            <div class="endpoint-desc">
                参数: url, proxy, timeout, headless, skip_cache
            </div>
        </div>
        
        <div class="endpoint">
            <div class="endpoint-title">
                <span class="method">GET</span>
                <span>/v1/stats</span>
            </div>
            <div class="endpoint-url">获取服务统计信息</div>
        </div>
        
        <div class="endpoint">
            <div class="endpoint-title">
                <span class="method">POST</span>
                <span>/v1/cache/clear</span>
            </div>
            <div class="endpoint-url">清空结果缓存</div>
        </div>
        
        <div class="example">
            <div class="example-title">使用示例</div>
            <code>curl "http://{host}/v1/challenge?url=https://example.com"</code>
        </div>
        
        <div class="links">
            <a href="/docs">📚 API 文档</a>
            <a href="/v1/stats">📊 统计信息</a>
            <a href="/health">💚 健康检查</a>
        </div>
    </div>
    
    <script>
        function updateStats() {{
            fetch('/v1/stats')
                .then(r => r.json())
                .then(data => {{
                    document.getElementById('total').textContent = data.total_requests;
                    document.getElementById('success-rate').textContent = data.success_rate;
                    document.getElementById('processing').textContent = data.processing + '/' + data.queue_waiting;
                    document.getElementById('cache-rate').textContent = data.cache_stats.hit_rate;
                }})
                .catch(() => {{}});
        }}
        updateStats();
        setInterval(updateStats, 3000);
    </script>
</body>
</html>
"""


@app.get("/v1/stats", response_model=StatsResponse)
async def get_stats():
    """获取服务统计信息"""
    cache = get_cache()
    pool = get_browser_pool()
    
    total = stats["total_requests"]
    success_rate = f"{stats['success'] / total * 100:.1f}%" if total > 0 else "0%"
    uptime = time.time() - stats["start_time"] if stats["start_time"] else 0
    
    return StatsResponse(
        total_requests=total,
        success=stats["success"],
        failed=stats["failed"],
        success_rate=success_rate,
        cache_hits=stats["cache_hits"],
        avg_time=round(stats["avg_time"], 2),
        uptime_seconds=round(uptime, 0),
        queue_waiting=stats["queue_waiting"],
        processing=stats["processing"],
        cache_stats=cache.stats(),
        pool_stats=pool.stats() if pool else None
    )


@app.post("/v1/cache/clear")
async def clear_cache():
    """清空结果缓存"""
    cache = get_cache()
    old_stats = cache.stats()
    cache.clear()
    return {"success": True, "cleared": old_stats["size"]}


@app.get("/v1/challenge", response_model=ChallengeResponse, responses={
    500: {"model": ErrorResponse, "description": "Challenge 解决失败"},
    503: {"model": ErrorResponse, "description": "服务繁忙"}
})
async def solve_challenge(
    url: str = Query(default="https://sora.chatgpt.com", description="目标 URL"),
    proxy: Optional[str] = Query(default=None, description="代理地址 (ip:port 或 http://ip:port)"),
    timeout: int = Query(default=60, ge=10, le=300, description="超时时间（秒）"),
    headless: bool = Query(default=True, description="是否无头模式"),
    skip_cache: bool = Query(default=False, description="跳过缓存，强制获取新 cookie")
):
    """
    解决 Cloudflare Turnstile Challenge（并发模式）
    
    支持并发处理，自动缓存结果（30分钟有效期）
    """
    request_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    from_cache = False
    
    # 更新统计
    stats["total_requests"] += 1
    stats["queue_waiting"] += 1
    
    print(f"[{request_id}] 📥 请求进入，等待: {stats['queue_waiting']}, 处理中: {stats['processing']}")
    
    try:
        # 获取信号量 - 控制并发
        async with request_semaphore:
            stats["queue_waiting"] -= 1
            stats["processing"] += 1
            
            print(f"[{request_id}] 🚀 开始处理 | URL: {url} | Proxy: {proxy or '无'}")
            
            # 先检查缓存
            if not skip_cache:
                cache = get_cache()
                cached = cache.get(url, proxy)
                if cached:
                    elapsed = time.time() - start_time
                    stats["success"] += 1
                    stats["cache_hits"] += 1
                    print(f"[{request_id}] 📦 缓存命中，耗时 {elapsed:.2f}s")
                    
                    return ChallengeResponse(
                        success=True,
                        cf_clearance=cached.cf_clearance,
                        cookies=cached.cookies,
                        user_agent=cached.user_agent,
                        elapsed_seconds=round(elapsed, 2),
                        request_id=request_id,
                        from_cache=True
                    )
            
            solver = CloudflareSolver(
                proxy=proxy,
                headless=headless,
                timeout=timeout,
                use_cache=True,
                use_pool=True
            )
            
            try:
                loop = asyncio.get_event_loop()
                solution = await loop.run_in_executor(
                    executor, 
                    lambda: solver.solve(url, skip_cache=skip_cache)
                )
                
                elapsed = time.time() - start_time
                
                # 更新统计
                stats["success"] += 1
                stats["total_time"] += elapsed
                stats["avg_time"] = stats["total_time"] / stats["success"]
                
                print(f"[{request_id}] ✅ 成功，耗时 {elapsed:.2f}s")
                
                return ChallengeResponse(
                    success=True,
                    cf_clearance=solution.cf_clearance,
                    cookies=solution.cookies,
                    user_agent=solution.user_agent,
                    elapsed_seconds=round(elapsed, 2),
                    request_id=request_id,
                    from_cache=from_cache
                )
                
            except CloudflareError as e:
                elapsed = time.time() - start_time
                stats["failed"] += 1
                print(f"[{request_id}] ❌ 失败: {e}")
                
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
                stats["failed"] += 1
                print(f"[{request_id}] ❌ 错误: {e}")
                
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
                stats["processing"] -= 1
                
    except asyncio.CancelledError:
        stats["queue_waiting"] -= 1
        print(f"[{request_id}] ⚠️ 请求被取消")
        raise


# 兼容旧接口
@app.get("/v1/queue")
async def get_queue_status():
    """获取当前队列状态（兼容旧接口）"""
    return {
        "waiting": stats["queue_waiting"],
        "processing": stats["processing"]
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    pool = get_browser_pool()
    return {
        "status": "ok",
        "service": "cloudflare-challenge-api",
        "version": "2.0.0",
        "pool_available": pool.stats()["available"] if pool else 0
    }


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """首页"""
    host = request.headers.get("host", "localhost:8000")
    return get_index_html(host)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
