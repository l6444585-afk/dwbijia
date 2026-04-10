#!/usr/bin/env python3
"""
全平台实时爬取 v4 — 每个产品都去得物/淘宝/京东/拼多多搜
用 Playwright PC 版，每个搜索等足够久让 SPA 渲染
"""
from __future__ import annotations
import json, re, time, random
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

WORKDIR = Path(__file__).parent

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
  parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);
"""

def extract_numbers(text: str, min_v: float = 30, max_v: float = 50000) -> list[float]:
    """提取文本中的价格数字"""
    prices = []
    for m in re.finditer(r'(\d{2,5}(?:\.\d{1,2})?)', text):
        try:
            p = float(m.group(1))
            if min_v < p < max_v:
                prices.append(p)
        except:
            pass
    return prices


def search_dewu(page, keyword: str) -> float:
    """得物PC搜索 - poizon.com"""
    try:
        page.goto(f"https://www.poizon.com/search?keyword={keyword}",
                  timeout=25000, wait_until="networkidle")
        # 等 SPA 渲染
        time.sleep(5)
        # 滚动触发懒加载
        for _ in range(3):
            page.mouse.wheel(0, random.randint(200, 500))
            time.sleep(0.5)
        time.sleep(2)

        prices = []
        # 方法1: 找价格元素
        for sel in ['[class*="price"]', '[class*="Price"]', '[class*="amount"]']:
            els = page.query_selector_all(sel)
            for el in els[:20]:
                try:
                    txt = el.inner_text().strip()
                    nums = extract_numbers(txt, 50)
                    prices.extend(nums)
                except:
                    pass

        # 方法2: 从页面源码提取
        if not prices:
            content = page.content()
            # 得物价格格式
            for pat in [
                r'"price"\s*:\s*(\d+)',
                r'"minPrice"\s*:\s*(\d+)',
                r'"tradePrice"\s*:\s*(\d+)',
                r'"soldPrice"\s*:\s*(\d+)',
            ]:
                for m in re.finditer(pat, content):
                    try:
                        p = float(m.group(1))
                        if p > 100000: p = p / 100  # 分→元
                        if 50 < p < 50000:
                            prices.append(p)
                    except:
                        pass

        return min(prices) if prices else 0
    except Exception as e:
        return 0


def search_jd(page, keyword: str) -> float:
    """京东PC搜索"""
    try:
        page.goto(f"https://search.jd.com/Search?keyword={keyword}&enc=utf-8",
                  timeout=20000, wait_until="domcontentloaded")
        time.sleep(3)
        page.mouse.wheel(0, 400)
        time.sleep(2)

        prices = []
        # 京东价格在 .p-price 里
        els = page.query_selector_all('.p-price strong i')
        for el in els[:10]:
            try:
                p = float(el.inner_text().strip())
                if 30 < p < 50000: prices.append(p)
            except: pass

        if not prices:
            content = page.content()
            for m in re.finditer(r'"p"\s*:\s*"(\d+\.\d+)"', content):
                try:
                    p = float(m.group(1))
                    if 30 < p < 50000: prices.append(p)
                except: pass

        return min(prices) if prices else 0
    except:
        return 0


def search_taobao(page, keyword: str) -> float:
    """淘宝PC搜索"""
    try:
        page.goto(f"https://s.taobao.com/search?q={keyword}",
                  timeout=20000, wait_until="domcontentloaded")
        time.sleep(4)
        page.mouse.wheel(0, 500)
        time.sleep(2)

        prices = []
        content = page.content()
        for pat in [r'"view_price"\s*:\s*"(\d+\.?\d*)"',
                    r'"price"\s*:\s*"(\d+\.?\d*)"',
                    r'"priceWap"\s*:\s*"(\d+\.?\d*)"']:
            for m in re.finditer(pat, content):
                try:
                    p = float(m.group(1))
                    if 30 < p < 50000: prices.append(p)
                except: pass

        if not prices:
            els = page.query_selector_all('[class*="price"] span, [class*="priceInt"]')
            for el in els[:10]:
                try:
                    nums = extract_numbers(el.inner_text(), 30)
                    prices.extend(nums)
                except: pass

        return min(prices) if prices else 0
    except:
        return 0


def search_pdd(page, keyword: str) -> float:
    """拼多多移动版搜索"""
    try:
        page.goto(f"https://mobile.yangkeduo.com/search_result.html?search_key={keyword}",
                  timeout=20000, wait_until="domcontentloaded")
        time.sleep(4)
        page.mouse.wheel(0, 400)
        time.sleep(2)

        prices = []
        content = page.content()
        for pat in [r'"priceDisplay"\s*:\s*"(\d+\.?\d*)"',
                    r'"normalPrice"\s*:\s*(\d+)',
                    r'"marketPrice"\s*:\s*(\d+)']:
            for m in re.finditer(pat, content):
                try:
                    p = float(m.group(1))
                    if p > 10000: p = p / 100
                    if 30 < p < 50000: prices.append(p)
                except: pass

        return min(prices) if prices else 0
    except:
        return 0


def search_shihuo_detail(session, url: str) -> dict:
    """识货详情页全渠道价格"""
    import requests
    result = {"dewu": 0, "taobao": 0, "tmall": 0, "jd": 0, "pdd": 0}
    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200: return result
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
        if not m: return result
        text = m.group(1)
        for platform, pat in [
            ("dewu", r"得物渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元"),
            ("taobao", r"淘宝渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元"),
            ("tmall", r"天猫渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元"),
            ("jd", r"京东渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元"),
            ("pdd", r"拼多多渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元"),
        ]:
            match = re.search(pat, text)
            if match:
                try:
                    p = float(match.group(1))
                    if 10 < p < 50000: result[platform] = p
                except: pass
        return result
    except:
        return result


def main():
    import requests as req

    with open(WORKDIR / "websearch_results.json") as f:
        products = json.load(f)
    with open(WORKDIR / "spu_shihuo_mapping.json") as f:
        mapping = json.load(f)

    total = len(products)
    cache = {}
    session = req.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    })

    print(f"=== 全平台实时爬取 {total} 个产品 ===")
    print("策略: 识货详情→得物→京东→淘宝→拼多多")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="zh-CN", timezone_id="Asia/Shanghai",
        )
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()

        start = time.time()

        for i, item in enumerate(products):
            spu = item["spu"]
            name = item["name"]
            cat = item.get("category", "")
            final = item.get("final_price", 0)
            front = item.get("front_price", 0)
            kw = f"李宁 {name}"

            print(f"\n[{i+1}/{total}] {spu} {name} ({cat})")

            prices = {"dewu": 0, "taobao": 0, "tmall": 0, "jd": 0, "pdd": 0}
            sources = []

            # === 1. 识货详情页(有映射的) ===
            info = mapping.get(spu, {})
            shihuo_url = info.get("url", "")
            if shihuo_url:
                sh = search_shihuo_detail(session, shihuo_url)
                for k in ["dewu", "taobao", "tmall", "jd", "pdd"]:
                    if sh.get(k, 0) > 0:
                        prices[k] = sh[k]
                if any(sh.get(k,0) > 0 for k in prices):
                    sources.append("识货")
                time.sleep(0.3)

            # === 2. 得物搜索(所有产品都试) ===
            if prices["dewu"] == 0:
                dw = search_dewu(page, kw)
                if dw == 0:
                    dw = search_dewu(page, f"李宁 {spu}")
                if dw > 0:
                    prices["dewu"] = dw
                    sources.append("得物")
                    print(f"    [得物] ¥{dw:.0f}")
                time.sleep(random.uniform(1, 2))

            # === 3. 京东搜索(缺的补) ===
            if prices["jd"] == 0:
                jd = search_jd(page, kw)
                if jd > 0:
                    prices["jd"] = jd
                    sources.append("京东")
                    print(f"    [京东] ¥{jd:.0f}")
                time.sleep(random.uniform(1, 2))

            # === 4. 淘宝搜索(缺的补) ===
            if prices["taobao"] == 0 and prices["tmall"] == 0:
                tb = search_taobao(page, kw)
                if tb > 0:
                    prices["taobao"] = tb
                    sources.append("淘宝")
                    print(f"    [淘宝] ¥{tb:.0f}")
                time.sleep(random.uniform(1, 2))

            # === 5. 拼多多搜索(缺的补) ===
            if prices["pdd"] == 0:
                pdd = search_pdd(page, kw)
                if pdd > 0:
                    prices["pdd"] = pdd
                    sources.append("拼多多")
                    print(f"    [拼多多] ¥{pdd:.0f}")
                time.sleep(random.uniform(1, 2))

            # === 6. 兜底 ===
            has_any = any(prices[k] > 0 for k in prices)
            if not has_any and final > 0:
                prices["taobao"] = final
                prices["tmall"] = front if front > 0 else 0
                sources.append("⚠️EC专供")

            # 组装
            all_p = [prices[k] for k in prices if prices[k] > 0]
            source_str = "+".join(sources) if sources else "无数据"

            cache[spu] = {
                **prices,
                "lowest": min(all_p) if all_p else 0,
                "shihuo_url": shihuo_url,
                "source": source_str,
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }

            parts = []
            for k, l in [("dewu","得物"),("taobao","淘宝"),("tmall","天猫"),("jd","京东"),("pdd","拼多多")]:
                if prices[k] > 0: parts.append(f"{l}¥{prices[k]:.0f}")
            print(f"    {' | '.join(parts) if parts else '无数据'}")
            print(f"    来源: {source_str}")

        browser.close()

    elapsed = time.time() - start

    # 保存
    with open(WORKDIR / "merged_price_cache.json", "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    # Excel
    import pandas as pd
    rows = []
    for item in products:
        spu = item["spu"]; c = cache.get(spu, {})
        all_p = [c.get(k,0) for k in ["dewu","taobao","tmall","jd","pdd"] if c.get(k,0)>0]
        net_low = min(all_p) if all_p else 0
        final = item.get("final_price", 0)
        src = c.get("source","")
        rows.append({
            "SPU": spu, "分类": item.get("category",""), "产品名称": item["name"],
            "淘宝前台价": item.get("front_price",0), "淘宝到手价": final,
            "得物价格": c.get("dewu",0) or "",
            "价差(到手-得物)": f"{final-c['dewu']:+.0f}" if c.get("dewu",0)>0 and final>0 else "",
            "淘宝价": c.get("taobao",0) or "", "天猫价": c.get("tmall",0) or "",
            "京东价": c.get("jd",0) or "", "拼多多价": c.get("pdd",0) or "",
            "全网最低": net_low or "",
            "价差(到手-最低)": f"{final-net_low:+.0f}" if net_low>0 and final>0 else "",
            "数据来源": "⚠️EC专供" if "⚠️" in src else "✅实时",
            "来源详情": src, "更新时间": c.get("updated",""),
        })

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    xlsx = WORKDIR / f"李宁全渠道价格对比_完整版_{ts}.xlsx"
    pd.DataFrame(rows).to_excel(xlsx, index=False, engine="openpyxl")

    has_dewu = sum(1 for p in products if cache.get(p["spu"],{}).get("dewu",0)>0)
    has_any = sum(1 for p in products if any(cache.get(p["spu"],{}).get(k,0)>0 for k in ["dewu","taobao","tmall","jd","pdd"]))
    real_src = sum(1 for p in products if "⚠️" not in cache.get(p["spu"],{}).get("source",""))

    print(f"\n{'='*70}")
    print(f"  耗时: {elapsed:.0f}秒")
    print(f"  有价格: {has_any}/{total} | 得物: {has_dewu}/{total}")
    print(f"  ✅实时: {real_src}/{total} | ⚠️EC专供: {total-real_src}/{total}")
    print(f"  Excel: {xlsx.name}")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
