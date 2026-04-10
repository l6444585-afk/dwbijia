#!/usr/bin/env python3
"""
补全 spu_shihuo_mapping.json 中缺失的 SPU 映射
通过识货搜索 API 查找商品，提取详情页 URL
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

WORKDIR = Path(__file__).parent
MAPPING_FILE = WORKDIR / "spu_shihuo_mapping.json"
EXCEL_FILE = WORKDIR / "价格表-3.10-13日常大牌日.xlsx"


def load_products() -> list[dict]:
    """从 Excel 读取所有产品"""
    df = pd.read_excel(EXCEL_FILE, header=None)
    products = []
    seen: set[str] = set()
    for idx in range(1, len(df)):
        row = df.iloc[idx]
        spu = str(row.iloc[0]).strip()
        if not spu or spu == "nan" or spu in seen:
            continue
        seen.add(spu)
        products.append({
            "spu": spu,
            "name": str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else "",
        })
    return products


def load_mapping() -> dict:
    if MAPPING_FILE.exists():
        with open(MAPPING_FILE) as f:
            return json.load(f)
    return {}


def save_mapping(mapping: dict):
    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def search_shihuo(session: requests.Session, keyword: str) -> list[dict]:
    """通过识货搜索 API 搜索商品"""
    results = []

    # 方法1: 识货搜索页 HTML
    search_url = f"https://www.shihuo.cn/search/goods?keyword={keyword}"
    try:
        r = session.get(search_url, timeout=15)
        if r.status_code == 200:
            # 从 __NEXT_DATA__ 提取搜索结果
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if m:
                data = json.loads(m.group(1))
                pp = data.get("props", {}).get("pageProps", {})
                goods_list = pp.get("data", {}).get("data", {}).get("list", [])
                if not goods_list:
                    goods_list = pp.get("data", {}).get("list", [])
                for item in goods_list:
                    goods_id = item.get("goods_id") or item.get("goodsId") or item.get("id")
                    style_id = item.get("style_id") or item.get("styleId", "")
                    name = item.get("goods_name") or item.get("goodsName") or item.get("name", "")
                    if goods_id:
                        url = f"https://www.shihuo.cn/page/pcGoodsDetail?goodsId={goods_id}"
                        if style_id:
                            url += f"&styleId={style_id}"
                        results.append({"url": url, "name": name, "goods_id": goods_id})
    except Exception as e:
        print(f"    搜索异常: {e}")

    return results


def match_product(results: list[dict], product_name: str) -> dict | None:
    """从搜索结果中匹配最佳商品（必须是李宁品牌）"""
    if not results:
        return None

    product_name_lower = product_name.lower()

    # 优先精确匹配名称
    for r in results:
        name = r.get("name", "").lower()
        if "李宁" in name and product_name_lower in name:
            return r

    # 其次返回第一个李宁的结果
    for r in results:
        name = r.get("name", "").lower()
        if "李宁" in name:
            return r

    # 最后返回第一个结果
    return results[0] if results else None


def main():
    products = load_products()
    mapping = load_mapping()

    missing = [p for p in products if p["spu"] not in mapping]
    print(f"总产品: {len(products)} | 已有映射: {len(mapping)} | 缺失: {len(missing)}")
    print("=" * 70)

    if not missing:
        print("所有 SPU 已有映射，无需补充。")
        return

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
    })

    found = 0
    not_found = []

    for i, p in enumerate(missing):
        spu = p["spu"]
        name = p["name"]

        # 搜索关键词: "李宁 产品名"
        keyword = f"李宁 {name}"
        print(f"  [{i+1:2d}/{len(missing)}] {spu} {name:15s} 搜索: {keyword}")

        results = search_shihuo(session, keyword)
        time.sleep(0.5)  # 速率限制

        best = match_product(results, name)
        if best:
            mapping[spu] = {
                "url": best["url"],
                "shihuo_name": best.get("name", ""),
            }
            found += 1
            print(f"           ✅ {best.get('name', '')[:40]}")
        else:
            not_found.append(p)
            print(f"           ❌ 未找到")

    save_mapping(mapping)

    print(f"\n{'=' * 70}")
    print(f"  新增映射: {found} | 仍缺失: {len(not_found)}")
    print(f"  映射文件已更新: {MAPPING_FILE.name}")
    if not_found:
        print(f"\n  未找到的产品:")
        for p in not_found:
            print(f"    - {p['spu']} {p['name']}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
