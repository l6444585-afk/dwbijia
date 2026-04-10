#!/usr/bin/env python3
"""
每日价格对比脚本 (快速版)
直接用缓存的 SPU→识货URL 映射，requests 抓详情页提取全渠道价格
30秒内完成，无需浏览器
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


def load_products() -> list[dict]:
    df = pd.read_excel(WORKDIR / "价格表-3.10-13日常大牌日.xlsx", header=None)
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
            "category": str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else "",
            "front_price": float(row.iloc[5]) if pd.notna(row.iloc[5]) else 0,
            "final_price": float(row.iloc[8]) if pd.notna(row.iloc[8]) else 0,
        })
    return products


def load_mapping() -> dict:
    path = WORKDIR / "spu_shihuo_mapping.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)



def parse_prices(html: str) -> dict:
    result = {"name": "", "lowest": 0.0, "dewu": 0.0,
              "taobao": 0.0, "tmall": 0.0, "jd": 0.0, "pdd": 0.0}

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            pp = data.get("props", {}).get("pageProps", {})
            base = pp.get("data", {}).get("data", {})
            dd = pp.get("detailData", {}).get("data", {})
            result["name"] = base.get("goods_name", "")
            prices = []
            for v in [base.get("goods_price"), dd.get("price")]:
                if v:
                    try:
                        prices.append(float(v))
                    except (ValueError, TypeError):
                        pass
            if prices:
                result["lowest"] = min(prices)
        except json.JSONDecodeError:
            pass

    for key, pats in [
        ("dewu", [r"得物渠道[^，。]*?售价[为]?\s*(\d+\.?\d*)元"]),
        ("taobao", [r"淘宝渠道[^，。]*?售价[为]?\s*(\d+\.?\d*)元",
                     r"在淘宝渠道[^，。]*?售价[为]?\s*(\d+\.?\d*)元"]),
        ("tmall", [r"天猫渠道[^，。]*?售价[为]?\s*(\d+\.?\d*)元"]),
        ("jd", [r"京东渠道[^，。]*?售价[为]?\s*(\d+\.?\d*)元"]),
        ("pdd", [r"拼多多渠道[^，。]*?售价[为]?\s*(\d+\.?\d*)元"]),
    ]:
        for pat in pats:
            match = re.search(pat, html)
            if match:
                try:
                    p = float(match.group(1))
                    if 10 < p < 50000:
                        result[key] = p
                        break
                except (ValueError, TypeError):
                    pass

    return result


def main():
    products = load_products()
    mapping = load_mapping()

    mapped_count = sum(1 for p in products if p["spu"] in mapping)
    ec_count = len(products) - mapped_count
    print(f"产品: {len(products)} | 识货实时: {mapped_count} | EC专供: {ec_count}")
    print("=" * 70)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
    })

    url_cache: dict[str, dict] = {}
    results = []
    start = time.time()

    for i, p in enumerate(products):
        spu = p["spu"]
        info = mapping.get(spu)

        row = {**p, "dewu": 0, "taobao": 0, "tmall": 0, "jd": 0, "pdd": 0,
               "lowest": 0, "shihuo_name": "", "source": ""}

        if info:
            # 有识货映射：实时抓取
            url = info["url"]
            if url not in url_cache:
                try:
                    r = session.get(url, timeout=15)
                    url_cache[url] = parse_prices(r.text) if r.status_code == 200 else {}
                    time.sleep(0.3)
                except Exception:
                    url_cache[url] = {}
            prices = url_cache[url]
            row.update(prices)
            row["source"] = "识货实时"
        else:
            # 非识货产品：优先用缓存中的实时数据，兜底用 Excel 价格
            cache_path = WORKDIR / "merged_price_cache.json"
            if not hasattr(main, '_price_cache'):
                main._price_cache = {}
                if cache_path.exists():
                    with open(cache_path) as f:
                        main._price_cache = json.load(f)
            cached = main._price_cache.get(spu, {})
            has_external = False
            for k in ["dewu", "jd", "pdd"]:
                v = cached.get(k, 0)
                if isinstance(v, (int, float)) and v > 0:
                    row[k] = v
                    has_external = True
            # tmall: 优先用缓存实时数据，否则用 Excel 前台价
            tmall_cached = cached.get("tmall", 0)
            if isinstance(tmall_cached, (int, float)) and tmall_cached > 0:
                row["tmall"] = tmall_cached
            else:
                row["tmall"] = p["front_price"]
            # taobao: 用 Excel 到手价
            row["taobao"] = p["final_price"]
            # lowest: 从所有渠道取最低
            all_p = [v for v in [row["dewu"], row["taobao"], row["tmall"], row["jd"], row["pdd"]] if v > 0]
            row["lowest"] = min(all_p) if all_p else 0
            row["source"] = cached.get("source", "EC专供(仅淘宝)")

        # 打印
        d = row["dewu"]
        parts = []
        if d > 0:
            parts.append(f"得物¥{d:.0f}")
        for k, label in [("taobao", "淘宝"), ("tmall", "天猫"), ("jd", "京东"), ("pdd", "拼多多")]:
            v = row[k]
            if v > 0:
                parts.append(f"{label}¥{v:.0f}")
        if row["lowest"] > 0:
            parts.append(f"低¥{row['lowest']:.0f}")

        status = " | ".join(parts) if parts else "—"
        print(f"  [{i+1:2d}/{len(products)}] {spu} {p['name']:15s} {status}")

        results.append(row)

    elapsed = time.time() - start
    session.close()

    # 导出
    rows = []
    for r in results:
        all_p = [v for v in [r["dewu"], r["taobao"], r["tmall"], r["jd"], r["pdd"], r["lowest"]] if v > 0]
        net_low = min(all_p) if all_p else 0
        final = r["final_price"]

        rows.append({
            "SPU": r["spu"],
            "分类": r["category"],
            "产品名称": r["name"],
            "淘宝前台价": r["front_price"],
            "淘宝到手价": final,
            "得物价格": r["dewu"] or "",
            "价差(到手-得物)": f"{final - r['dewu']:+.0f}" if r["dewu"] > 0 and final > 0 else "",
            "淘宝(识货)": r["taobao"] or "",
            "天猫价": r["tmall"] or "",
            "京东价": r["jd"] or "",
            "拼多多价": r["pdd"] or "",
            "全网最低": net_low or "",
            "价差(到手-最低)": f"{final - net_low:+.0f}" if net_low > 0 and final > 0 else "",
            "数据来源": r.get("source", ""),
            "识货商品名": r["shihuo_name"],
        })

    xlsx = WORKDIR / "每日价格对比.xlsx"
    pd.DataFrame(rows).to_excel(xlsx, index=False, engine="openpyxl")

    has_dewu = sum(1 for r in results if r["dewu"] > 0)
    has_any = sum(1 for r in results if any(r[k] > 0 for k in ["dewu", "taobao", "tmall", "jd", "pdd", "lowest"]))

    print(f"\n{'=' * 70}")
    print(f"  耗时: {elapsed:.1f}秒")
    print(f"  有得物: {has_dewu}/{len(results)} | 有价格: {has_any}/{len(results)}")
    print(f"  Excel: {xlsx.name}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
