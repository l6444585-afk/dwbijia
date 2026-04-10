#!/usr/bin/env python3
"""
实时抓取 EC 专供款的全渠道价格
搜索得物、京东、拼多多等平台
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

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


def search_dewu(session: requests.Session, keyword: str) -> dict:
    """搜索得物获取价格"""
    result = {"dewu": 0}
    try:
        # 得物 H5 搜索接口
        url = "https://app.dewu.com/api/v1/h5/search/fire/search/list"
        payload = {
            "title": keyword,
            "page": 0,
            "sortType": 0,
            "sortMode": 1,
            "limit": 20,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            "Referer": "https://m.dewu.com/",
        }
        r = session.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            product_list = data.get("data", {}).get("productList", [])
            for item in product_list:
                name = item.get("title", "")
                if "李宁" in name:
                    price = item.get("price", 0)
                    if price and price > 0:
                        # 得物价格单位是分
                        result["dewu"] = price / 100 if price > 1000 else price
                        break
    except Exception:
        pass
    return result


def search_jd(session: requests.Session, keyword: str) -> float:
    """搜索京东获取价格"""
    try:
        url = f"https://search.jd.com/Search?keyword={keyword}&enc=utf-8"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html",
            "Cookie": "",
        }
        r = session.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            # 从搜索结果页提取价格
            prices = re.findall(r'"p":"(\d+\.\d+)"', r.text)
            if prices:
                valid = [float(p) for p in prices if 10 < float(p) < 50000]
                if valid:
                    return min(valid)
    except Exception:
        pass
    return 0


def search_pdd_via_mobile(session: requests.Session, keyword: str) -> float:
    """通过拼多多移动端搜索获取价格"""
    try:
        url = "https://mobile.yangkeduo.com/proxy/api/search"
        params = {
            "q": keyword,
            "page": 1,
            "size": 10,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        }
        r = session.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            for item in items:
                name = item.get("goods_name", "")
                if "李宁" in name:
                    price = item.get("min_group_price", 0)
                    if price and 10 < price / 100 < 50000:
                        return price / 100
    except Exception:
        pass
    return 0


def search_smzdm(session: requests.Session, keyword: str) -> dict:
    """搜索什么值得买获取多平台价格"""
    result = {"jd": 0, "pdd": 0, "tmall": 0}
    try:
        url = f"https://search.smzdm.com/?c=home&s={keyword}&order=score&v=b"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        }
        r = session.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            # 提取价格信息
            blocks = re.findall(
                r'class="feed-block-title"[^>]*>([^<]*李宁[^<]*)</.*?'
                r'class="z-highlight"[^>]*>(\d+\.?\d*)</.*?'
                r'(京东|天猫|拼多多|淘宝)',
                r.text, re.DOTALL
            )
            for _, price_str, platform in blocks:
                price = float(price_str)
                if 10 < price < 50000:
                    if "京东" in platform and result["jd"] == 0:
                        result["jd"] = price
                    elif "天猫" in platform and result["tmall"] == 0:
                        result["tmall"] = price
                    elif "拼多多" in platform and result["pdd"] == 0:
                        result["pdd"] = price
    except Exception:
        pass
    return result


def load_product_names() -> dict[str, str]:
    """从 Excel 读取 SPU -> 产品名映射"""
    df = pd.read_excel(EXCEL_FILE, header=None)
    names = {}
    for idx in range(1, len(df)):
        row = df.iloc[idx]
        spu = str(row.iloc[0]).strip()
        name = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ""
        if spu and spu != "nan" and name:
            names[spu] = name
    return names


def main():
    cache = load_cache()
    product_names = load_product_names()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 找出需要更新的 EC 专供款
    ec_products = {
        spu: data for spu, data in cache.items()
        if "EC专供" in data.get("source", "") or not data.get("shihuo_url")
    }
    print(f"EC 专供款: {len(ec_products)} 个，开始实时抓取...")
    print("=" * 70)

    session = requests.Session()

    updated = 0
    for i, (spu, data) in enumerate(ec_products.items()):
        old_source = data.get("source", "")
        m = re.search(r'淘宝到手¥(\d+)', old_source)
        taobao_price = float(m.group(1)) if m else 0

        product_name = product_names.get(spu, spu)
        keyword = f"李宁 {product_name}"

        print(f"  [{i+1:2d}/{len(ec_products)}] {spu:12s} {product_name:10s}", end="", flush=True)

        prices = {"dewu": 0, "taobao": 0, "tmall": 0, "jd": 0, "pdd": 0, "lowest": 0}

        # 1. 搜索得物
        dewu = search_dewu(session, keyword)
        prices["dewu"] = dewu.get("dewu", 0)
        time.sleep(0.3)

        # 2. 搜索京东
        jd_price = search_jd(session, keyword)
        prices["jd"] = jd_price
        time.sleep(0.3)

        # 3. 搜什么值得买
        smzdm = search_smzdm(session, keyword)
        if smzdm["jd"] > 0 and prices["jd"] == 0:
            prices["jd"] = smzdm["jd"]
        if smzdm["tmall"] > 0:
            prices["tmall"] = smzdm["tmall"]
        if smzdm["pdd"] > 0:
            prices["pdd"] = smzdm["pdd"]
        time.sleep(0.3)

        # 保留淘宝到手价
        if taobao_price > 0:
            prices["taobao"] = taobao_price

        # 计算全网最低
        all_p = [v for v in prices.values() if v > 0]
        prices["lowest"] = min(all_p) if all_p else 0

        # 更新缓存
        has_new = any(prices[k] > 0 for k in ["dewu", "jd", "pdd"])
        cache[spu].update(prices)
        cache[spu]["updated"] = now
        if has_new:
            cache[spu]["source"] = f"✅实时抓取({now})"
            updated += 1
        else:
            cache[spu]["source"] = f"⚠️EC专供(淘宝到手¥{taobao_price:.0f},实时更新{now})"

        # 打印结果
        parts = []
        for k, label in [("dewu", "得物"), ("taobao", "淘宝"), ("tmall", "天猫"), ("jd", "京东"), ("pdd", "拼多多")]:
            if prices[k] > 0:
                parts.append(f"{label}¥{prices[k]:.0f}")
        status = " | ".join(parts) if parts else "无数据"
        tag = "✅" if has_new else "⚠️"
        print(f"  {tag} {status}")

    save_cache(cache)
    session.close()

    print(f"\n{'=' * 70}")
    print(f"  更新完成: {updated}/{len(ec_products)} 个找到新渠道价格")
    print(f"  缓存已更新: {CACHE_FILE.name} (时间戳: {now})")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
