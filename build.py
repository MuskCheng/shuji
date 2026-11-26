"""渲染层：把 bundle.json 注入模板，生成单文件 HTML。

- 字段白名单：只把页面真正需要的字段写进产物，避免 readDetail 等大对象撑爆文件。
- 体积检查：超过上限给出警告。
- Key 不参与渲染，产物里没有任何凭据。
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "data" / "raw" / "bundle.json"
TEMPLATE = ROOT / "templates" / "index.html"
DEFAULT_OUT = ROOT / "dist" / "书迹.html"
MAX_HTML_BYTES = 2 * 1024 * 1024  # 2MB 软上限


def load_config():
    cfg = ROOT / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    example = ROOT / "config.example.json"
    if example.exists():
        return json.loads(example.read_text(encoding="utf-8"))
    return {}


def whitelist(bundle, cfg):
    """只保留页面渲染所需字段，控制体积。"""
    overall = bundle.get("overall", {})
    return {
        "fetchedAt": bundle.get("fetchedAt"),
        "includeSecret": bundle.get("includeSecret", False),
        "user": {
            "name": (bundle.get("user") or {}).get("name", ""),
            "avatar": (bundle.get("user") or {}).get("avatar", ""),
        },
        "overall": {
            "readStat": overall.get("readStat", []),
            "totalReadTime": overall.get("totalReadTime", 0),
            "readRate": overall.get("readRate"),
        },
        "shelfSummary": bundle.get("shelfSummary", {}),
        "profile": bundle.get("profile", {}),
        "secretStats": bundle.get("secretStats", {}),
        "years": {
            y: {"totalReadTime": d.get("totalReadTime", 0)}
            for y, d in (bundle.get("years") or {}).items()
        },
        "yearlyFinished": bundle.get("yearlyFinished", {}),
        "heatmap": bundle.get("heatmap", {}),
        # 书墙：按年截取，避免极端账号把单文件撑到几 MB
        "finishedBooks": {
            y: v[: cfg.get("maxFinishedPerYear", 200)]
            for y, v in sorted((bundle.get("finishedBooks") or {}).items(), reverse=True)
        },
        "bookCloud": (bundle.get("bookCloud") or [])[: cfg.get("maxBookCloud", 100)],
        "categoryCloud": bundle.get("categoryCloud", {}),
    }


def js_string(value):
    s = json.dumps(value, ensure_ascii=False)
    # 防止数据里出现 </script> 提前闭合脚本块
    return s.replace("</", "<\\/")


def main(argv=None):
    ap = argparse.ArgumentParser(description="把 bundle.json 注入模板，生成单文件 HTML")
    ap.add_argument("--bundle", type=Path, default=BUNDLE, help="输入数据（默认 data/raw/bundle.json）")
    ap.add_argument("--output", type=Path, help="输出路径（默认取 config.json 或 dist/书迹.html）")
    args = ap.parse_args(argv)

    bundle_path = args.bundle if args.bundle.is_absolute() else ROOT / args.bundle
    if not bundle_path.exists():
        print("未找到数据缓存，请先运行：python fetch.py", file=sys.stderr)
        return 1
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    cfg = load_config()
    data = whitelist(bundle, cfg)

    html = TEMPLATE.read_text(encoding="utf-8")
    if "/*__DATA__*/" not in html:
        print("模板缺少数据占位符，无法注入", file=sys.stderr)
        return 1
    html = html.replace("/*__DATA__*/", js_string(data))

    out = args.output or Path(cfg.get("output") or DEFAULT_OUT)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    size = out.stat().st_size
    print("已生成：%s（%.1f KB）" % (out, size / 1024))
    if size > MAX_HTML_BYTES:
        print("警告：文件超过 %.1f MB，考虑减少内嵌年份或词云条目" % (MAX_HTML_BYTES / 1048576),
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
