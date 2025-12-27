"""
Cloudflare Challenge API Server

提供 /v1/challenge 接口，每次请求都会启动浏览器获取新的 cf_clearance
"""
import time
import uuid
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from cloudflare_solver import CloudflareSolver, CloudflareError

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
    解决 Cloudflare Turnstile Challenge
    
    每次请求都会启动新的浏览器实例，获取全新的 cf_clearance cookie。
    不使用缓存，保证每次返回的值都是最新获取的。
    
    - **url**: 目标网站 URL（默认 sora.chatgpt.com）
    - **proxy**: 代理地址，格式 ip:port 或 http://ip:port
    - **timeout**: 等待验证超时时间（10-300秒）
    - **headless**: 是否使用无头模式（默认 True）
    """
    request_id = str(uuid.uuid4())[:8]
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
        solution = solver.solve(url)
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


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "cloudflare-challenge-api"}


@app.get("/")
async def root():
    """API 信息"""
    return {
        "name": "Cloudflare Challenge API",
        "version": "1.0.0",
        "endpoints": {
            "/v1/challenge": "GET - 解决 Cloudflare challenge",
            "/health": "GET - 健康检查",
            "/docs": "GET - API 文档"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
