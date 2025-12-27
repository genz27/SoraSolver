"""
Cloudflare Turnstile Challenge Solver using DrissionPage

独立项目，用于解决 Cloudflare 验证并获取 cf_clearance cookie
"""
import time
import json
import random
import argparse
from typing import Optional, Dict
from dataclasses import dataclass, field
from datetime import datetime
from fake_useragent import UserAgent


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
        self.ua = UserAgent()
    
    def _random_delay(self, min_ms: int = 100, max_ms: int = 500):
        """随机延迟"""
        delay = random.randint(min_ms, max_ms) / 1000
        time.sleep(delay)
    
    def _create_page(self):
        """创建浏览器页面"""
        import os
        from DrissionPage import ChromiumPage, ChromiumOptions
        
        options = ChromiumOptions()
        
        # Docker 环境下设置 Chrome 路径
        chrome_path = os.environ.get("CHROME_PATH")
        if chrome_path:
            options.set_browser_path(chrome_path)
        
        # 设置代理
        if self.proxy:
            proxy_addr = self.proxy
            if not proxy_addr.startswith("http"):
                proxy_addr = f"http://{proxy_addr}"
            options.set_proxy(proxy_addr)
        
        # 随机选择 User-Agent（使用 fake-useragent 库）
        user_agent = self.ua.chrome
        options.set_user_agent(user_agent)
        
        # 无头模式 - 使用新版无头模式
        if self.headless:
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
        
        # 语言和时区
        options.set_argument("--lang=en-US,en")
        
        # Docker 环境额外参数
        options.set_argument("--disable-software-rasterizer")
        options.set_argument("--single-process")
        
        # 设置 pref 来隐藏自动化特征
        options.set_pref("credentials_enable_service", False)
        options.set_pref("profile.password_manager_enabled", False)
        
        return ChromiumPage(options)
    
    def _inject_stealth_js(self, page):
        """注入反检测 JavaScript"""
        stealth_js = """
        // 覆盖 webdriver 属性
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        
        // 覆盖 plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        
        // 覆盖 languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
        
        // 覆盖 platform
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32'
        });
        
        // 覆盖 hardwareConcurrency
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8
        });
        
        // 覆盖 deviceMemory
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8
        });
        
        // 修改 chrome 对象
        window.chrome = {
            runtime: {}
        };
        
        // 覆盖权限查询
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        """
        try:
            page.run_js(stealth_js)
        except Exception as e:
            print(f"⚠️ 注入反检测脚本失败: {e}")
    
    def _simulate_mouse_movement(self, page):
        """模拟鼠标移动"""
        try:
            # 获取页面尺寸
            width = page.run_js("return window.innerWidth") or 1200
            height = page.run_js("return window.innerHeight") or 800
            
            # 随机移动鼠标几次
            for _ in range(random.randint(3, 6)):
                x = random.randint(100, width - 100)
                y = random.randint(100, height - 100)
                page.actions.move_to((x, y))
                self._random_delay(50, 200)
            
            print("🖱️ 模拟鼠标移动完成")
        except Exception as e:
            print(f"⚠️ 模拟鼠标移动失败: {e}")
    
    def _try_click_turnstile(self, page) -> bool:
        """尝试点击 Turnstile checkbox"""
        try:
            # Turnstile iframe 选择器
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
                        print(f"🔍 找到 Turnstile iframe: {selector}")
                        
                        # 切换到 iframe
                        page.to_frame(iframe)
                        self._random_delay(300, 800)
                        
                        # 尝试点击 checkbox
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
                                    # 模拟人类点击 - 先移动到元素附近
                                    self._random_delay(200, 500)
                                    checkbox.click()
                                    print(f"✅ 点击了 Turnstile checkbox: {cb_selector}")
                                    page.to_main()
                                    return True
                            except:
                                continue
                        
                        page.to_main()
                except:
                    continue
            
            # 尝试直接点击页面上的验证按钮
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
                        print(f"✅ 点击了验证按钮: {selector}")
                        return True
                except:
                    continue
                    
        except Exception as e:
            print(f"⚠️ 点击 Turnstile 失败: {e}")
        
        return False
    
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
            # 初始随机延迟
            self._random_delay(500, 1500)
            
            print(f"🌐 正在访问: {website_url}")
            page.get(website_url)
            
            # 注入反检测脚本
            self._inject_stealth_js(page)
            
            # 等待页面加载
            self._random_delay(1000, 2000)
            
            # 模拟鼠标移动
            self._simulate_mouse_movement(page)
            
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
        click_attempted = False
        last_mouse_move = 0
        
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
                
                # 每5秒尝试点击一次 Turnstile
                if not click_attempted or elapsed > 5:
                    if self._try_click_turnstile(page):
                        click_attempted = True
                        self._random_delay(1000, 2000)
                
                # 每10秒模拟一次鼠标移动
                if elapsed - last_mouse_move > 10:
                    self._simulate_mouse_movement(page)
                    last_mouse_move = elapsed
            else:
                # 页面标题变了，可能已经通过，再检查一次 cookie
                for cookie in page.cookies():
                    if cookie["name"] == "cf_clearance":
                        print(f"✅ Cloudflare 验证通过，耗时 {elapsed:.1f}s")
                        return cookie["value"]
            
            # 随机延迟
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
