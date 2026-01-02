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
        self._instance_counter = 0
    
    def _create_page(self, proxy: Optional[str] = None):
        """创建浏览器页面"""
        import os
        import tempfile
        from DrissionPage import ChromiumPage, ChromiumOptions
        
        options = ChromiumOptions()
        
        # Docker 环境下设置 Chrome 路径
        chrome_path = os.environ.get("CHROME_PATH")
        if chrome_path:
            options.set_browser_path(chrome_path)
        elif os.path.exists(r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
            options.set_browser_path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        
        # 为每个实例创建独立的用户数据目录，避免冲突
        self._instance_counter += 1
        user_data_dir = os.path.join(tempfile.gettempdir(), f"cf_pool_{os.getpid()}_{self._instance_counter}_{random.randint(10000,99999)}")
        options.set_user_data_path(user_data_dir)
        
        # 自动分配端口避免冲突
        options.auto_port()
        
        # 设置代理
        if proxy:
            proxy_addr = proxy if proxy.startswith("http") else f"http://{proxy}"
            options.set_proxy(proxy_addr)
        
        # 随机 User-Agent
        options.set_user_agent(self._ua.chrome)
        
        # 无头模式 - 使用新版无头模式更难被检测
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
        options.set_argument("--lang=en-US,en")
        options.set_argument("--disable-web-security")
        options.set_argument("--allow-running-insecure-content")
        
        # 更多反检测
        options.set_pref("credentials_enable_service", False)
        options.set_pref("profile.password_manager_enabled", False)
        options.set_pref("webrtc.ip_handling_policy", "disable_non_proxied_udp")
        options.set_pref("webrtc.multiple_routes_enabled", False)
        options.set_pref("webrtc.nonproxied_udp_enabled", False)
        
        return ChromiumPage(options)
    
    def acquire(self, proxy: Optional[str] = None):
        """获取浏览器实例"""
        # 注意：由于代理是在创建时设置的，池化只对无代理请求有效
        if proxy:
            self._stats["created"] += 1
            return self._create_page(proxy)
        
        with self._lock:
            if self._available:
                page = self._available.pop()
                self._stats["reused"] += 1
                print(f"  ♻️ 复用浏览器实例，剩余: {len(self._available)}")
                return page
        
        print("  🆕 创建新浏览器实例...")
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
                    # 清理 cookies 和状态，但保持浏览器打开
                    page.clear_cache()
                    page.get("about:blank")
                    self._available.append(page)
                    print(f"  ♻️ 浏览器实例已归还，可用: {len(self._available)}")
                    return
                except Exception as e:
                    print(f"  ⚠️ 归还实例失败: {e}")
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
                # 测试浏览器是否正常工作
                page.get("about:blank")
                with self._lock:
                    if len(self._available) < self._pool_size:
                        self._available.append(page)
                        print(f"  ✓ 实例 {i+1}/{count} 就绪")
                    else:
                        page.quit()
            except Exception as e:
                print(f"  ✗ 实例 {i+1}/{count} 失败: {e}")
        
        print(f"🔥 预热完成，可用实例: {len(self._available)}")
        
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
        self._instance_counter = 0
    
    def _random_delay(self, min_ms: int = 100, max_ms: int = 500):
        """随机延迟"""
        time.sleep(random.randint(min_ms, max_ms) / 1000)
    
    def _create_page(self):
        """创建浏览器页面（不使用池时）"""
        import os
        import tempfile
        from DrissionPage import ChromiumPage, ChromiumOptions
        
        options = ChromiumOptions()
        
        chrome_path = os.environ.get("CHROME_PATH")
        if chrome_path:
            options.set_browser_path(chrome_path)
        elif os.path.exists(r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
            options.set_browser_path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        
        # 为每个实例创建独立的用户数据目录，避免冲突
        self._instance_counter += 1
        user_data_dir = os.path.join(tempfile.gettempdir(), f"cf_solver_{os.getpid()}_{self._instance_counter}_{random.randint(10000,99999)}")
        options.set_user_data_path(user_data_dir)
        
        # 自动分配端口避免冲突
        options.auto_port()
        
        if self.proxy:
            proxy_addr = self.proxy if self.proxy.startswith("http") else f"http://{self.proxy}"
            options.set_proxy(proxy_addr)
        
        options.set_user_agent(self.ua.chrome)
        
        if self.headless:
            options.set_argument("--headless=new")
        
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
        options.set_argument("--lang=en-US,en")
        
        options.set_pref("credentials_enable_service", False)
        options.set_pref("profile.password_manager_enabled", False)
        
        return ChromiumPage(options)
    
    def solve(self, website_url: str, skip_cache: bool = False, max_retries: int = 5) -> CloudflareSolution:
        """
        解决 Cloudflare Turnstile challenge.
        如果遇到人机验证，关闭浏览器重新打开一个新的。
        """
        # 检查缓存
        if self.use_cache and not skip_cache:
            cache = get_cache()
            cached = cache.get(website_url, self.proxy)
            if cached:
                print(f"📦 使用缓存的 cf_clearance")
                return cached
        
        last_error = None
        print(f"🚀 开始获取 cf_clearance, URL: {website_url}, 最大重试: {max_retries}")
        
        for attempt in range(max_retries + 1):
            page = None
            
            try:
                if attempt > 0:
                    # 重试前等待一段时间
                    wait_time = random.randint(3000, 5000)
                    print(f"🔄 第 {attempt}/{max_retries} 次重试，等待 {wait_time/1000:.1f}s...")
                    self._random_delay(wait_time, wait_time + 1000)
                else:
                    print(f"🆕 第 1 次尝试...")
                
                # 每次都创建新的浏览器实例
                print(f"  📂 创建新浏览器实例...")
                page = self._create_page()
                print(f"  ✓ 浏览器已启动")
                
                print(f"  🌐 访问: {website_url}")
                page.get(website_url)
                
                # 等待页面加载
                print(f"  ⏳ 等待页面加载...")
                self._random_delay(2000, 3000)
                
                # 获取页面信息
                title = page.title if page.title else "无标题"
                print(f"  📄 页面标题: {title}")
                
                # 检查是否需要人机验证
                print(f"  🔍 检查 cf_clearance...")
                cf_clearance = self._check_clearance(page)
                
                if cf_clearance:
                    cookies = {cookie["name"]: cookie["value"] for cookie in page.cookies()}
                    user_agent = page.run_js("return navigator.userAgent")
                    
                    solution = CloudflareSolution(
                        cf_clearance=cf_clearance,
                        cookies=cookies,
                        user_agent=user_agent,
                        url=website_url
                    )
                    
                    if self.use_cache:
                        get_cache().set(website_url, solution, self.proxy)
                    
                    print(f"✅ 成功获取 cf_clearance!")
                    print(f"  📝 cf_clearance: {cf_clearance[:50]}...")
                    return solution
                else:
                    # 遇到人机验证，关闭浏览器重试
                    print(f"  ❌ 未获取到 cf_clearance，准备重试...")
                    raise CloudflareError("需要人机验证或超时")
                
            except Exception as e:
                last_error = e
                print(f"  ❌ 本次尝试失败: {e}")
            finally:
                # 每次都关闭浏览器
                if page:
                    try:
                        page.quit()
                        print(f"  🔒 浏览器已关闭")
                    except:
                        pass
                    page = None
        
        print(f"❌ 所有 {max_retries + 1} 次尝试均失败")
        raise CloudflareError(f"重试 {max_retries} 次后仍然失败: {last_error}")
    
    def _check_clearance(self, page, wait_time: int = 8) -> Optional[str]:
        """检查是否获取到 cf_clearance，如果遇到人机验证返回 None"""
        start_time = time.time()
        check_count = 0
        
        while time.time() - start_time < wait_time:
            check_count += 1
            elapsed = time.time() - start_time
            
            try:
                # 先检查 cookie
                cookies = page.cookies()
                for cookie in cookies:
                    if cookie["name"] == "cf_clearance":
                        print(f"    ✓ 找到 cf_clearance (第{check_count}次检查, {elapsed:.1f}s)")
                        return cookie["value"]
                
                # 获取页面状态
                title = page.title.lower() if page.title else ""
                page_text = page.html if page.html else ""
                
                # 检查是否有人机验证（需要点击的那种）
                is_manual_challenge = (
                    "确认您是真人" in page_text or
                    "verify you are human" in page_text
                )
                
                if is_manual_challenge:
                    print(f"    ⚠️ 检测到人机验证页面 (第{check_count}次检查, {elapsed:.1f}s)")
                    return None
                
                # 检查是否在自动验证中
                is_auto_checking = "just a moment" in title or "checking" in title
                
                if is_auto_checking:
                    if check_count == 1:
                        print(f"    ⏳ 页面正在自动验证中...")
                elif check_count == 1:
                    print(f"    📄 页面已加载，等待 cookie...")
                
            except Exception as e:
                if check_count == 1:
                    print(f"    ⚠️ 检查出错: {e}")
            
            self._random_delay(500, 1000)
        
        # 超时
        print(f"    ⏰ 等待超时 ({wait_time}s)，共检查 {check_count} 次")
        return None


class CloudflareError(Exception):
    """Cloudflare solving error"""
    pass


def main():
    parser = argparse.ArgumentParser(description="Cloudflare Turnstile Challenge Solver")
    parser.add_argument("url", nargs="?", default="https://sora.chatgpt.com", help="目标 URL")
    parser.add_argument("-p", "--proxy", help="代理地址 (ip:port)")
    parser.add_argument("--headless", action="store_true", default=True, help="无头模式（默认）")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口（默认）")
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
