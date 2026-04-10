#!/usr/bin/env python3
"""
Stealth Playwright 全网价格爬取 v2
用真实浏览器指纹 + 用户行为模拟绕过反爬
"""
from __future__ import annotations
import json, re, time, random
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

WORKDIR = Path(__file__).parent
CACHE_FILE = WORKDIR / "merged_price_cache.json"
WS_FILE = WORKDIR / "websearch_results.json"

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = {runtime: {}};
"""

def load_data():
    with open(CACHE_FILE) as f: cache = json.load(f)
    with open(WS_FILE) as f: products = json.load(f)
    return cache, products

def save_cache(cache):
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f: json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.replace(CACHE_FILE)

def human_delay():
    time.sleep(random.uniform(1.5, 3.0))

def scroll_page(page):
    for _ in range(3):
        page.mouse.wheel(0, random.randint(300, 600))
        time.sleep(random.uniform(0.3, 0.8))

def extract_jd_prices(page, keyword):
    """京东PC版搜索"""
    try:
        page.goto(f"https://search.jd.com/Search?keyword={keyword}&enc=utf-8",
                  timeout=20000, wait_until="domcontentloaded")
        time.sleep(2)
        scroll_page(page)
        time.sleep(1)

        prices = []
        els = page.query_selector_all('.p-price strong i, .p-price span.price, [class*="price"] i')
        for el in els[:15]:
            try:
                txt = el.inner_text().strip()
                p = float(re.sub(r'[^\d.]', '', txt))
                if 30 < p < 50000:
                    prices.append(p)
            except: pass

        if not prices:
            text = page.content()
            for m in re.finditer(r'"p"\s*:\s*"(\d+\.\d+)"', text):
                try:
                    p = float(m.group(1))
                    if 30 < p < 50000: prices.append(p)
                except: pass

        return min(prices) if prices else 0
    except Exception as e:
        print(f"      [京东PC] {e}")
        return 0

def extract_tb_prices(page, keyword):
    """淘宝PC搜索"""
    try:
        page.goto(f"https://s.taobao.com/search?q={keyword}",
                  timeout=20000, wait_until="domcontentloaded")
        time.sleep(3)
        scroll_page(page)
        time.sleep(1)

        prices = []
        # 淘宝价格在span里
        els = page.query_selector_all('[class*="priceInt"], [class*="price-sale"], .price strong')
        for el in els[:15]:
            try:
                txt = el.inner_text().strip()
                p = float(re.sub(r'[^\d.]', '', txt))
                if 30 < p < 50000: prices.append(p)
            except: pass

        if not prices:
            text = page.content()
            for m in re.finditer(r'"view_price"\s*:\s*"(\d+\.?\d*)"', text):
                try:
                    p = float(m.group(1))
                    if 30 < p < 50000: prices.append(p)
                except: pass

        return min(prices) if prices else 0
    except Exception as e:
        print(f"      [淘宝PC] {e}")
        return 0

def extract_pdd_prices(page, keyword):
    """拼多多搜索"""
    try:
        page.goto(f"https://mobile.yangkeduo.com/search_result.html?search_key={keyword}",
                  timeout=20000, wait_until="domcontentloaded")
        time.sleep(3)
        scroll_page(page)

        prices = []
        text = page.content()
        for m in re.finditer(r'"priceDisplay"\s*:\s*"(\d+\.?\d*)"', text):
            try:
                p = float(m.group(1))
                if 30 < p < 50000: prices.append(p)
            except: pass

        if not prices:
            for m in re.finditer(r'"price"\s*:\s*(\d+)', text):
                try:
                    p = float(m.group(1)) / 100  # 拼多多价格可能以分
                    if p < 30: p = float(m.group(1))
                    if 30 < p < 50000: prices.append(p)
                except: pass

        return min(prices) if prices else 0
    except Exception as e:
        print(f"      [拼多多] {e}")
        return 0

def extract_dewu_prices(page, keyword):
    """得物搜索 - 用PC版"""
    try:
        page.goto(f"https://www.poizon.com/search?keyword={keyword}",
                  timeout=20000, wait_until="domcontentloaded")
        time.sleep(4)
        scroll_page(page)
        time.sleep(2)

        prices = []
        # 得物PC版价格
        els = page.query_selector_all('[class*="price"], [class*="Price"]')
        for el in els[:15]:
            try:
                txt = el.inner_text().strip()
                for m in re.finditer(r'(\d{2,5})', txt):
                    p = float(m.group(1))
                    if 50 < p < 50000: prices.append(p)
            except: pass

        if not prices:
            text = page.content()
            for m in re.finditer(r'"price"\s*[=:]\s*(\d+)', text):
                try:
                    p = float(m.group(1))
                    if p > 100000: p = p / 100
                    if 50 < p < 50000: prices.append(p)
                except: pass

        return min(prices) if prices else 0
    except Exception as e:
        print(f"      [得物PC] {e}")
        return 0

def extract_shihuo_prices_by_name(page, keyword):
    """识货搜索+详情页获取全渠道"""
    result = {"dewu": 0, "taobao": 0, "tmall": 0, "jd": 0, "pdd": 0}
    try:
        page.goto(f"https://www.shihuo.cn/search?k=李宁+{keyword}", timeout=15000)
        time.sleep(2)

        text = page.content()
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.DOTALL)
        if not m: return result

        data = json.loads(m.group(1))
        items = data.get("props",{}).get("pageProps",{}).get("data",{}).get("data",{}).get("list",[])

        # 找李宁的
        best = None
        for item in items:
            title = item.get("title","")
            brand = item.get("brand_name","").lower()
            if "李宁" in title or "li-ning" in brand or "lining" in brand:
                best = item
                break

        if not best: return result

        gid = best.get("goods_id","")
        sid = best.get("style_id","")
        if not gid: return result

        print(f"      [识货] 匹配: {best['title'][:30]}")

        # 访问详情页
        page.goto(f"https://www.shihuo.cn/page/pcGoodsDetail?goodsId={gid}&styleId={sid}", timeout=15000)
        time.sleep(2)

        text2 = page.content()
        m2 = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text2, re.DOTALL)
        if not m2: return result

        detail_text = m2.group(1)

        # 提取渠道价格
        patterns = {
            "dewu": r"得物渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元",
            "taobao": r"淘宝渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元",
            "tmall": r"天猫渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元",
            "jd": r"京东渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元",
            "pdd": r"拼多多渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元",
        }
        for platform, pat in patterns.items():
            match = re.search(pat, detail_text)
            if match:
                try:
                    p = float(match.group(1))
                    if 10 < p < 50000:
                        result[platform] = p
                except: pass

        return result
    except Exception as e:
        print(f"      [识货] {e}")
        return result


def main():
    cache, products = load_data()

    # 备份
    with open(CACHE_FILE.with_suffix(".bak"), "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    total = len(products)
    to_fill = []
    for item in products:
        spu = item["spu"]
        c = cache.get(spu, {})
        src = c.get("source", "")
        has_dewu = c.get("dewu", 0) > 0
        is_fallback = "excel_ref" in src
        if is_fallback or not has_dewu:
            to_fill.append(item)

    print(f"产品: {total} | 需爬取: {len(to_fill)}")
    print("=" * 70)

    start = time.time()
    new_prices = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()

        for i, item in enumerate(to_fill):
            spu = item["spu"]
            name = item["name"]
            category = item.get("category", "")
            search_kw = f"李宁 {name}"

            existing = cache.get(spu, {
                "dewu": 0, "taobao": 0, "tmall": 0,
                "jd": 0, "pdd": 0, "lowest": 0,
                "shihuo_url": "", "source": "",
            })

            old_count = sum(1 for k in ["dewu","taobao","tmall","jd","pdd"] if existing.get(k,0) > 0)
            is_fallback = "excel_ref" in existing.get("source", "")

            print(f"\n[{i+1}/{len(to_fill)}] {spu} {name} ({'兜底需替换' if is_fallback else '缺得物'})")

            gained = 0
            sources = []

            # === 1. 识货全渠道(最有效) ===
            shihuo = extract_shihuo_prices_by_name(page, name)
            human_delay()
            for platform in ["dewu", "taobao", "tmall", "jd", "pdd"]:
                if shihuo.get(platform, 0) > 0:
                    if is_fallback or existing.get(platform, 0) == 0:
                        existing[platform] = shihuo[platform]
                        gained += 1
                        sources.append(f"识货→{platform}")
                        print(f"    [识货→{platform}] ¥{shihuo[platform]:.0f}")

            # === 2. 京东 ===
            if existing.get("jd", 0) == 0 or is_fallback:
                jd_price = extract_jd_prices(page, search_kw)
                human_delay()
                if jd_price > 0:
                    existing["jd"] = jd_price
                    gained += 1
                    sources.append("京东PC")
                    print(f"    [京东] ¥{jd_price:.0f}")

            # === 3. 淘宝 ===
            if existing.get("taobao", 0) == 0 or is_fallback:
                tb_price = extract_tb_prices(page, search_kw)
                human_delay()
                if tb_price > 0:
                    existing["taobao"] = tb_price
                    gained += 1
                    sources.append("淘宝PC")
                    print(f"    [淘宝] ¥{tb_price:.0f}")

            # === 4. 拼多多 ===
            if existing.get("pdd", 0) == 0 or is_fallback:
                pdd_price = extract_pdd_prices(page, search_kw)
                human_delay()
                if pdd_price > 0:
                    existing["pdd"] = pdd_price
                    gained += 1
                    sources.append("拼多多")
                    print(f"    [拼多多] ¥{pdd_price:.0f}")

            # === 5. 得物 ===
            if existing.get("dewu", 0) == 0:
                dw = extract_dewu_prices(page, search_kw)
                human_delay()
                if dw > 0:
                    existing["dewu"] = dw
                    gained += 1
                    sources.append("得物PC")
                    print(f"    [得物] ¥{dw:.0f}")

            if gained > 0:
                new_prices += gained
                existing["source"] = "+".join(sources)
            elif is_fallback:
                existing["source"] = "excel_ref(全网搜索无结果,EC专供)"

            # 更新 lowest
            all_p = [existing.get(k,0) for k in ["dewu","taobao","tmall","jd","pdd"] if existing.get(k,0) > 0]
            if all_p: existing["lowest"] = min(all_p)

            # 汇总
            parts = []
            for k, label in [("dewu","得物"),("taobao","淘宝"),("tmall","天猫"),("jd","京东"),("pdd","拼多多")]:
                v = existing.get(k,0)
                if v > 0: parts.append(f"{label}¥{v:.0f}")
            print(f"    结果: {' | '.join(parts) if parts else '仍无数据'}")
            print(f"    来源: {existing.get('source','')}")

            cache[spu] = existing

        browser.close()

    elapsed = time.time() - start
    save_cache(cache)

    # 统计
    has_dewu = sum(1 for p in products if cache.get(p["spu"],{}).get("dewu",0) > 0)
    has_any = sum(1 for p in products if any(cache.get(p["spu"],{}).get(k,0)>0 for k in ["dewu","taobao","tmall","jd","pdd"]))
    real_src = sum(1 for p in products if "excel_ref" not in cache.get(p["spu"],{}).get("source",""))

    print(f"\n{'='*70}")
    print(f"  耗时: {elapsed:.0f}秒 | 新增: {new_prices}条")
    print(f"  得物: {has_dewu}/{total} | 有价格: {has_any}/{total}")
    print(f"  真实数据: {real_src}/{total} | 兜底: {total-real_src}/{total}")

    # Excel
    import pandas as pd
    rows = []
    for item in products:
        spu = item["spu"]; c = cache.get(spu, {})
        all_p = [c.get(k,0) for k in ["dewu","taobao","tmall","jd","pdd"] if c.get(k,0) > 0]
        net_low = min(all_p) if all_p else 0
        final = item.get("final_price", 0)
        src = c.get("source","")
        if "excel_ref" in src: label = "⚠️兜底(EC专供)"
        else: label = "✅实际爬取"
        rows.append({
            "SPU": spu, "分类": item.get("category",""), "产品名称": item["name"],
            "淘宝前台价": item.get("front_price",0), "淘宝到手价": final,
            "得物价格": c.get("dewu",0) or "",
            "价差(到手-得物)": f"{final-c['dewu']:+.0f}" if c.get("dewu",0)>0 and final>0 else "",
            "淘宝价": c.get("taobao",0) or "", "天猫价": c.get("tmall",0) or "",
            "京东价": c.get("jd",0) or "", "拼多多价": c.get("pdd",0) or "",
            "全网最低": net_low or "",
            "价差(到手-最低)": f"{final-net_low:+.0f}" if net_low>0 and final>0 else "",
            "数据来源": label, "来源详情": src,
        })
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    xlsx = f"李宁全渠道价格对比_完整版_{ts}.xlsx"
    pd.DataFrame(rows).to_excel(xlsx, index=False, engine="openpyxl")
    print(f"  Excel: {xlsx}")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
