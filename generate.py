"""书迹 · 一键生成入口。

用法：
  1) 设置环境变量 WEREAD_API_KEY
  2) python generate.py

可选参数：
  --include-secret   连私密书一起生成（默认排除）
  --rebuild          忽略缓存，重新抓取所有数据
"""

import shutil
import sys
from pathlib import Path

import fetch
import build

ROOT = Path(__file__).resolve().parent


def main():
    args = set(sys.argv[1:])

    if "--rebuild" in args:
        raw = ROOT / "data" / "raw"
        if raw.exists():
            shutil.rmtree(raw)
            print("已清除本地缓存，开始全新抓取")

    fetch.main()
    print("")
    code = build.main()
    print("")
    print("完成。用浏览器打开生成的 HTML 即可查看你的书迹。")
    return code


if __name__ == "__main__":
    sys.exit(main())
