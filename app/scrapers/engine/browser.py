"""
Playwright 浏览器池

- 复用浏览器实例，减少启动开销
- 注入隐身脚本，规避 Playwright 指纹检测
- 模拟真实用户行为（鼠标移动、随机延迟、滚动）
"""
import asyncio
import random
import time
from typing import Optional
from loguru import logger
from app.scrapers.engine.fingerprint import FingerprintGenerator, BrowserFingerprint

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    logger.warning("[浏览器池] playwright 未安装，浏览器功能不可用。运行: pip install playwright && playwright install chromium")


# Playwright 隐身注入脚本 - 隐藏自动化特征
STEALTH_JS = """
() => {
    // 隐藏 webdriver 标志
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 隐藏 Playwright/Puppeteer 特征
    delete window.__playwright;
    delete window.__pw_manual;

    // 伪造 plugins 数组
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                { name: 'Native Client', filename: 'internal-nacl-plugin' },
            ];
            plugins.length = 3;
            return plugins;
        }
    });

    // 伪造 languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en']
    });

    // Chrome 特有属性
    window.chrome = {
        runtime: { connect: () => {}, sendMessage: () => {} },
        loadTimes: () => ({}),
        csi: () => ({}),
        app: { isInstalled: false },
    };

    // 隐藏自动化权限查询
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters)
    );

    // 伪造 WebGL 信息 (由外部注入具体值)
    // 这部分在 context 初始化时通过参数注入
}
"""


class BrowserPool:
    """
    浏览器实例池

    管理多个浏览器上下文，每个上下文有独立的指纹、Cookie和存储
    """

    def __init__(self, max_contexts: int = 5):
        self.max_contexts = max_contexts
        self._playwright = None
        self._browser: Optional[object] = None
        self._available: asyncio.Queue = asyncio.Queue()
        self._all_contexts: list = []
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self):
        """初始化浏览器池"""
        if not HAS_PLAYWRIGHT:
            logger.error("[浏览器池] playwright 未安装，无法初始化")
            return False

        async with self._lock:
            if self._initialized:
                return True
            try:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--disable-infobars",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--disable-gpu",
                        "--lang=zh-CN",
                    ],
                )
                self._initialized = True
                logger.info(f"[浏览器池] Chromium 已启动, 最大上下文数: {self.max_contexts}")
                return True
            except Exception as e:
                logger.error(f"[浏览器池] 启动失败: {e}")
                return False

    async def get_context(
        self,
        fingerprint: Optional[BrowserFingerprint] = None,
        proxy: Optional[str] = None,
    ) -> Optional[object]:
        """
        获取一个浏览器上下文

        每个上下文拥有独立的指纹、Cookie和网络配置
        """
        if not self._initialized:
            if not await self.initialize():
                return None

        fp = fingerprint or FingerprintGenerator.generate(mobile=True)

        try:
            context_options = {
                "user_agent": fp.user_agent,
                "viewport": {"width": fp.viewport_width, "height": fp.viewport_height},
                "device_scale_factor": fp.device_scale_factor,
                "is_mobile": fp.is_mobile,
                "has_touch": fp.is_mobile,
                "locale": "zh-CN",
                "timezone_id": fp.timezone,
                "permissions": ["geolocation"],
            }

            if proxy:
                context_options["proxy"] = {"server": proxy}

            context = await self._browser.new_context(**context_options)

            # 注入隐身脚本
            await context.add_init_script(STEALTH_JS)

            # 注入 WebGL 指纹覆盖
            webgl_script = f"""
            () => {{
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                    if (parameter === 37445) return '{fp.webgl_vendor}';
                    if (parameter === 37446) return '{fp.webgl_renderer}';
                    return getParameter.call(this, parameter);
                }};
            }}
            """
            await context.add_init_script(webgl_script)

            self._all_contexts.append(context)
            return context
        except Exception as e:
            logger.error(f"[浏览器池] 创建上下文失败: {e}")
            return None

    async def new_page(
        self,
        context: Optional[object] = None,
        fingerprint: Optional[BrowserFingerprint] = None,
        proxy: Optional[str] = None,
    ) -> Optional[object]:
        """获取一个新的页面"""
        if context is None:
            context = await self.get_context(fingerprint=fingerprint, proxy=proxy)
        if context is None:
            return None
        try:
            page = await context.new_page()
            return page
        except Exception as e:
            logger.error(f"[浏览器池] 创建页面失败: {e}")
            return None

    async def close_context(self, context):
        """关闭一个上下文"""
        try:
            if context in self._all_contexts:
                self._all_contexts.remove(context)
            await context.close()
        except Exception:
            pass

    async def shutdown(self):
        """关闭所有浏览器"""
        for ctx in self._all_contexts[:]:
            try:
                await ctx.close()
            except Exception:
                pass
        self._all_contexts.clear()

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._initialized = False
        logger.info("[浏览器池] 已关闭")


async def simulate_human(page, scroll: bool = True):
    """
    模拟真实用户行为

    - 随机鼠标移动
    - 随机等待时间
    - 页面滚动
    """
    if not HAS_PLAYWRIGHT:
        return

    try:
        # 随机鼠标移动
        for _ in range(random.randint(2, 5)):
            x = random.randint(100, 800)
            y = random.randint(100, 600)
            await page.mouse.move(x, y, steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.1, 0.3))

        # 随机滚动
        if scroll:
            for _ in range(random.randint(2, 4)):
                delta = random.randint(200, 600)
                await page.mouse.wheel(0, delta)
                await asyncio.sleep(random.uniform(0.5, 1.5))

        # 随机等待
        await asyncio.sleep(random.uniform(0.5, 2.0))
    except Exception:
        pass
