"""
Cloudflare Turnstile Challenge Solver using DrissionPage

独立项目，用于解决 Cloudflare 验证并获取 cf_clearance cookie
"""
import time
import json
import argparse
from typing import Optional, Dict
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CloudflareSolution:
    """Cloudflare challenge solution result"""
    cf_clearance: str
    cookies: Dict[str, str]
    user_agent: str
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        return {
            "cf_clearance": self.cf_clearance,
            "cookies": self.cookies,
            "user_agent": self.user_agent,
            "created_at": self.created_at.isoformat()
        }
    
    def is_expired(self, max_age_seconds: int = 1800) -> bool:
        """检查 cookie 是否过期（默认30分钟）"""
        age = (datetime.now() - self.created_at).total_seconds()
        return age > max_age_seconds


class CloudflareSolver:
    """
    Cloudflare Turnstile Challenge solver using DrissionPage.
    使用真实浏览器绕过 Cloudflare 检测。
    """
    
    def __init__(
        self,
        proxy: Optional[str] = None,
        headless: bool = True,
        timeout: int = 60
    ):
        """
        Initialize CloudflareSolver.
        
        Args:
            proxy: 代理地址，格式 "ip:port" 或 "http://ip:port"
            headless: 是否无头模式（默认 True）
            timeout: 等待 Cloudflare 验证超时时间（秒）
        """
        self.proxy = proxy
        self.headless = headless
        self.timeout = timeout
    
    def _create_page(self):
        """创建浏览器页面"""
        from DrissionPage import ChromiumPage, ChromiumOptions
        
        options = ChromiumOptions()
        
        # 设置代理
        if self.proxy:
            proxy_addr = self.proxy
            if not proxy_addr.startswith("http"):
                proxy_addr = f"http://{proxy_addr}"
            options.set_proxy(proxy_addr)
        
        # 无头模式
        if self.headless:
            options.headless()
        
        # 反检测设置
        options.set_argument("--disable-blink-features=AutomationControlled")
        options.set_argument("--no-sandbox")
        options.set_argument("--disable-dev-shm-usage")
        options.set_argument("--disable-gpu")
        
        return ChromiumPage(options)
    
    def solve(self, website_url: str) -> CloudflareSolution:
        """
        解决 Cloudflare Turnstile challenge.
        
        Args:
            website_url: 目标页面 URL
        
        Returns:
            CloudflareSolution 包含 cf_clearance cookie
            
        Raises:
            CloudflareError: 如果解决失败
        """
        page = self._create_page()
        
        try:
            print(f"🌐 正在访问: {website_url}")
            page.get(website_url)
            
            # 等待 Cloudflare 验证完成
            cf_clearance = self._wait_for_clearance(page)
            
            # 获取所有 cookies
            cookies = {}
            for cookie in page.cookies():
                cookies[cookie["name"]] = cookie["value"]
            
            # 获取 user agent
            user_agent = page.run_js("return navigator.userAgent")
            
            return CloudflareSolution(
                cf_clearance=cf_clearance,
                cookies=cookies,
                user_agent=user_agent
            )
            
        finally:
            page.quit()
    
    def _wait_for_clearance(self, page) -> str:
        """等待 cf_clearance cookie 出现"""
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > self.timeout:
                raise CloudflareError(f"等待 Cloudflare 验证超时 ({self.timeout}s)")
            
            # 检查是否有 cf_clearance cookie
            for cookie in page.cookies():
                if cookie["name"] == "cf_clearance":
                    print(f"✅ Cloudflare 验证通过，耗时 {elapsed:.1f}s")
                    return cookie["value"]
            
            # 检查页面是否还在验证中
            title = page.title.lower() if page.title else ""
            if "just a moment" in title or "checking" in title:
                print(f"⏳ 等待 Cloudflare 验证中... ({elapsed:.1f}s)")
            else:
                # 页面标题变了，可能已经通过，再检查一次 cookie
                for cookie in page.cookies():
                    if cookie["name"] == "cf_clearance":
                        print(f"✅ Cloudflare 验证通过，耗时 {elapsed:.1f}s")
                        return cookie["value"]
            
            time.sleep(1)


class CloudflareError(Exception):
    """Cloudflare solving error"""
    pass


def main():
    parser = argparse.ArgumentParser(description="Cloudflare Turnstile Challenge Solver")
    parser.add_argument("url", nargs="?", default="https://sora.chatgpt.com", help="目标 URL")
    parser.add_argument("-p", "--proxy", help="代理地址 (ip:port)")
    parser.add_argument("--headless", action="store_true", default=True, help="无头模式")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口")
    parser.add_argument("-t", "--timeout", type=int, default=60, help="超时时间（秒）")
    parser.add_argument("-o", "--output", help="输出 JSON 文件路径")
    
    args = parser.parse_args()
    
    headless = not args.no_headless
    
    print("=" * 50)
    print("Cloudflare Turnstile Challenge Solver")
    print("=" * 50)
    print(f"目标 URL: {args.url}")
    print(f"代理: {args.proxy or '无'}")
    print(f"无头模式: {headless}")
    print(f"超时: {args.timeout}s")
    print("=" * 50)
    
    solver = CloudflareSolver(
        proxy=args.proxy,
        headless=headless,
        timeout=args.timeout
    )
    
    try:
        solution = solver.solve(args.url)
        
        print("\n" + "=" * 50)
        print("✅ Challenge solved successfully!")
        print("=" * 50)
        print(f"cf_clearance: {solution.cf_clearance}")
        print(f"user_agent: {solution.user_agent}")
        print(f"\nCookies ({len(solution.cookies)}):")
        for name, value in solution.cookies.items():
            display_value = value[:50] + "..." if len(value) > 50 else value
            print(f"  {name}: {display_value}")
        
        # 输出到文件
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(solution.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\n📁 结果已保存到: {args.output}")
        
        # 输出可复制的 cookie 字符串
        print("\n📋 Cookie 字符串 (可直接使用):")
        cookie_str = "; ".join([f"{k}={v}" for k, v in solution.cookies.items()])
        print(cookie_str)
        
    except CloudflareError as e:
        print(f"\n❌ 解决失败: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        exit(1)


if __name__ == "__main__":
    main()
