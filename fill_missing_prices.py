#!/usr/bin/env python3
"""
补全缺失价格脚本 v3
策略: 识货搜索 → 找到李宁商品 → 访问详情页 → 提取全渠道价格
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

WORKDIR = Path(__file__).parent
CACHE_FILE = WORKDIR / "merged_price_cache.json"
WS_FILE = WORKDIR / "websearch_results.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def load_data() -> tuple[dict, list]:
    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    products = []
    if WS_FILE.exists():
        with open(WS_FILE) as f:
            products = json.load(f)
    return cache, products


def save_cache(cache: dict) -> None:
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.replace(CACHE_FILE)


def shihuo_search(keyword: str, session: requests.Session) -> list[dict]:
    """识货搜索 - 返回匹配的李宁商品列表"""
    try:
        r = session.get(
            "https://www.shihuo.cn/search",
            params={"k": f"李宁 {keyword}"},
            timeout=15,
        )
        if r.status_code != 200:
            return []

        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r.text, re.DOTALL,
        )
        if not m:
            return []

        data = json.loads(m.group(1))
        items = (
            data.get("props", {}).get("pageProps", {})
            .get("data", {}).get("data", {}).get("list", [])
        )

        # 过滤: 只要李宁品牌的
        results = []
        for item in items:
            title = item.get("title", "")
            brand = item.get("brand_name", "").lower()
            if "李宁" in title or "li-ning" in brand or "lining" in brand or "li ning" in brand:
                results.append({
                    "goods_id": item.get("goods_id", ""),
                    "style_id": item.get("style_id", ""),
                    "title": title,
                    "price": item.get("price", 0),
                })
        return results
    except Exception as e:
        print(f"    [识货搜索] 失败: {e}")
        return []


def shihuo_detail_prices(goods_id: str, style_id: str, session: requests.Session) -> dict:
    """识货详情页 - 提取全渠道价格"""
    result = {"dewu": 0, "taobao": 0, "tmall": 0, "jd": 0, "pdd": 0, "lowest": 0}
    try:
        url = f"https://www.shihuo.cn/page/pcGoodsDetail?goodsId={goods_id}&styleId={style_id}"
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return result

        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r.text, re.DOTALL,
        )
        if not m:
            return result

        data = json.loads(m.group(1))
        pp = data.get("props", {}).get("pageProps", {})
        text = json.dumps(pp, ensure_ascii=False)

        # 从详情数据提取基础价格
        base = pp.get("data", {}).get("data", {})
        detail = pp.get("detailData", {}).get("data", {})

        base_price = 0
        for val in [base.get("goods_price"), detail.get("price")]:
            if val:
                try:
                    p = float(val)
                    if 10 < p < 50000:
                        base_price = p
                        break
                except (ValueError, TypeError):
                    pass

        # 从渠道文本提取各平台价格
        channel_patterns = [
            ("dewu", [
                r"得物[^，。\n]{0,20}?[¥￥]?\s*(\d{2,5}(?:\.\d{1,2})?)",
                r"得物渠道[^，。]*?售价[为]?\s*(\d{2,5}(?:\.\d{1,2})?)",
                r"得物[价格]*\s*[:：]?\s*[¥￥]?\s*(\d{2,5})",
            ]),
            ("taobao", [
                r"淘宝[^，。\n]{0,20}?[¥￥]?\s*(\d{2,5}(?:\.\d{1,2})?)",
                r"淘宝渠道[^，。]*?售价[为]?\s*(\d{2,5}(?:\.\d{1,2})?)",
            ]),
            ("tmall", [
                r"天猫[^，。\n]{0,20}?[¥￥]?\s*(\d{2,5}(?:\.\d{1,2})?)",
                r"天猫渠道[^，。]*?售价[为]?\s*(\d{2,5}(?:\.\d{1,2})?)",
            ]),
            ("jd", [
                r"京东[^，。\n]{0,20}?[¥￥]?\s*(\d{2,5}(?:\.\d{1,2})?)",
                r"京东渠道[^，。]*?售价[为]?\s*(\d{2,5}(?:\.\d{1,2})?)",
            ]),
            ("pdd", [
                r"拼多多[^，。\n]{0,20}?[¥￥]?\s*(\d{2,5}(?:\.\d{1,2})?)",
                r"拼多多渠道[^，。]*?售价[为]?\s*(\d{2,5}(?:\.\d{1,2})?)",
            ]),
        ]

        for platform, patterns in channel_patterns:
            for pat in patterns:
                match = re.search(pat, text)
                if match:
                    try:
                        p = float(match.group(1))
                        if 10 < p < 50000:
                            result[platform] = p
                            break
                    except (ValueError, TypeError):
                        pass

        # SKU列表中提取渠道价格
        sku_data = pp.get("skuListData", {}).get("data", {}).get("list", [])
        for sku in sku_data:
            channels = sku.get("channel_list", sku.get("channels", []))
            if isinstance(channels, list):
                for ch in channels:
                    ch_name = str(ch.get("channel_name", ch.get("name", ""))).lower()
                    ch_price = 0
                    for pk in ["price", "min_price", "channel_price"]:
                        try:
                            ch_price = float(ch.get(pk, 0))
                            if ch_price > 0:
                                break
                        except (ValueError, TypeError):
                            pass
                    if ch_price <= 0 or ch_price > 50000:
                        continue

                    if "得物" in ch_name or "dewu" in ch_name:
                        if result["dewu"] == 0 or ch_price < result["dewu"]:
                            result["dewu"] = ch_price
                    elif "天猫" in ch_name:
                        if result["tmall"] == 0 or ch_price < result["tmall"]:
                            result["tmall"] = ch_price
                    elif "淘宝" in ch_name:
                        if result["taobao"] == 0 or ch_price < result["taobao"]:
                            result["taobao"] = ch_price
                    elif "京东" in ch_name or "jd" in ch_name:
                        if result["jd"] == 0 or ch_price < result["jd"]:
                            result["jd"] = ch_price
                    elif "拼多多" in ch_name or "pdd" in ch_name:
                        if result["pdd"] == 0 or ch_price < result["pdd"]:
                            result["pdd"] = ch_price

        # 如果只有基础价格但没提取到渠道价格, 用基础价格做 lowest
        all_prices = [result[k] for k in ["dewu", "taobao", "tmall", "jd", "pdd"] if result[k] > 0]
        if all_prices:
            result["lowest"] = min(all_prices)
        elif base_price > 0:
            result["lowest"] = base_price

        result["shihuo_url"] = url
        return result

    except Exception as e:
        print(f"    [识货详情] 失败: {e}")
        return result


def keyword_match_score(product_name: str, search_title: str) -> float:
    """计算关键词匹配度"""
    name_chars = set(product_name.replace(" ", ""))
    title_chars = set(search_title.replace(" ", ""))
    if not name_chars:
        return 0
    overlap = name_chars & title_chars
    return len(overlap) / len(name_chars)


def fill_product(spu: str, name: str, existing: dict, session: requests.Session) -> dict:
    """用识货搜索补全单个产品"""
    updated = {**existing}

    # 搜索识货
    search_terms = [name]
    # 如果名字太短或太通用，加 SPU
    if len(name) <= 2:
        search_terms.append(spu)

    best_match = None
    best_score = 0

    for term in search_terms:
        items = shihuo_search(term, session)
        time.sleep(0.5)

        for item in items:
            score = keyword_match_score(name, item["title"])
            if score > best_score:
                best_score = score
                best_match = item

    if not best_match or best_score < 0.3:
        # 尝试用 SPU 编号搜索
        items = shihuo_search(spu, session)
        time.sleep(0.5)
        for item in items:
            score = keyword_match_score(name, item["title"])
            if score > best_score:
                best_score = score
                best_match = item

    if not best_match:
        print(f"    未找到匹配商品")
        return updated

    print(f"    匹配: {best_match['title'][:35]} (score={best_score:.2f})")

    # 获取详情页价格
    prices = shihuo_detail_prices(
        str(best_match["goods_id"]),
        str(best_match["style_id"]),
        session,
    )
    time.sleep(0.5)

    # 合并: 只更新之前缺失的价格
    for platform in ["dewu", "taobao", "tmall", "jd", "pdd"]:
        if prices.get(platform, 0) > 0 and not updated.get(platform, 0):
            updated[platform] = prices[platform]
            print(f"    [{platform}] ¥{prices[platform]:.0f} NEW")

    if prices.get("shihuo_url"):
        updated["shihuo_url"] = prices["shihuo_url"]

    # 更新 lowest
    all_p = [updated.get(k, 0) for k in ["dewu", "taobao", "tmall", "jd", "pdd"]
             if updated.get(k, 0) > 0]
    if all_p:
        updated["lowest"] = min(all_p)

    return updated


def export_excel(products: list, cache: dict) -> str:
    import pandas as pd

    rows = []
    for item in products:
        spu = item["spu"]
        c = cache.get(spu, {})
        all_p = [c.get(k, 0) for k in ["dewu", "taobao", "tmall", "jd", "pdd"]
                 if c.get(k, 0) > 0]
        net_low = min(all_p) if all_p else 0
        final = item.get("final_price", 0)

        rows.append({
            "SPU": spu,
            "分类": item.get("category", ""),
            "产品名称": item["name"],
            "淘宝前台价": item.get("front_price", 0),
            "淘宝到手价": final,
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
    xlsx_path = WORKDIR / f"李宁全渠道价格对比_完整版_{ts}.xlsx"
    pd.DataFrame(rows).to_excel(xlsx_path, index=False, engine="openpyxl")
    return xlsx_path.name


def main():
    cache, products = load_data()
    print(f"加载: {len(products)} 产品, {len(cache)} 条缓存")

    # Before 统计
    total = len(products)
    before_dewu = sum(1 for item in products if cache.get(item["spu"], {}).get("dewu", 0) > 0)
    before_any = sum(1 for item in products
                     if any(cache.get(item["spu"], {}).get(k, 0) > 0
                            for k in ["dewu", "taobao", "tmall", "jd", "pdd"]))
    print(f"当前: 得物 {before_dewu}/{total} | 有价格 {before_any}/{total}")
    print("=" * 70)

    # 找需要补全的
    to_fill = []
    for item in products:
        spu = item["spu"]
        cached = cache.get(spu, {})
        has_dewu = cached.get("dewu", 0) > 0
        has_any = any(cached.get(k, 0) > 0 for k in ["dewu", "taobao", "tmall", "jd", "pdd"])
        if not has_dewu or not has_any:
            to_fill.append(item)

    print(f"需要补全: {len(to_fill)} 个")
    print("=" * 70)

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html"})

    start = time.time()
    updated_count = 0
    new_prices = 0

    for i, item in enumerate(to_fill):
        spu = item["spu"]
        name = item["name"]
        existing = cache.get(spu, {
            "dewu": 0, "taobao": 0, "tmall": 0,
            "jd": 0, "pdd": 0, "lowest": 0,
            "shihuo_url": "", "source": "",
        })

        old_count = sum(1 for k in ["dewu", "taobao", "tmall", "jd", "pdd"]
                        if existing.get(k, 0) > 0)

        print(f"\n[{i+1}/{len(to_fill)}] {spu} {name}")

        updated = fill_product(spu, name, existing, session)

        new_count = sum(1 for k in ["dewu", "taobao", "tmall", "jd", "pdd"]
                        if updated.get(k, 0) > 0)
        gained = new_count - old_count
        if gained > 0:
            new_prices += gained
            updated_count += 1
            src = existing.get("source", "")
            updated["source"] = f"{src}+shihuo_fill" if src else "shihuo_fill"

        # 汇总
        parts = []
        for k, label in [("dewu", "得物"), ("taobao", "淘宝"), ("tmall", "天猫"),
                          ("jd", "京东"), ("pdd", "拼多多")]:
            v = updated.get(k, 0)
            if v > 0:
                parts.append(f"{label}¥{v:.0f}")
        print(f"  结果: {' | '.join(parts) if parts else '仍无数据'}")

        cache[spu] = updated

    elapsed = time.time() - start
    session.close()
    save_cache(cache)

    # After 统计
    after_dewu = sum(1 for item in products if cache.get(item["spu"], {}).get("dewu", 0) > 0)
    after_any = sum(1 for item in products
                    if any(cache.get(item["spu"], {}).get(k, 0) > 0
                           for k in ["dewu", "taobao", "tmall", "jd", "pdd"]))

    print(f"\n{'=' * 70}")
    print(f"  耗时: {elapsed:.1f}秒")
    print(f"  更新产品: {updated_count}/{len(to_fill)}")
    print(f"  新增价格: {new_prices} 条")
    print(f"  得物: {before_dewu} → {after_dewu}/{total}")
    print(f"  有价格: {before_any} → {after_any}/{total}")
    print(f"  完全无价: {total - after_any}/{total}")

    try:
        xlsx = export_excel(products, cache)
        print(f"  Excel: {xlsx}")
    except Exception as e:
        print(f"  Excel 失败: {e}")

    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
