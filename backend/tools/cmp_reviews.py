"""复盘一致性比对:把每份复盘抽成可 diff 的关键结论,横向对齐打印。

**改 agent/prompt.py 或 metrics/candidate_pool.py 后必须用它验一遍**:同一天复跑 ≥2 次,
六个维度应全部 ✅。任一维度 ❌ 说明那部分的「选择权」还在 agent 手里(或格式自由度过大),
要么把选择收进规则层(candidate_pool),要么在 prompt 里把格式/枚举写死。

用法:
    cd backend
    PYTHONPATH=. python3 -m daban_review.cli analyze 20260727 > /tmp/r1.txt 2>&1
    PYTHONPATH=. python3 -m daban_review.cli analyze 20260727 > /tmp/r2.txt 2>&1
    python3 tools/cmp_reviews.py /tmp/r1.txt /tmp/r2.txt

抽取维度:自检行数字 / 情绪周期结论 / 一段方向名 / 二段画像票 / 四段矛盾主角 /
五段候选(code+rank+触发价)。抽取器兼容历史格式(反引号行/表格/加粗),改了输出格式记得同步。
"""

from __future__ import annotations

import json
import re
import sys


def load(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def selfcheck(t: str) -> str:
    m = re.search(r"数据基础:(.+)", t)
    return m.group(1).strip() if m else "(无自检行)"


def section(t: str, head: str, nxt: str) -> str:
    """取某段正文,**不含标题行**(否则 '## 四、情绪周期与明日核心矛盾' 的标题字会被当成结论抽走)。"""
    m = re.search(rf"## {head}(.*?)(?=## {nxt}|\Z)", t, re.S)
    if not m:
        return ""
    body = m.group(1)
    return body.split("\n", 1)[1] if "\n" in body else ""


def directions(t: str) -> list[str]:
    """一段方向名。兼容三种写法:反引号行(现行格式)、markdown 表格行、加粗行。"""
    sec = section(t, "一、", "二、")
    names: list[str] = []
    for line in sec.splitlines():
        line = line.strip().replace("**", "")  # 加粗与否不影响方向名
        if re.match(r"^`?主线\d", line):  # 现行格式:主线1 央企(涨停10家/…)— 属性定性:…
            head = line.strip("`").split("—")[0]
            names.append(re.sub(r"[(（].*", "", re.sub(r"^主线\d+\s*", "", head)).strip())
        elif line.startswith("`") and "—" in line:  # 旧格式:`电网设备/数据中心(…)— 属性…`
            head = line.strip("`").split("—")[0]
            head = re.sub(r"^主线\d+\s*", "", head)
            names.append(re.sub(r"[(（].*", "", head).strip())
        elif line.startswith("|") and not set(line) <= set("|- :"):
            cell = line.strip("|").split("|")[0].strip()
            if cell and "方向" not in cell:
                names.append(re.sub(r"[(（].*", "", cell).strip())
        elif re.match(r"^[-*]?\s*\*\*[^*]+\*\*\s*[—\-(]", line):
            cell = re.sub(r"\*", "", line).strip("-* ")
            names.append(re.sub(r"[(（].*", "", cell).split("—")[0].strip())
    return [n for n in names if n][:6]


def profiled(t: str) -> list[str]:
    """二段画像的票名。兼容 `**名称(N板…**` 与 `**[席位] 名称(N板…**` 两种写法。"""
    sec = section(t, "二、", "三、")
    hits = re.findall(r"\*\*(?:\[[^\]]+\]\s*)?([一-龥A-Za-z0-9]+?)\s*[(（]\d+板", sec)
    return hits


def phase(t: str) -> str:
    sec = section(t, "四、", "五、")
    m = re.search(r"(?:周期定位|情绪周期)[::\s*]*([^\n。,,]+)", sec)
    if m:
        return re.sub(r"\*", "", m.group(1)).strip()
    m = re.search(r"情绪周期([^/\n]+)", selfcheck(t))
    return m.group(1).strip() if m else "?"


def conflict_stars(t: str) -> list[str]:
    """四段里被拿来做 if/则 判断的票(加粗票名 + 6位代码)。"""
    sec = section(t, "四、", "五、")
    return re.findall(r"\*\*([一-龥A-Za-z0-9]+?)[(（](\d{6})[)）]\*\*", sec)


def candidates(t: str) -> list[dict]:
    m = list(re.finditer(r"```json\s*(.*?)```", t, re.S))
    if not m:
        return []
    try:
        return json.loads(m[-1].group(1).strip())
    except Exception:
        return []


def main() -> None:
    paths = sys.argv[1:]
    docs = {p.split("/")[-1].replace(".txt", ""): load(p) for p in paths}

    print("=" * 100)
    for name, t in docs.items():
        print(f"[{name}] 自检:{selfcheck(t)}")
    print("-" * 100)
    for name, t in docs.items():
        print(f"[{name}] 周期结论:{phase(t)}")
    print("-" * 100)
    for name, t in docs.items():
        print(f"[{name}] 方向:{directions(t)}")
    print("-" * 100)
    for name, t in docs.items():
        print(f"[{name}] 画像票:{profiled(t)}")
    print("-" * 100)
    for name, t in docs.items():
        print(f"[{name}] 明日矛盾主角:{[f'{n}({c})' for n, c in conflict_stars(t)]}")
    print("-" * 100)
    styles = ["低位连板接力", "首板打板", "题材情绪龙头", "高位龙头接力"]
    for st in styles:
        row = []
        for name, t in docs.items():
            hit = [c for c in candidates(t) if c.get("style") == st]
            row.append(
                f"{name}={hit[0]['name']}({hit[0]['code']}) r{hit[0].get('pool_rank')} {hit[0].get('price_ref','')}"
                if hit else f"{name}=(无)"
            )
        print(f"  {st}:")
        for r in row:
            print(f"      {r}")

    # 一致性小结
    print("=" * 100)
    def allsame(fn) -> bool:
        vals = [json.dumps(fn(t), ensure_ascii=False, sort_keys=True) for t in docs.values()]
        return len(set(vals)) == 1

    checks = {
        "周期结论": lambda t: re.sub(r"[<>「」\s]", "", phase(t)),  # 忽略括号/空白,只比实质结论
        "候选(style+code)": lambda t: sorted((c.get("style"), c.get("code")) for c in candidates(t)),
        "候选触发价": lambda t: sorted((c.get("style"), c.get("price_ref")) for c in candidates(t)),
        "候选 rank": lambda t: sorted((c.get("style"), c.get("pool_rank")) for c in candidates(t)),
        "画像票集合": lambda t: sorted(set(profiled(t))),
        "方向集合": lambda t: sorted(set(directions(t))),
        "矛盾主角": lambda t: sorted(c for _, c in conflict_stars(t)),
    }
    for label, fn in checks.items():
        print(f"  {'✅一致' if allsame(fn) else '❌不一致'}  {label}")


if __name__ == "__main__":
    main()
