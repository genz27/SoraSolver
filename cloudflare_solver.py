"""
Cloudflare Turnstile Challenge Solver using DrissionPage

独立项目，用于解决 Cloudflare 验证并获取 cf_clearance cookie
支持浏览器实例池和结果缓存
"""
import time
import json
import random
import argparse
import threading
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime
from collections import OrderedDict
from fake_useragent import UserAgent


@dataclass
class CloudflareSolution:
    """Cloudflare challenge solution result"""
    cf_clearance: str
    cookies: Dict[str, str]
    user_agent: str
    url: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        return {
            "cf_clearance": self.cf_clearance,
            "cookies": self.cookies,
            "user_agent": self.user_agent,
            "url": self.url,
            "created_at": self.created_at.isoformat()
        }
    
    def is_expired(self, max_age_seconds: int = 1800) -> bool:
        """检查 cookie 是否过期（默认30分钟）"""
        age = (datetime.now() - self.created_at).total_seconds()
        return age > max_age_seconds


class SolutionCache:
    """
    LRU 缓存，存储最近的 cf_clearance 结果
    支持按 URL+Proxy 键缓存，TTL 自动过期
    """
    
    def __init__(self, max_size: int = 50, ttl_seconds: int = 1800):
        self._cache: OrderedDict[str, CloudflareSolution] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0}
    
    def _make_key(self, url: str, proxy: Optional[str] = None) -> str:
        """生成缓存键"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        return f"{domain}|{proxy or 'direct'}"
    
    def get(self, url: str, proxy: Optional[str] = None) -> Optional[CloudflareSolution]:
        """获取缓存的解决方案"""
        key = self._make_key(url, proxy)
        
        with self._lock:
            if key not in self._cache:
                self._stats["misses"] += 1
                return None
            
            solution = self._cache[key]
            
            # 检查是否过期
            if solution.is_expired(self._ttl):
                del self._cache[key]
                self._stats["misses"] += 1
                return None
            
            # LRU: 移到末尾
            self._cache.move_to_end(key)
            self._stats["hits"] += 1
            return solution
    
    def set(self, url: str, solution: CloudflareSolution, proxy: Optional[str] = None):
        """存储解决方案"""
        key = self._make_key(url, proxy)
        solution.url = url
        
        with self._lock:
            # 如果已存在，先删除
            if key in self._cache:
                del self._cache[key]
            
            # 检查容量
            while len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
            
            self._cache[key] = solution
    
    def invalidate(self, url: str, proxy: Optional[str] = None):
        """使缓存失效"""
        key = self._make_key(url, proxy)
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
    
    def stats(self) -> dict:
        """获取缓存统计"""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total if total > 0 else 0
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": f"{hit_rate:.1%}"
            }


class BrowserPool:
    """
    浏览器实例池
    预热浏览器实例，减少冷启动时间
    """
    
    def __init__(self, pool_size: int = 2, headless: bool = True):
        self._pool_size = pool_size
        self._headless = headless
        self._available: List = []
        self._lock = threading.Lock()
        self._ua = UserAgent()
        self._stats = {"created": 0, "reused": 0, "failed": 0}
    
    def _create_page(self, proxy: Optional[str] = None):
        """创建浏览器页面"""
        import os
        from DrissionPage import ChromiumPage, ChromiumOptions
        
        options = ChromiumOptions()
        
        # Docker 环境下设置 Chrome 路径
        chrome_path = os.environ.get("CHROME_PATH")
        if chrome_path:
            options.set_browser_path(chrome_path)
        
        # 设置代理
        if proxy:
            proxy_addr = proxy if proxy.startswith("http") else f"http://{proxy}"
            options.set_proxy(proxy_addr)
        
        # 随机 User-Agent
        options.set_user_agent(self._ua.chrome)
        
        # 无头模式
        if self._headless:
            options.set_argument("--headless=new")
        
        # 窗口大小随机化
        width = random.randint(1200, 1920)
        height = random.randint(800, 1080)
        options.set_argument(f"--window-size={width},{height}")
        
        # 反检测设置
        options.set_argument("--disable-blink-features=AutomationControlled")
        options.set_argument("--no-sandbox")
        options.set_argument("--disable-dev-shm-usage")
        options.set_argument("--disable-gpu")
        options.set_argument("--disable-infobars")
        options.set_argument("--disable-extensions")
        options.set_argument("--disable-popup-blocking")
        options.set_argument("--ignore-certificate-errors")
        options.set_argument("--disable-web-security")
        options.set_argument("--lang=en-US,en")
        options.set_argument("--disable-software-rasterizer")
        options.set_argument("--single-process")
        
        options.set_pref("credentials_enable_service", False)
        options.set_pref("profile.password_manager_enabled", False)
        
        return ChromiumPage(options)
    
    def acquire(self, proxy: Optional[str] = None):
        """获取浏览器实例"""
        # 注意：由于代理是在创建时设置的，池化只对无代理请求有效
        if proxy:
            self._stats["created"] += 1
            return self._create_page(proxy)
        
        with self._lock:
            if self._available:
                self._stats["reused"] += 1
                return self._available.pop()
        
        self._stats["created"] += 1
        return self._create_page()
    
    def release(self, page, proxy: Optional[str] = None):
        """归还浏览器实例"""
        # 有代理的实例不复用
        if proxy:
            try:
                page.quit()
            except:
                pass
            return
        
        with self._lock:
            if len(self._available) < self._pool_size:
                try:
                    # 清理状态
                    page.get("about:blank")
                    self._available.append(page)
                    return
                except:
                    self._stats["failed"] += 1
        
        try:
            page.quit()
        except:
            pass
    
    def warmup(self, count: int = None):
        """预热浏览器实例"""
        count = count or self._pool_size
        print(f"🔥 预热 {count} 个浏览器实例...")
        
        for i in range(count):
            try:
                page = self._create_page()
                with self._lock:
                    if len(self._available) < self._pool_size:
                        self._available.append(page)
                    else:
                        page.quit()
                print(f"  ✓ 实例 {i+1}/{count} 就绪")
            except Exception as e:
                print(f"  ✗ 实例 {i+1}/{count} 失败: {e}")
        
        print(f"🔥 预热完成，可用实例: {len(self._available)}")
    
    def shutdown(self):
        """关闭所有实例"""
        with self._lock:
            for page in self._available:
                try:
                    page.quit()
                except:
                    pass
            self._available.clear()
    
    def stats(self) -> dict:
        """获取池统计"""
        with self._lock:
            return {
                "available": len(self._available),
                "pool_size": self._pool_size,
                **self._stats
            }


# 全局实例
_solution_cache: Optional[SolutionCache] = None
_browser_pool: Optional[BrowserPool] = None


def get_cache() -> SolutionCache:
    """获取全局缓存实例"""
    global _solution_cache
    if _solution_cache is None:
        _solution_cache = SolutionCache()
    return _solution_cache


def get_browser_pool() -> Optional[BrowserPool]:
    """获取全局浏览器池"""
    return _browser_pool


def init_browser_pool(pool_size: int = 2, headless: bool = True, warmup: bool = True):
    """初始化浏览器池"""
    global _browser_pool
    _browser_pool = BrowserPool(pool_size=pool_size, headless=headless)
    if warmup:
        _browser_pool.warmup()
    return _browser_pool


class CloudflareSolver:
    """
    Cloudflare Turnstile Challenge solver using DrissionPage.
    使用真实浏览器绕过 Cloudflare 检测。
    """
    
    def __init__(
        self,
        proxy: Optional[str] = None,
        headless: bool = True,
        timeout: int = 60,
        use_cache: bool = True,
        use_pool: bool = True
    ):
        self.proxy = proxy
        self.headless = headless
        self.timeout = timeout
        self.use_cache = use_cache
        self.use_pool = use_pool
        self.ua = UserAgent()
    
    def _random_delay(self, min_ms: int = 100, max_ms: int = 500):
        """随机延迟"""
        time.sleep(random.randint(min_ms, max_ms) / 1000)
    
    def _create_page(self):
        """创建浏览器页面（不使用池时）"""
        import os
        from DrissionPage import ChromiumPage, ChromiumOptions
        
        options = ChromiumOptions()
        
        chrome_path = os.environ.get("CHROME_PATH")
        if chrome_path:
            options.set_browser_path(chrome_path)
        
        if self.proxy:
            proxy_addr = self.proxy if self.proxy.startswith("http") else f"http://{self.proxy}"
            options.set_proxy(proxy_addr)
        
        options.set_user_agent(self.ua.chrome)
        
        if self.headless:
            options.set_argument("--headless=new")
        
        width = random.randint(1200, 1920)
        height = random.randint(800, 1080)
        options.set_argument(f"--window-size={width},{height}")
        
        options.set_argument("--disable-blink-features=AutomationControlled")
        options.set_argument("--no-sandbox")
        options.set_argument("--disable-dev-shm-usage")
        options.set_argument("--disable-gpu")
        options.set_argument("--disable-infobars")
        options.set_argument("--disable-extensions")
        options.set_argument("--disable-popup-blocking")
        options.set_argument("--ignore-certificate-errors")
        options.set_argument("--disable-web-security")
        options.set_argument("--lang=en-US,en")
        options.set_argument("--disable-software-rasterizer")
        options.set_argument("--single-process")
        
        options.set_pref("credentials_enable_service", False)
        options.set_pref("profile.password_manager_enabled", False)
        
        return ChromiumPage(options)
    
    def _inject_stealth_js(self, page):
        """注入反检测 JavaScript"""
        stealth_js = """
        (function() {
            // 安全地尝试修改属性，如果已存在则跳过
            try {
                if (navigator.webdriver !== undefined) {
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true });
                }
            } catch(e) {}
            
            try {
                if (!window.chrome) {
                    window.chrome = { runtime: {} };
                }
            } catch(e) {}
            
            try {
                const originalQuery = window.navigator.permissions.query;
                if (originalQuery) {
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                }
            } catch(e) {}
        })();
        """
        try:
            page.run_js(stealth_js)
        except Exception:
            pass  # 静默失败，DrissionPage 已有内置反检测
    
    def _simulate_mouse_movement(self, page, retry: int = 3):
        """模拟鼠标移动"""
        for attempt in range(retry):
            try:
                # 等待页面稳定
                page.wait.doc_loaded(timeout=5)
                self._random_delay(300, 500)
                
                width = page.run_js("return window.innerWidth") or 1200
                height = page.run_js("return window.innerHeight") or 800
                
                for _ in range(random.randint(3, 6)):
                    x = random.randint(100, width - 100)
                    y = random.randint(100, height - 100)
                    page.actions.move_to((x, y))
                    self._random_delay(50, 200)
                return
            except Exception as e:
                if attempt < retry - 1:
                    self._random_delay(500, 1000)
                else:
                    print(f"⚠️ 模拟鼠标移动失败: {e}")
    
    def _try_click_turnstile(self, page) -> bool:
        """尝试点击 Turnstile checkbox"""
        try:
            selectors = [
                'iframe[src*="challenges.cloudflare.com"]',
                'iframe[src*="turnstile"]',
                'iframe[title*="Cloudflare"]',
                '#turnstile-wrapper iframe',
                '.cf-turnstile iframe',
            ]
            
            for selector in selectors:
                try:
                    iframe = page.ele(selector, timeout=2)
                    if iframe:
                        page.to_frame(iframe)
                        self._random_delay(300, 800)
                        
                        checkbox_selectors = [
                            'input[type="checkbox"]',
                            '.ctp-checkbox-label',
                            '#challenge-stage',
                            'div[class*="checkbox"]',
                        ]
                        
                        for cb_selector in checkbox_selectors:
                            try:
                                checkbox = page.ele(cb_selector, timeout=1)
                                if checkbox:
                                    self._random_delay(200, 500)
                                    checkbox.click()
                                    page.to_main()
                                    return True
                            except:
                                continue
                        
                        page.to_main()
                except:
                    continue
            
            button_selectors = [
                'input[type="button"][value*="Verify"]',
                'button:contains("Verify")',
                '#challenge-form input[type="submit"]',
            ]
            
            for selector in button_selectors:
                try:
                    btn = page.ele(selector, timeout=1)
                    if btn:
                        self._random_delay(200, 500)
                        btn.click()
                        return True
                except:
                    continue
                    
        except Exception as e:
            print(f"⚠️ 点击 Turnstile 失败: {e}")
        
        return False
    
    def solve(self, website_url: str, skip_cache: bool = False) -> CloudflareSolution:
        """
        解决 Cloudflare Turnstile challenge.
        
        Args:
            website_url: 目标页面 URL
            skip_cache: 跳过缓存，强制获取新的 cookie
        
        Returns:
            CloudflareSolution 包含 cf_clearance cookie
        """
        # 检查缓存
        if self.use_cache and not skip_cache:
            cache = get_cache()
            cached = cache.get(website_url, self.proxy)
            if cached:
                print(f"📦 使用缓存的 cf_clearance (剩余 {1800 - (datetime.now() - cached.created_at).total_seconds():.0f}s)")
                return cached
        
        # 获取浏览器实例
        pool = get_browser_pool() if self.use_pool else None
        page = None
        
        try:
            if pool:
                page = pool.acquire(self.proxy)
            else:
                page = self._create_page()
            
            self._random_delay(500, 1500)
            
            print(f"🌐 正在访问: {website_url}")
            page.get(website_url)
            
            self._inject_stealth_js(page)
            self._random_delay(1000, 2000)
            self._simulate_mouse_movement(page)
            
            cf_clearance = self._wait_for_clearance(page)
            
            cookies = {cookie["name"]: cookie["value"] for cookie in page.cookies()}
            user_agent = page.run_js("return navigator.userAgent")
            
            solution = CloudflareSolution(
                cf_clearance=cf_clearance,
                cookies=cookies,
                user_agent=user_agent,
                url=website_url
            )
            
            # 存入缓存
            if self.use_cache:
                get_cache().set(website_url, solution, self.proxy)
            
            return solution
            
        finally:
            if page:
                if pool:
                    pool.release(page, self.proxy)
                else:
                    page.quit()
    
    def _wait_for_clearance(self, page) -> str:
        """等待 cf_clearance cookie 出现"""
        start_time = time.time()
        click_attempted = False
        last_mouse_move = 0
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > self.timeout:
                raise CloudflareError(f"等待 Cloudflare 验证超时 ({self.timeout}s)")
            
            # 先检查 cookie
            try:
                for cookie in page.cookies():
                    if cookie["name"] == "cf_clearance":
                        print(f"✅ Cloudflare 验证通过，耗时 {elapsed:.1f}s")
                        return cookie["value"]
            except:
                self._random_delay(500, 1000)
                continue
            
            # 检查页面状态
            try:
                title = page.title.lower() if page.title else ""
            except:
                self._random_delay(500, 1000)
                continue
            
            if "just a moment" in title or "checking" in title:
                print(f"⏳ 等待 Cloudflare 验证中... ({elapsed:.1f}s)")
                
                if not click_attempted or elapsed > 5:
                    if self._try_click_turnstile(page):
                        click_attempted = True
                        self._random_delay(1000, 2000)
                
                # 每15秒模拟一次鼠标移动，避免频繁操作
                if elapsed - last_mouse_move > 15:
                    self._simulate_mouse_movement(page)
                    last_mouse_move = elapsed
            else:
                try:
                    for cookie in page.cookies():
                        if cookie["name"] == "cf_clearance":
                            print(f"✅ Cloudflare 验证通过，耗时 {elapsed:.1f}s")
                            return cookie["value"]
                except:
                    pass
            
            self._random_delay(800, 1500)


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
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    
    args = parser.parse_args()
    headless = not args.no_headless
    
    print("=" * 50)
    print("Cloudflare Turnstile Challenge Solver")
    print("=" * 50)
    print(f"目标 URL: {args.url}")
    print(f"代理: {args.proxy or '无'}")
    print(f"无头模式: {headless}")
    print(f"超时: {args.timeout}s")
    print(f"缓存: {'禁用' if args.no_cache else '启用'}")
    print("=" * 50)
    
    solver = CloudflareSolver(
        proxy=args.proxy,
        headless=headless,
        timeout=args.timeout,
        use_cache=not args.no_cache,
        use_pool=False  # CLI 模式不使用池
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
        
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(solution.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\n📁 结果已保存到: {args.output}")
        
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
