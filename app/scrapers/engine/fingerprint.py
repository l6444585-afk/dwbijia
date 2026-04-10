"""
浏览器指纹随机化生成器

- 生成真实的浏览器指纹组合
- 每次请求使用不同的指纹，避免被关联
- 覆盖: User-Agent, Viewport, WebGL, Canvas, 语言, 时区等
"""
import random
from dataclasses import dataclass


# 真实 User-Agent 库（Chrome/Safari/Edge 最新版本）
_DESKTOP_UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_MOBILE_UAS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; 22081212C) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_7_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
]

_DESKTOP_VIEWPORTS = [
    (1920, 1080), (1536, 864), (1440, 900), (1366, 768),
    (2560, 1440), (1680, 1050), (1280, 800), (1600, 900),
]

_MOBILE_VIEWPORTS = [
    (375, 812), (390, 844), (393, 873), (414, 896),
    (360, 780), (412, 915), (428, 926), (320, 568),
]

_LANGUAGES = [
    "zh-CN,zh;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9",
    "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "zh-CN,zh-TW;q=0.9,zh;q=0.8,en;q=0.7",
]

_TIMEZONES = ["Asia/Shanghai", "Asia/Chongqing", "Asia/Harbin", "Asia/Urumqi"]

_WEBGL_VENDORS = [
    "Google Inc. (NVIDIA)",
    "Google Inc. (Apple)",
    "Google Inc. (Intel)",
    "Google Inc. (AMD)",
]

_WEBGL_RENDERERS = [
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (Apple, Apple M1 Pro, OpenGL 4.1)",
    "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (AMD, AMD Radeon RX 6600 XT Direct3D11 vs_5_0 ps_5_0)",
    "Apple GPU",
    "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)",
]


@dataclass
class BrowserFingerprint:
    """浏览器指纹"""
    user_agent: str
    viewport_width: int
    viewport_height: int
    device_scale_factor: float
    is_mobile: bool
    language: str
    timezone: str
    webgl_vendor: str
    webgl_renderer: str
    platform: str
    hardware_concurrency: int
    device_memory: int

    @property
    def headers(self) -> dict:
        """生成对应的HTTP请求头"""
        h = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": self.language,
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        if "Chrome" in self.user_agent:
            major = "124"
            try:
                major = self.user_agent.split("Chrome/")[1].split(".")[0]
            except (IndexError, AttributeError):
                pass
            h["Sec-Ch-Ua"] = f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not-A.Brand";v="99"'
            h["Sec-Ch-Ua-Mobile"] = "?1" if self.is_mobile else "?0"
            h["Sec-Ch-Ua-Platform"] = f'"{self.platform}"'
        return h


class FingerprintGenerator:
    """指纹生成器"""

    @staticmethod
    def generate(mobile: bool = True) -> BrowserFingerprint:
        """生成一个随机的浏览器指纹"""
        if mobile:
            ua = random.choice(_MOBILE_UAS)
            vw, vh = random.choice(_MOBILE_VIEWPORTS)
            scale = random.choice([2.0, 3.0])
            platform = "Android" if "Android" in ua else "iPhone"
        else:
            ua = random.choice(_DESKTOP_UAS)
            vw, vh = random.choice(_DESKTOP_VIEWPORTS)
            scale = random.choice([1.0, 1.25, 1.5, 2.0])
            if "Macintosh" in ua:
                platform = "macOS"
            elif "Windows" in ua:
                platform = "Windows"
            else:
                platform = "Linux"

        return BrowserFingerprint(
            user_agent=ua,
            viewport_width=vw,
            viewport_height=vh,
            device_scale_factor=scale,
            is_mobile=mobile,
            language=random.choice(_LANGUAGES),
            timezone=random.choice(_TIMEZONES),
            webgl_vendor=random.choice(_WEBGL_VENDORS),
            webgl_renderer=random.choice(_WEBGL_RENDERERS),
            platform=platform,
            hardware_concurrency=random.choice([4, 8, 12, 16]),
            device_memory=random.choice([4, 8, 16]),
        )
