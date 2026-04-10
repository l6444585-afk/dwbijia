#!/usr/bin/env python3
"""
Playwright headless 补全缺失价格
直接渲染得物/京东/淘宝搜索页获取价格
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

WORKDIR = Path(__file__).parent
CACHE_FILE = WORKDIR / "merged_price_cache.json"
WS_FILE = WORKDIR / "websearch_results.json"


def load_data() -> tuple[dict, list]:
    with open(CACHE_FILE) as f:
        cache = json.load(f)
    with open(WS_FILE) as f:
        products = json.load(f)
    return cache, products


def save_cache(cache: dict) -> None:
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.replace(CACHE_FILE)


def extract_prices_from_text(text: str, min_price: float = 30) -> list[float]:
    """从页面文本提取价格"""
    prices = []
    for m in re.finditer(r"[¥￥]\s*(\d{2,5}(?:\.\d{1,2})?)", text):
        try:
            p = float(m.group(1))
            if min_price < p < 50000:
                prices.append(p)
        except (ValueError, TypeError):
            pass
    return prices


def search_dewu(page, keyword: str) -> float:
    """得物搜索"""
    try:
        url = f"https://m.dewu.com/search/result?keyword=李宁+{keyword}"
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # 等待商品卡片加载
        try:
            page.wait_for_selector('[class*="price"], [class*="Price"]', timeout=5000)
        except PwTimeout:
            pass

        text = page.content()
        # 从 JSON 数据中提取
        prices = []
        for m in re.finditer(r'"price"\s*[=:]\s*"?(\d+\.?\d*)"?', text):
            try:
                p = float(m.group(1))
                if p > 100000:
                    p = p / 100
                if 30 < p < 50000:
                    prices.append(p)
            except (ValueError, TypeError):
                pass

        # 从页面文本提取
        if not prices:
            prices = extract_prices_from_text(text, 50)

        return min(prices) if prices else 0
    except Exception as e:
        print(f"      [得物] {e}")
        return 0


def search_jd(page, keyword: str) -> float:
    """京东搜索"""
    try:
        url = f"https://so.m.jd.com/ware/search.action?keyword=李宁+{keyword}"
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        try:
            page.wait_for_selector('[class*="price"], .p-price', timeout=5000)
        except PwTimeout:
            pass

        text = page.content()
        prices = []

        # jdPrice JSON
        for m in re.finditer(r'"jdPrice"\s*:\s*"?(\d+\.?\d*)"?', text):
            try:
                p = float(m.group(1))
                if 30 < p < 50000:
                    prices.append(p)
            except (ValueError, TypeError):
                pass

        # 页面价格元素
        if not prices:
            price_els = page.query_selector_all('[class*="price"]')
            for el in price_els[:10]:
                txt = el.inner_text()
                for m in re.finditer(r"(\d{2,5}(?:\.\d{1,2})?)", txt):
                    try:
                        p = float(m.group(1))
                        if 30 < p < 50000:
                            prices.append(p)
                    except (ValueError, TypeError):
                        pass

        return min(prices) if prices else 0
    except Exception as e:
        print(f"      [京东] {e}")
        return 0


def search_taobao(page, keyword: str) -> float:
    """淘宝搜索"""
    try:
        url = f"https://s.m.taobao.com/h5?q=李宁+{keyword}"
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        text = page.content()
        prices = []

        for m in re.finditer(r'"priceWap"\s*:\s*"(\d+\.?\d*)"', text):
            try:
                p = float(m.group(1))
                if 30 < p < 50000:
                    prices.append(p)
            except (ValueError, TypeError):
                pass

        if not prices:
            for m in re.finditer(r'"price"\s*:\s*"(\d+\.?\d*)"', text):
                try:
                    p = float(m.group(1))
                    if 30 < p < 50000:
                        prices.append(p)
                except (ValueError, TypeError):
                    pass

        if not prices:
            prices = extract_prices_from_text(text, 50)

        return min(prices) if prices else 0
    except Exception as e:
        print(f"      [淘宝] {e}")
        return 0


def search_tmall(page, keyword: str) -> float:
    """天猫搜索"""
    try:
        url = f"https://list.tmall.com/search_product.htm?q=李宁+{keyword}"
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        text = page.content()
        prices = extract_prices_from_text(text, 50)
        return min(prices) if prices else 0
    except Exception as e:
        print(f"      [天猫] {e}")
        return 0


def main():
    cache, products = load_data()
    total = len(products)

    # 找所有需要补全的
    to_fill = []
    for item in products:
        spu = item["spu"]
        c = cache.get(spu, {})
        has_dewu = c.get("dewu", 0) > 0
        has_any = any(c.get(k, 0) > 0 for k in ["dewu", "taobao", "tmall", "jd", "pdd"])
        if not has_any or not has_dewu:
            to_fill.append(item)

    print(f"产品: {total} | 需补全: {len(to_fill)}")
    print("=" * 70)

    start = time.time()
    new_prices = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                       "Version/17.4 Mobile/15E148 Safari/604.1",
            viewport={"width": 375, "height": 812},
            locale="zh-CN",
        )
        page = ctx.new_page()

        for i, item in enumerate(to_fill):
            spu = item["spu"]
            name = item["name"]
            existing = cache.get(spu, {
                "dewu": 0, "taobao": 0, "tmall": 0,
                "jd": 0, "pdd": 0, "lowest": 0,
                "shihuo_url": "", "source": "",
            })

            print(f"\n[{i+1}/{len(to_fill)}] {spu} {name}")

            search_term = name.strip()
            gained = 0

            # 搜得物
            if not existing.get("dewu", 0):
                price = search_dewu(page, search_term)
                if not price:
                    price = search_dewu(page, spu)
                if price:
                    existing["dewu"] = price
                    gained += 1
                    print(f"    [得物] ¥{price:.0f} NEW")
                time.sleep(0.5)

            # 搜京东
            if not existing.get("jd", 0):
                price = search_jd(page, search_term)
                if price:
                    existing["jd"] = price
                    gained += 1
                    print(f"    [京东] ¥{price:.0f} NEW")
                time.sleep(0.5)

            # 搜淘宝
            if not existing.get("taobao", 0):
                price = search_taobao(page, search_term)
                if price:
                    existing["taobao"] = price
                    gained += 1
                    print(f"    [淘宝] ¥{price:.0f} NEW")
                time.sleep(0.5)

            # 搜天猫 (仅对完全无价格的)
            has_any = any(existing.get(k, 0) > 0 for k in ["dewu", "taobao", "tmall", "jd", "pdd"])
            if not has_any and not existing.get("tmall", 0):
                price = search_tmall(page, search_term)
                if price:
                    existing["tmall"] = price
                    gained += 1
                    print(f"    [天猫] ¥{price:.0f} NEW")
                time.sleep(0.5)

            if gained > 0:
                new_prices += gained
                src = existing.get("source", "")
                existing["source"] = f"{src}+playwright" if src else "playwright"

            # 更新 lowest
            all_p = [existing.get(k, 0) for k in ["dewu", "taobao", "tmall", "jd", "pdd"]
                     if existing.get(k, 0) > 0]
            if all_p:
                existing["lowest"] = min(all_p)

            # 打印汇总
            parts = []
            for k, label in [("dewu", "得物"), ("taobao", "淘宝"), ("tmall", "天猫"),
                              ("jd", "京东"), ("pdd", "拼多多")]:
                v = existing.get(k, 0)
                if v > 0:
                    parts.append(f"{label}¥{v:.0f}")
            print(f"    结果: {' | '.join(parts) if parts else '仍无数据'}")

            cache[spu] = existing

        browser.close()

    elapsed = time.time() - start
    save_cache(cache)

    # 最终统计
    has_dewu = sum(1 for p in products if cache.get(p["spu"], {}).get("dewu", 0) > 0)
    has_any = sum(1 for p in products
                  if any(cache.get(p["spu"], {}).get(k, 0) > 0
                         for k in ["dewu", "taobao", "tmall", "jd", "pdd"]))

    print(f"\n{'=' * 70}")
    print(f"  耗时: {elapsed:.1f}秒")
    print(f"  新增价格: {new_prices} 条")
    print(f"  得物: {has_dewu}/{total} ({has_dewu/total*100:.0f}%)")
    print(f"  有价格: {has_any}/{total} ({has_any/total*100:.0f}%)")
    print(f"  无价格: {total - has_any}/{total}")

    # 生成 Excel
    try:
        import pandas as pd
        rows = []
        for item in products:
            spu = item["spu"]
            c = cache.get(spu, {})
            all_p = [c.get(k, 0) for k in ["dewu", "taobao", "tmall", "jd", "pdd"] if c.get(k, 0) > 0]
            net_low = min(all_p) if all_p else 0
            final = item.get("final_price", 0)
            rows.append({
                "SPU": spu, "分类": item.get("category", ""), "产品名称": item["name"],
                "淘宝前台价": item.get("front_price", 0), "淘宝到手价": final,
                "得物价格": c.get("dewu", 0) or "",
                "价差(到手-得物)": f"{final - c['dewu']:+.0f}" if c.get("dewu", 0) > 0 and final > 0 else "",
                "淘宝(其他渠道)": c.get("taobao", 0) or "",
                "天猫价": c.get("tmall", 0) or "",
                "京东价": c.get("jd", 0) or "",
                "拼多多价": c.get("pdd", 0) or "",
                "全网最低": net_low or "",
                "价差(到手-最低)": f"{final - net_low:+.0f}" if net_low > 0 and final > 0 else "",
            })
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        xlsx = WORKDIR / f"李宁全渠道价格对比_完整版_{ts}.xlsx"
        pd.DataFrame(rows).to_excel(xlsx, index=False, engine="openpyxl")
        print(f"  Excel: {xlsx.name}")
    except Exception as e:
        print(f"  Excel: {e}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
