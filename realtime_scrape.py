#!/usr/bin/env python3
"""
全量实时价格爬取 — 所有37个产品全部重新抓最新价格
1. 有识货映射的 → 直接抓详情页提取全渠道实时价格
2. 没映射的 → Playwright 搜识货找到映射 → 抓详情页
3. 都找不到的 → 标记为EC专供
"""
from __future__ import annotations
import json, re, time, random
from datetime import datetime
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

WORKDIR = Path(__file__).parent

def parse_shihuo_detail(html: str) -> dict:
    """从识货详情页提取全渠道价格"""
    result = {"dewu": 0, "taobao": 0, "tmall": 0, "jd": 0, "pdd": 0}

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return result

    text = m.group(1)

    patterns = {
        "dewu": r"得物渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元",
        "taobao": r"淘宝渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元",
        "tmall": r"天猫渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元",
        "jd": r"京东渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元",
        "pdd": r"拼多多渠道[^，。]*?售价[为]?\s*(\d+(?:\.\d+)?)\s*元",
    }

    for platform, pat in patterns.items():
        match = re.search(pat, text)
        if match:
            try:
                p = float(match.group(1))
                if 10 < p < 50000:
                    result[platform] = p
            except (ValueError, TypeError):
                pass

    return result


def scrape_shihuo_url(url: str, session: requests.Session) -> dict:
    """用 requests 抓识货详情页"""
    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return {}
        return parse_shihuo_detail(r.text)
    except Exception as e:
        print(f"      请求失败: {e}")
        return {}


def playwright_find_shihuo_mapping(page, name: str) -> dict | None:
    """用 Playwright 在识货搜索找到商品映射"""
    try:
        page.goto(f"https://www.shihuo.cn/search?k=李宁+{name}", timeout=15000)
        time.sleep(2)

        text = page.content()
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.DOTALL)
        if not m:
            return None

        data = json.loads(m.group(1))
        items = data.get("props",{}).get("pageProps",{}).get("data",{}).get("data",{}).get("list",[])

        # 严格过滤：必须是李宁品牌 + 标题含关键词
        name_chars = set(name.replace(" ", ""))

        for item in items:
            title = item.get("title", "")
            brand = item.get("brand_name", "").lower()
            is_lining = "李宁" in title or "li-ning" in brand or "lining" in brand
            if not is_lining:
                continue

            # 计算匹配度
            title_chars = set(title)
            overlap = name_chars & title_chars
            score = len(overlap) / len(name_chars) if name_chars else 0

            if score >= 0.6:  # 严格阈值
                return {
                    "goods_id": item.get("goods_id", ""),
                    "style_id": item.get("style_id", ""),
                    "title": title,
                    "score": score,
                }

        return None
    except Exception as e:
        print(f"      识货搜索失败: {e}")
        return None


def main():
    # 加载数据
    with open(WORKDIR / "websearch_results.json") as f:
        products = json.load(f)
    with open(WORKDIR / "spu_shihuo_mapping.json") as f:
        mapping = json.load(f)

    total = len(products)
    print(f"=== 全量实时爬取 {total} 个产品 ===")
    print(f"有映射: {sum(1 for p in products if mapping.get(p['spu'],{}).get('url'))} | 无映射: {sum(1 for p in products if not mapping.get(p['spu'],{}).get('url'))}")
    print("=" * 70)

    # 全新缓存
    cache = {}

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html",
    })

    # 启动 Playwright 用于搜索无映射的产品
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
    )
    page = ctx.new_page()

    start = time.time()
    success = 0
    new_mappings = 0

    for i, item in enumerate(products):
        spu = item["spu"]
        name = item["name"]
        category = item.get("category", "")
        final_price = item.get("final_price", 0)
        front_price = item.get("front_price", 0)

        print(f"\n[{i+1}/{total}] {spu} {name} ({category})")

        prices = {}
        source = ""
        shihuo_url = ""

        # === 方法1: 已有映射 → 直接抓 ===
        info = mapping.get(spu, {})
        url = info.get("url", "")

        if url:
            print(f"    有映射 → 抓取识货详情页...")
            prices = scrape_shihuo_url(url, session)
            shihuo_url = url
            if any(prices.get(k, 0) > 0 for k in ["dewu", "taobao", "tmall", "jd", "pdd"]):
                source = "✅识货详情页(实时)"
            time.sleep(random.uniform(0.3, 0.8))

        # === 方法2: 无映射 → Playwright搜索识货 ===
        if not any(prices.get(k, 0) > 0 for k in ["dewu", "taobao", "tmall", "jd", "pdd"]):
            print(f"    无映射 → Playwright搜索识货...")
            match = playwright_find_shihuo_mapping(page, name)
            time.sleep(random.uniform(0.5, 1.0))

            if match and match.get("goods_id"):
                gid = match["goods_id"]
                sid = match["style_id"]
                detail_url = f"https://www.shihuo.cn/page/pcGoodsDetail?goodsId={gid}&styleId={sid}"
                print(f"    找到: {match['title'][:30]} (score={match['score']:.2f})")

                prices = scrape_shihuo_url(detail_url, session)
                shihuo_url = detail_url
                new_mappings += 1

                if any(prices.get(k, 0) > 0 for k in ["dewu", "taobao", "tmall", "jd", "pdd"]):
                    source = "✅识货搜索+详情页(实时)"
                    # 保存新映射
                    mapping[spu] = {"url": detail_url, "shihuo_name": match["title"]}

                time.sleep(random.uniform(0.3, 0.8))

        # === 方法3: 都失败 → 用Excel到手价兜底 ===
        if not any(prices.get(k, 0) > 0 for k in ["dewu", "taobao", "tmall", "jd", "pdd"]):
            if final_price > 0:
                prices["taobao"] = final_price
                if front_price > 0:
                    prices["tmall"] = front_price
                source = f"⚠️EC专供(淘宝到手¥{final_price:.0f},全网无此款)"
                print(f"    全网无结果 → EC专供兜底")

        # 组装缓存
        all_p = [prices.get(k, 0) for k in ["dewu", "taobao", "tmall", "jd", "pdd"] if prices.get(k, 0) > 0]

        cache[spu] = {
            "dewu": prices.get("dewu", 0),
            "taobao": prices.get("taobao", 0),
            "tmall": prices.get("tmall", 0),
            "jd": prices.get("jd", 0),
            "pdd": prices.get("pdd", 0),
            "lowest": min(all_p) if all_p else 0,
            "shihuo_url": shihuo_url,
            "source": source,
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        if any(prices.get(k, 0) > 0 for k in ["dewu", "taobao", "tmall", "jd", "pdd"]):
            success += 1

        # 打印
        parts = []
        for k, label in [("dewu","得物"),("taobao","淘宝"),("tmall","天猫"),("jd","京东"),("pdd","拼多多")]:
            v = prices.get(k, 0)
            if v > 0:
                parts.append(f"{label}¥{v:.0f}")
        print(f"    {' | '.join(parts) if parts else '无数据'}")
        print(f"    来源: {source}")

    browser.close()
    pw.stop()
    session.close()
    elapsed = time.time() - start

    # 保存
    with open(WORKDIR / "merged_price_cache.json", "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    with open(WORKDIR / "spu_shihuo_mapping.json", "w") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    # 生成 Excel
    import pandas as pd
    rows = []
    for item in products:
        spu = item["spu"]
        c = cache.get(spu, {})
        all_p = [c.get(k,0) for k in ["dewu","taobao","tmall","jd","pdd"] if c.get(k,0) > 0]
        net_low = min(all_p) if all_p else 0
        final = item.get("final_price", 0)
        src = c.get("source", "")

        rows.append({
            "SPU": spu, "分类": item.get("category",""), "产品名称": item["name"],
            "淘宝前台价": item.get("front_price",0), "淘宝到手价": final,
            "得物价格": c.get("dewu",0) or "",
            "价差(到手-得物)": f"{final-c['dewu']:+.0f}" if c.get("dewu",0)>0 and final>0 else "",
            "淘宝价": c.get("taobao",0) or "", "天猫价": c.get("tmall",0) or "",
            "京东价": c.get("jd",0) or "", "拼多多价": c.get("pdd",0) or "",
            "全网最低": net_low or "",
            "价差(到手-最低)": f"{final-net_low:+.0f}" if net_low>0 and final>0 else "",
            "数据来源": "⚠️EC专供" if "⚠️" in src else "✅实时爬取",
            "来源详情": src,
            "更新时间": c.get("updated", ""),
        })

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    xlsx = WORKDIR / f"李宁全渠道价格对比_完整版_{ts}.xlsx"
    pd.DataFrame(rows).to_excel(xlsx, index=False, engine="openpyxl")

    # 统计
    has_dewu = sum(1 for p in products if cache.get(p["spu"],{}).get("dewu",0) > 0)
    real_src = sum(1 for p in products if "⚠️" not in cache.get(p["spu"],{}).get("source",""))

    print(f"\n{'='*70}")
    print(f"  耗时: {elapsed:.0f}秒")
    print(f"  有价格: {success}/{total}")
    print(f"  得物: {has_dewu}/{total}")
    print(f"  ✅实时爬取: {real_src}/{total}")
    print(f"  ⚠️EC专供: {total-real_src}/{total}")
    print(f"  新增映射: {new_mappings}")
    print(f"  Excel: {xlsx.name}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
