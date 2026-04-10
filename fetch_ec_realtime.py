#!/usr/bin/env python3
"""
Playwright 无头浏览器实时抓取全渠道价格
先访问首页建立 session，再搜索提取价格
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright, Page

WORKDIR = Path(__file__).parent
CACHE_FILE = WORKDIR / "merged_price_cache.json"
EXCEL_FILE = WORKDIR / "价格表-3.10-13日常大牌日.xlsx"


def load_cache() -> dict:
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def load_product_names() -> dict[str, str]:
    df = pd.read_excel(EXCEL_FILE, header=None)
    names = {}
    for idx in range(1, len(df)):
        row = df.iloc[idx]
        spu = str(row.iloc[0]).strip()
        name = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ""
        if spu and spu != "nan" and name:
            names[spu] = name
    return names


def extract_min_price(texts: list[str], floor: float = 10, ceil: float = 50000) -> float:
    """从文本列表中提取最低合理价格"""
    prices = []
    for t in texts:
        for m in re.finditer(r'(\d+(?:\.\d{1,2})?)', t):
            p = float(m.group(1))
            if floor < p < ceil:
                prices.append(p)
    return min(prices) if prices else 0


def search_jd(page: Page, keyword: str) -> float:
    """京东搜索"""
    try:
        page.goto(f"https://search.jd.com/Search?keyword={keyword}&enc=utf-8",
                  wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(2000)

        # 滚动触发懒加载
        page.evaluate("window.scrollBy(0, 500)")
        page.wait_for_timeout(1000)

        # 方法1: 价格元素
        els = page.query_selector_all(".p-price strong i, .p-price em")
        price_texts = []
        for el in els:
            t = el.inner_text().strip()
            if t:
                price_texts.append(t)
        if price_texts:
            p = extract_min_price(price_texts)
            if p > 0:
                return p

        # 方法2: 从 HTML 正则
        content = page.content()
        # JD 商品价格 JSON
        matches = re.findall(r'"p":"(\d+\.\d+)"', content)
        if matches:
            valid = [float(m) for m in matches if 10 < float(m) < 50000]
            if valid:
                return min(valid)

        # 方法3: 任何价格元素
        all_prices = re.findall(r'class="p-price"[^>]*>.*?(\d+\.\d{2})', content, re.DOTALL)
        if all_prices:
            valid = [float(p) for p in all_prices if 10 < float(p) < 50000]
            if valid:
                return min(valid)
    except Exception:
        pass
    return 0


def search_dewu(page: Page, keyword: str) -> float:
    """得物搜索"""
    try:
        page.goto(f"https://www.dewu.com/search/result?keyword={keyword}",
                  wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(3000)

        content = page.content()

        # 从 NEXT_DATA 提取
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', content, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                items = (data.get("props", {}).get("pageProps", {})
                         .get("data", {}).get("productList", []))
                for item in items:
                    price = item.get("price", 0)
                    if price > 0:
                        # 得物价格单位可能是分
                        p = price / 100 if price > 50000 else price
                        if 10 < p < 50000:
                            return p
            except json.JSONDecodeError:
                pass

        # 从页面提取价格
        price_els = page.query_selector_all('[class*="price"], [class*="Price"]')
        for el in price_els:
            t = el.inner_text()
            m = re.search(r'[¥￥]?\s*(\d+(?:\.\d+)?)', t)
            if m:
                p = float(m.group(1))
                if 10 < p < 50000:
                    return p
    except Exception:
        pass
    return 0


def search_pdd(page: Page, keyword: str) -> float:
    """拼多多搜索"""
    try:
        page.goto(f"https://mobile.yangkeduo.com/search_result.html?search_key={keyword}",
                  wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(3000)

        content = page.content()

        # 从页面 JSON 提取
        for pattern in [
            r'"priceDisplay":"(\d+(?:\.\d+)?)"',
            r'"normalPrice":(\d+)',
            r'"min_group_price":(\d+)',
            r'"price":"?(\d+(?:\.\d+)?)"?',
        ]:
            matches = re.findall(pattern, content)
            for ps in matches:
                p = float(ps)
                if p > 10000:
                    p = p / 100
                if 10 < p < 50000:
                    return p

        # 从 DOM 提取
        price_els = page.query_selector_all('[class*="price"]')
        for el in price_els:
            t = el.inner_text()
            m = re.search(r'(\d+(?:\.\d+)?)', t)
            if m:
                p = float(m.group(1))
                if 10 < p < 50000:
                    return p
    except Exception:
        pass
    return 0


def search_taobao(page: Page, keyword: str) -> float:
    """淘宝搜索"""
    try:
        page.goto(f"https://s.taobao.com/search?q={keyword}",
                  wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(3000)

        content = page.content()

        # 从搜索结果提取价格
        prices = re.findall(r'"priceShow":"(\d+(?:\.\d+)?)"', content)
        if not prices:
            prices = re.findall(r'"price_show":"(\d+(?:\.\d+)?)"', content)
        if not prices:
            prices = re.findall(r'"view_price":"(\d+(?:\.\d+)?)"', content)
        if prices:
            valid = [float(p) for p in prices if 10 < float(p) < 50000]
            if valid:
                return min(valid)

        # DOM 价格
        price_els = page.query_selector_all('[class*="priceInt"], [class*="price"]')
        for el in price_els:
            t = el.inner_text()
            m = re.search(r'(\d+(?:\.\d+)?)', t)
            if m:
                p = float(m.group(1))
                if 10 < p < 50000:
                    return p
    except Exception:
        pass
    return 0


def init_session(page: Page, url: str, name: str):
    """访问首页建立 cookie/session"""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)
        print(f"  ✓ {name} session 已建立")
    except Exception as e:
        print(f"  ✗ {name} session 失败: {e}")


def main():
    cache = load_cache()
    product_names = load_product_names()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 所有需要更新的产品（EC专供款）
    ec_spus = [
        spu for spu, data in cache.items()
        if not data.get("shihuo_url")
    ]

    print(f"需实时抓取: {len(ec_spus)} 个 EC 专供款")
    print("=" * 70)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        # PC 端 context（京东、得物）
        pc_ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )

        # 移动端 context（拼多多、淘宝）
        mobile_ctx = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            locale="zh-CN",
        )

        pc_page = pc_ctx.new_page()
        mobile_page = mobile_ctx.new_page()

        # 先初始化各平台 session
        print("初始化平台 session...")
        init_session(pc_page, "https://www.jd.com", "京东")
        init_session(pc_page, "https://www.dewu.com", "得物")
        init_session(mobile_page, "https://mobile.yangkeduo.com", "拼多多")
        init_session(mobile_page, "https://m.taobao.com", "淘宝")
        print("=" * 70)

        updated = 0
        for i, spu in enumerate(ec_spus):
            product_name = product_names.get(spu, spu)
            keyword = f"李宁 {product_name}"

            print(f"  [{i+1:2d}/{len(ec_spus)}] {spu:12s} {product_name:12s}", end="", flush=True)

            # 搜索各平台
            dewu = search_dewu(pc_page, keyword)
            jd = search_jd(pc_page, keyword)
            pdd = search_pdd(mobile_page, keyword)
            taobao = search_taobao(mobile_page, keyword)

            # 更新缓存
            new_prices = {}
            if dewu > 0:
                new_prices["dewu"] = dewu
            if jd > 0:
                new_prices["jd"] = jd
            if pdd > 0:
                new_prices["pdd"] = pdd
            if taobao > 0:
                new_prices["taobao"] = taobao

            if new_prices:
                cache[spu].update(new_prices)
                all_p = [v for k, v in cache[spu].items()
                         if k in ["dewu", "taobao", "tmall", "jd", "pdd"]
                         and isinstance(v, (int, float)) and v > 0]
                cache[spu]["lowest"] = min(all_p) if all_p else 0
                cache[spu]["updated"] = now
                cache[spu]["source"] = f"✅实时({now})"
                updated += 1

                parts = []
                for k, label in [("dewu", "得物"), ("taobao", "淘宝"), ("tmall", "天猫"), ("jd", "京东"), ("pdd", "拼多多")]:
                    v = cache[spu].get(k, 0)
                    if isinstance(v, (int, float)) and v > 0:
                        parts.append(f"{label}¥{v:.0f}")
                print(f"  ✅ {' | '.join(parts)}")
            else:
                cache[spu]["updated"] = now
                cache[spu]["source"] = f"⚠️EC专供(全网无此款,更新{now})"
                print(f"  ⚠️ 全网无此款")

            time.sleep(0.5)

        browser.close()

    save_cache(cache)

    print(f"\n{'=' * 70}")
    print(f"  完成: {updated}/{len(ec_spus)} 个找到外部渠道价格")
    print(f"  缓存时间戳: {now}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
