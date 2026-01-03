"""
配置管理模块 - 使用 SQLite 存储配置
"""
import sqlite3
import hashlib
import secrets
import threading
from typing import Optional, Dict, Any
from pathlib import Path

DB_PATH = Path("data/config.db")


def get_db() -> sqlite3.Connection:
    """获取数据库连接"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 配置表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT,
            description TEXT
        )
    """)
    
    # API Key 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            name TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 管理员表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    
    # 请求日志表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS request_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT,
            url TEXT,
            proxy TEXT,
            success INTEGER,
            error TEXT,
            elapsed_seconds REAL,
            from_cache INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 初始化默认配置
    defaults = {
        "max_workers": ("3", "并发浏览器数量"),
        "pool_size": ("2", "预热浏览器池大小"),
        "semaphore_limit": ("3", "并发请求限制"),
        "cache_ttl": ("1800", "缓存过期时间(秒)"),
        "max_retries": ("0", "默认重试次数"),
        "require_api_key": ("0", "是否需要API Key验证(0/1)"),
        "proxy_pool_enabled": ("0", "是否启用代理池(0/1)"),
        "proxy_list": ("", "代理列表(一行一个)"),
    }
    
    for key, (value, desc) in defaults.items():
        cursor.execute(
            "INSERT OR IGNORE INTO config (key, value, description) VALUES (?, ?, ?)",
            (key, value, desc)
        )
    
    # 创建默认管理员 admin/admin123
    default_pwd_hash = hashlib.sha256("admin123".encode()).hexdigest()
    cursor.execute(
        "INSERT OR IGNORE INTO admins (username, password_hash) VALUES (?, ?)",
        ("admin", default_pwd_hash)
    )
    
    # 创建默认 API Key
    cursor.execute("SELECT COUNT(*) FROM api_keys")
    if cursor.fetchone()[0] == 0:
        default_key = secrets.token_urlsafe(32)
        cursor.execute(
            "INSERT INTO api_keys (key, name) VALUES (?, ?)",
            (default_key, "default")
        )
        print(f"📌 默认 API Key: {default_key}")
    
    conn.commit()
    conn.close()


class ConfigManager:
    """配置管理器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache = {}
        return cls._instance
    
    def get(self, key: str, default: Any = None) -> str:
        """获取配置值"""
        if key in self._cache:
            return self._cache[key]
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        
        value = row["value"] if row else default
        self._cache[key] = value
        return value
    
    def get_int(self, key: str, default: int = 0) -> int:
        """获取整数配置"""
        return int(self.get(key, str(default)))
    
    def set(self, key: str, value: str, description: str = None):
        """设置配置值"""
        conn = get_db()
        cursor = conn.cursor()
        if description:
            cursor.execute(
                "INSERT OR REPLACE INTO config (key, value, description) VALUES (?, ?, ?)",
                (key, value, description)
            )
        else:
            cursor.execute(
                "UPDATE config SET value = ? WHERE key = ?",
                (value, key)
            )
        conn.commit()
        conn.close()
        self._cache[key] = value
    
    def get_all(self) -> Dict[str, Dict]:
        """获取所有配置"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value, description FROM config")
        rows = cursor.fetchall()
        conn.close()
        return {row["key"]: {"value": row["value"], "description": row["description"]} for row in rows}
    
    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()


class APIKeyManager:
    """API Key 管理器"""
    
    def validate(self, key: str) -> bool:
        """验证 API Key"""
        if not key:
            return False
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM api_keys WHERE key = ? AND enabled = 1", (key,))
        row = cursor.fetchone()
        conn.close()
        return row is not None
    
    def list_keys(self) -> list:
        """列出所有 API Key"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, key, name, enabled, created_at FROM api_keys")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def add_key(self, name: str = None) -> str:
        """添加新 API Key"""
        key = secrets.token_urlsafe(32)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO api_keys (key, name) VALUES (?, ?)", (key, name or "unnamed"))
        conn.commit()
        conn.close()
        return key
    
    def delete_key(self, key_id: int):
        """删除 API Key"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        conn.commit()
        conn.close()
    
    def toggle_key(self, key_id: int, enabled: bool):
        """启用/禁用 API Key"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE api_keys SET enabled = ? WHERE id = ?", (1 if enabled else 0, key_id))
        conn.commit()
        conn.close()


class AdminManager:
    """管理员管理器"""
    
    def verify(self, username: str, password: str) -> bool:
        """验证管理员登录"""
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM admins WHERE username = ? AND password_hash = ?",
            (username, pwd_hash)
        )
        row = cursor.fetchone()
        conn.close()
        return row is not None
    
    def change_password(self, username: str, new_password: str) -> bool:
        """修改密码"""
        pwd_hash = hashlib.sha256(new_password.encode()).hexdigest()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE admins SET password_hash = ? WHERE username = ?",
            (pwd_hash, username)
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0


class ProxyPoolManager:
    """代理池管理器 - 简化版，从配置读取代理列表"""
    
    _current_index = 0
    _lock = threading.Lock()
    
    def parse_proxy(self, line: str) -> Optional[str]:
        """
        解析代理格式，支持多种格式：
        - ip:port
        - http://ip:port
        - socks5://ip:port
        - user:pass@ip:port
        - http://user:pass@ip:port
        """
        line = line.strip()
        if not line or line.startswith('#'):
            return None
        
        # 已经是完整格式
        if '://' in line:
            return line
        
        # 简单格式 ip:port 或 user:pass@ip:port
        if '@' in line:
            # user:pass@ip:port -> http://user:pass@ip:port
            return f"http://{line}"
        else:
            # ip:port -> http://ip:port
            return f"http://{line}"
    
    def get_proxy_list(self) -> list:
        """获取所有代理"""
        proxy_text = config.get("proxy_list", "")
        proxies = []
        for line in proxy_text.split('\n'):
            proxy = self.parse_proxy(line)
            if proxy:
                proxies.append(proxy)
        return proxies
    
    def get_next_proxy(self) -> Optional[str]:
        """轮询获取下一个代理"""
        proxies = self.get_proxy_list()
        if not proxies:
            return None
        
        with self._lock:
            proxy = proxies[self._current_index % len(proxies)]
            self._current_index += 1
        return proxy
    
    def get_proxy_count(self) -> int:
        """获取代理数量"""
        return len(self.get_proxy_list())


class RequestLogger:
    """请求日志管理器"""
    
    def log(self, request_id: str, url: str, proxy: str, success: bool, 
            error: str = None, elapsed: float = 0, from_cache: bool = False):
        """记录请求日志"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO request_logs (request_id, url, proxy, success, error, elapsed_seconds, from_cache)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (request_id, url, proxy, 1 if success else 0, error, elapsed, 1 if from_cache else 0))
        conn.commit()
        conn.close()
    
    def get_logs(self, limit: int = 100) -> list:
        """获取最近的日志"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, request_id, url, proxy, success, error, elapsed_seconds, from_cache, created_at 
            FROM request_logs ORDER BY id DESC LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def clear_logs(self):
        """清空日志"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM request_logs")
        conn.commit()
        conn.close()


# 全局实例
config = ConfigManager()
api_keys = APIKeyManager()
admins = AdminManager()
proxy_pool = ProxyPoolManager()
request_logger = RequestLogger()
