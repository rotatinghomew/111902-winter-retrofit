"""生成验收会报告：python3 -m analysis [--query-date YYYY-MM-DD] [--data PATH] [--out DIR]"""

import argparse
import json
from pathlib import Path

from .core import run
from .report import build_json, build_markdown


def main():
    ap = argparse.ArgumentParser(prog="analysis", description="节能验收证据分析与报告")
    ap.add_argument("--data", default="data/supplies.json", help="来源资料路径")
    ap.add_argument("--query-date", default="2026-11-19", help="查询日（口径截止）")
    ap.add_argument("--out", default="out", help="报告输出目录")
    args = ap.parse_args()

    res = run(args.data, args.query_date)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = build_markdown(res)
    js = build_json(res)
    md_path = out_dir / f"report_{args.query_date}.md"
    js_path = out_dir / f"report_{args.query_date}.json"
    md_path.write_text(md, encoding="utf-8")
    js_path.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {md_path} 与 {js_path}")


if __name__ == "__main__":
    main()
