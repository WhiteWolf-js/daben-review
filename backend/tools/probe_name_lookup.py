"""名称→代码反查的联网自检(不进 pytest 套件,避免日常单测依赖网络)。

持仓截图常常只有股票名称没有代码,导入时靠 akshare_client.code_by_name 反查全 A 名称表。
数据源(mootdx 主 / akshare 兜底)哪天变了,跑这个脚本能一眼看出来。

跑法:cd backend && PYTHONPATH=. python3 tools/probe_name_lookup.py
"""

from __future__ import annotations

import logging
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

SAMPLES = ("兴业股份", "吉华集团", "格尔软件", "大湖股份", "皇台酒业", "顺钠股份", "长城军工")


def main() -> None:
    import sys

    from daban_review.data.akshare_client import code_by_name, stock_name_map
    from daban_review.data.store import stock_names_meta

    force = "--force" in sys.argv  # 加 --force 跳过库缓存,联网重拉并落库
    print(f"库中名录:{stock_names_meta()}")
    t = time.time()
    m = stock_name_map(force=force)
    print(f"名称表:{len(m)} 只,耗时 {time.time() - t:.1f}s({'联网重拉' if force else '走缓存/库'})")
    if len(m) < 3000:
        print("⚠️ 全 A 应有数千只,拉少了说明数据源有问题")

    miss = 0
    for nm in SAMPLES:
        code = code_by_name(nm)
        print(f"  {nm} → {code or 'MISS'}")
        miss += 0 if code else 1

    t = time.time()
    stock_name_map()
    print(f"二次调用(按日缓存):{time.time() - t:.4f}s")
    print("结果:" + ("全部命中" if miss == 0 else f"{miss} 只未命中(可能已退市/更名)"))


if __name__ == "__main__":
    main()
