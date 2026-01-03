"""
Cloudflare Challenge API Server
支持 API Key 验证 + SQLite 配置管理 + 后台管理
"""
import time
import uuid
import asyncio
import secrets
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request, Depends, Header
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 获取项目根目录
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
from cloudflare_solver import (
    CloudflareSolver, CloudflareError, get_cache
)
from config import init_db, config, api_keys, admins, proxy_pool, request_logger, ConfigManager

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

# 管理员 session
admin_sessions = {}


def get_config_int(key: str, default: int) -> int:
    """获取配置（优先环境变量）"""
    import os
    env_val = os.environ.get(key.upper())
    if env_val:
        return int(env_val)
    return config.get_int(key, default)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global request_semaphore, executor
    
    print("🚀 初始化服务...")
    
    # 初始化数据库
    init_db()
    
    stats["start_time"] = time.time()
    
    # 从配置加载参数
    max_workers = get_config_int("max_workers", 3)
    semaphore_limit = get_config_int("semaphore_limit", 3)
    
    print(f"   MAX_WORKERS={max_workers}, SEMAPHORE={semaphore_limit}")
    
    request_semaphore = asyncio.Semaphore(semaphore_limit)
    executor = ThreadPoolExecutor(max_workers=max_workers)
    
    print("✅ 服务就绪")
    
    yield
    
    print("🛑 关闭服务...")
    if executor:
        executor.shutdown(wait=False)


app = FastAPI(
    title="Cloudflare Challenge API",
    version="2.1.0",
    lifespan=lifespan
)


# ============ 模型 ============

class ChallengeResponse(BaseModel):
    success: bool
    cf_clearance: str
    cookies: dict
    user_agent: str
    elapsed_seconds: float
    request_id: str
    from_cache: bool = False


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    request_id: str


# ============ API Key 验证 ============

async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """验证 API Key"""
    if config.get("require_api_key", "0") != "1":
        return True
    
    key = x_api_key or api_key
    if not key or not api_keys.validate(key):
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True


# ============ 管理员验证 ============

async def verify_admin(authorization: str = Header(None)):
    """验证管理员 token"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    token = authorization[7:]
    if token not in admin_sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return admin_sessions[token]


# ============ 主要 API ============

@app.get("/v1/challenge", response_model=ChallengeResponse, dependencies=[Depends(verify_api_key)])
async def solve_challenge(
    url: str = Query(default="https://sora.chatgpt.com"),
    proxy: Optional[str] = Query(default=None),
    timeout: int = Query(default=60, ge=10, le=300),
    headless: bool = Query(default=True),
    skip_cache: bool = Query(default=False),
    max_retries: Optional[int] = Query(default=None, ge=0, le=10)
):
    """解决 Cloudflare Challenge"""
    request_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    
    stats["total_requests"] += 1
    stats["queue_waiting"] += 1
    
    # 如果启用代理池且没有指定代理，从代理池获取
    use_proxy = proxy
    if not use_proxy and config.get("proxy_pool_enabled", "0") == "1":
        use_proxy = proxy_pool.get_next_proxy()
        if use_proxy:
            print(f"  📡 使用代理池: {use_proxy}")
    
    try:
        async with request_semaphore:
            stats["queue_waiting"] -= 1
            stats["processing"] += 1
            
            # 检查缓存
            if not skip_cache:
                cache = get_cache()
                cached = cache.get(url, use_proxy)
                if cached:
                    elapsed = time.time() - start_time
                    stats["success"] += 1
                    stats["cache_hits"] += 1
                    # 记录日志
                    request_logger.log(request_id, url, use_proxy, True, None, elapsed, True)
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
                proxy=use_proxy,
                headless=headless,
                timeout=timeout,
                use_cache=True
            )
            
            # 获取重试次数配置
            retries = max_retries if max_retries is not None else get_config_int("max_retries", 0)
            
            try:
                loop = asyncio.get_event_loop()
                solution = await loop.run_in_executor(
                    executor,
                    lambda: solver.solve(url, skip_cache=skip_cache, max_retries=retries)
                )
                
                elapsed = time.time() - start_time
                stats["success"] += 1
                stats["total_time"] += elapsed
                stats["avg_time"] = stats["total_time"] / stats["success"]
                
                # 记录日志
                request_logger.log(request_id, url, use_proxy, True, None, elapsed, False)
                
                return ChallengeResponse(
                    success=True,
                    cf_clearance=solution.cf_clearance,
                    cookies=solution.cookies,
                    user_agent=solution.user_agent,
                    elapsed_seconds=round(elapsed, 2),
                    request_id=request_id,
                    from_cache=False
                )
                
            except CloudflareError as e:
                elapsed = time.time() - start_time
                stats["failed"] += 1
                # 记录日志
                request_logger.log(request_id, url, use_proxy, False, str(e), elapsed, False)
                raise HTTPException(status_code=500, detail={"success": False, "error": str(e), "request_id": request_id})
            except Exception as e:
                elapsed = time.time() - start_time
                stats["failed"] += 1
                request_logger.log(request_id, url, use_proxy, False, str(e), elapsed, False)
                raise HTTPException(status_code=500, detail={"success": False, "error": str(e), "request_id": request_id})
            finally:
                stats["processing"] -= 1
                
    except asyncio.CancelledError:
        stats["queue_waiting"] -= 1
        raise


@app.get("/v1/stats")
async def get_stats():
    """获取统计信息"""
    cache = get_cache()
    total = stats["total_requests"]
    
    return {
        "total_requests": total,
        "success": stats["success"],
        "failed": stats["failed"],
        "success_rate": f"{stats['success'] / total * 100:.1f}%" if total > 0 else "0%",
        "cache_hits": stats["cache_hits"],
        "avg_time": round(stats["avg_time"], 2),
        "uptime_seconds": round(time.time() - stats["start_time"], 0) if stats["start_time"] else 0,
        "queue_waiting": stats["queue_waiting"],
        "processing": stats["processing"],
        "cache_stats": cache.stats()
    }


@app.post("/v1/cache/clear")
async def clear_cache():
    """清空缓存"""
    cache = get_cache()
    old_size = cache.stats()["size"]
    cache.clear()
    return {"success": True, "cleared": old_size}


@app.get("/v1/queue")
async def get_queue_status():
    """队列状态"""
    return {"waiting": stats["queue_waiting"], "processing": stats["processing"]}


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "version": "2.1.0"
    }


# ============ 管理后台 API ============

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/login")
async def admin_login(req: LoginRequest):
    """管理员登录"""
    if admins.verify(req.username, req.password):
        token = secrets.token_urlsafe(32)
        admin_sessions[token] = req.username
        return {"success": True, "token": token}
    return {"success": False, "message": "用户名或密码错误"}


@app.get("/api/config", dependencies=[Depends(verify_admin)])
async def get_all_config():
    """获取所有配置"""
    return config.get_all()


@app.post("/api/config", dependencies=[Depends(verify_admin)])
async def update_config(data: dict):
    """更新配置"""
    for key, value in data.items():
        config.set(key, str(value))
    config.clear_cache()
    return {"success": True}


@app.get("/api/keys", dependencies=[Depends(verify_admin)])
async def list_api_keys():
    """列出 API Keys"""
    return api_keys.list_keys()


@app.post("/api/keys", dependencies=[Depends(verify_admin)])
async def add_api_key(data: dict):
    """添加 API Key"""
    key = api_keys.add_key(data.get("name"))
    return {"key": key}


@app.put("/api/keys/{key_id}", dependencies=[Depends(verify_admin)])
async def update_api_key(key_id: int, data: dict):
    """更新 API Key"""
    api_keys.toggle_key(key_id, data.get("enabled", True))
    return {"success": True}


@app.delete("/api/keys/{key_id}", dependencies=[Depends(verify_admin)])
async def delete_api_key(key_id: int):
    """删除 API Key"""
    api_keys.delete_key(key_id)
    return {"success": True}


@app.get("/api/stats", dependencies=[Depends(verify_admin)])
async def get_admin_stats():
    """管理后台统计"""
    cache = get_cache()
    total = stats["total_requests"]
    
    return {
        "total_requests": total,
        "success": stats["success"],
        "failed": stats["failed"],
        "success_rate": f"{stats['success'] / total * 100:.1f}%" if total > 0 else "0%",
        "cache_hits": stats["cache_hits"],
        "avg_time": round(stats["avg_time"], 2),
        "uptime_seconds": round(time.time() - stats["start_time"], 0) if stats["start_time"] else 0,
        "cache_stats": cache.stats()
    }


@app.post("/api/password", dependencies=[Depends(verify_admin)])
async def change_admin_password(data: dict, username: str = Depends(verify_admin)):
    """修改密码"""
    admins.change_password(username, data["password"])
    return {"success": True}


# ============ 日志 API ============

@app.get("/api/logs", dependencies=[Depends(verify_admin)])
async def get_logs(limit: int = 100):
    """获取请求日志"""
    return request_logger.get_logs(limit)


@app.delete("/api/logs", dependencies=[Depends(verify_admin)])
async def clear_logs():
    """清空日志"""
    request_logger.clear_logs()
    return {"success": True}


# ============ 静态页面 ============

@app.get("/", response_class=HTMLResponse)
async def index():
    """首页"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """管理后台"""
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """登录页"""
    return FileResponse(STATIC_DIR / "login.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
