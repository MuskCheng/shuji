"""用虚构数据生成 docs/demo.html —— 不含任何真实阅读记录。

虚构书名、作者与统计数字，仅用于展示页面效果。每次运行结果固定。
"""

import base64
import calendar
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "demo.html"

BOOKS = [
    ("三体", "刘慈欣", "科幻-中国科幻"),
    ("百年孤独", "加西亚·马尔克斯", "文学-外国文学"),
    ("人类简史", "尤瓦尔·赫拉利", "历史-世界史"),
    ("置身事内", "兰小欢", "经济-中国经济"),
    ("乡土中国", "费孝通", "社会-社会学"),
    ("万历十五年", "黄仁宇", "历史-中国史"),
    ("沉思录", "马可·奥勒留", "哲学-西方哲学"),
    ("原则", "瑞·达利欧", "商业-管理"),
    ("自私的基因", "理查德·道金斯", "科普-生物"),
    ("人间失格", "太宰治", "文学-外国文学"),
    ("全球通史", "斯塔夫里阿诺斯", "历史-世界史"),
    ("小狗钱钱", "博多·舍费尔", "商业-个人理财"),
    ("也许你该找个人聊聊", "洛莉·戈特利布", "心理-心理学应用"),
    ("枪炮、病菌与钢铁", "贾雷德·戴蒙德", "历史-世界史"),
    ("小王子", "圣埃克苏佩里", "文学-外国文学"),
    ("认知偏差", "行为科学编辑部", "心理-认知科学"),
    ("气候经济与人类未来", "比尔·盖茨", "科普-环境"),
    ("一课经济学", "亨利·黑兹利特", "经济-经济学"),
    ("为什么我们总是在防御", "约瑟夫·布尔戈", "心理-心理学应用"),
    ("低利率时代", "经济观察组", "经济-宏观"),
    ("短暂的人生", "山田咏美", "文学-外国文学"),
    ("如何阅读一本书", "莫提默·艾德勒", "教育-学习方法"),
    ("看见", "柴静", "社会-纪实"),
    ("激荡三十年", "吴晓波", "经济-中国经济"),
    ("禅与摩托车维修艺术", "罗伯特·波西格", "哲学-西方哲学"),
    ("规模", "杰弗里·韦斯特", "科普-复杂系统"),
    ("事实", "汉斯·罗斯林", "科普-统计"),
    ("娱乐至死", "尼尔·波兹曼", "社会-传播学"),
    ("九章算术", "佚名", "数学-古典数学"),
    ("敦煌本纪", "叶舟", "文学-中国文学"),
]


def demo_avatar():
    """示例头像：内联 SVG（渐变圆 + 单字），不引用任何外部图片。"""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="132" height="132" viewBox="0 0 132 132">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#7fd3c3"/><stop offset="1" stop-color="#28685e"/></linearGradient></defs>'
        '<rect width="132" height="132" fill="url(#g)"/>'
        '<text x="66" y="88" font-size="58" font-family="KaiTi,serif" fill="#f2fffb" text-anchor="middle">读</text>'
        '</svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def demo_cover(title, author, index):
    """虚构封面：渐变底 + 书名 + 作者，内联 SVG，不含任何真实封面图。

    之前示例封面是一块纯色渐变，容易被误认为「抓取失败」。现在每本书都有
    可读的书名/作者，看起来像一本书，但一眼仍是示意图，且完全离线可复现。
    """
    hue = (index * 47) % 360
    hue2 = (hue + 38) % 360
    # 中文按字断行；英文/数字连续串尽量不拆，示例数据以中文为主
    lines, cur = [], ""
    for ch in title:
        cur += ch
        if len(cur) >= 7:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    lines = lines[:3]
    if len(lines) == 3 and len(lines[2]) > 7:
        lines[2] = lines[2][:6] + "…"
    title_lines = "".join(
        "<text x='120' y='%d' text-anchor='middle' font-size='30' "
        "font-family='Noto Sans CJK SC,Microsoft YaHei,sans-serif' "
        "font-weight='700' fill='#fff8ea' letter-spacing='1'>%s</text>"
        % (126 + i * 41, escape(line))
        for i, line in enumerate(lines)
    )
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='240' height='320' viewBox='0 0 240 320'>"
        "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        "<stop stop-color='hsl(%d,46%%,42%%)'/>"
        "<stop offset='1' stop-color='hsl(%d,48%%,17%%)'/>"
        "</linearGradient></defs>"
        "<rect width='240' height='320' fill='url(#g)'/>"
        "<rect x='10' y='10' width='220' height='300' fill='none' stroke='rgba(255,255,255,.22)' stroke-width='1'/>"
        "<rect x='23' y='23' width='3' height='66' fill='#f1d18a' opacity='.9'/>"
        "<circle cx='196' cy='58' r='26' fill='none' stroke='rgba(255,255,255,.18)' stroke-width='1'/>"
        "<circle cx='196' cy='58' r='17' fill='none' stroke='rgba(255,255,255,.12)' stroke-width='1'/>"
        "%s"
        "<text x='120' y='272' text-anchor='middle' font-size='14' "
        "font-family='Noto Sans CJK SC,Microsoft YaHei,sans-serif' fill='rgba(255,248,234,.78)'>%s</text>"
        "<text x='120' y='298' text-anchor='middle' font-size='10' letter-spacing='2' "
        "font-family='sans-serif' fill='rgba(255,248,234,.45)'>DEMO COVER</text>"
        "</svg>"
    ) % (hue, hue2, title_lines, escape(author))
    return "data:image/svg+xml;charset=utf-8," + quote(svg, safe="")


def build_bundle():
    rnd = random.Random(20260315)
    years = ["2022", "2023", "2024"]
    heatmap = {}
    year_time = {}
    finished = {}
    # 每年一个强度系数，让逐年对比有起伏，不至于三根一样长
    year_scale = {"2022": 0.52, "2023": 1.18, "2024": 0.86}
    for y in years:
        pts = []
        scale = year_scale.get(y, 1.0)
        dim = calendar.monthrange(int(y), 2)[1] + 337
        d0 = date(int(y), 1, 1)
        total = 0
        # 用几个平滑的“阅读季”制造可辨认的起伏
        peaks = {3: 0.5, 7: 1.0, 8: 0.9, 11: 0.6}
        for i in range(dim):
            d = d0 + timedelta(days=i)
            month = d.month
            base = peaks.get(month, 0.22) * 7200
            wave = math.sin(i / 19) * 1800
            noise = rnd.uniform(-900, 900)
            sec = max(0, int((base + wave + noise) * scale))
            total += sec
            pts.append({"date": d.isoformat(), "seconds": sec})
        heatmap[y] = pts
        year_time[y] = total
        finished[y] = f"{rnd.randint(18, 70)}本"

    cloud = []
    finished_books = {}
    for y in years:
        finished_books[y] = []
    for i, (title, author, cat) in enumerate(BOOKS):
        seconds = int(320000 * math.exp(-i / 8) + rnd.randint(2000, 20000))
        cloud.append({
            "title": title,
            "author": author,
            "category": cat,
            "seconds": seconds,
            "bookIds": [f"demo-{i:04d}"],
        })
        # 虚构的「读完」记录：带书名的示意封面，内联 SVG，不引用外部图片
        year = years[i % len(years)]
        month = rnd.randint(1, 12)
        day = rnd.randint(1, 28)
        cover = demo_cover(title, author, i)
        # 虚构的逐日阅读轨迹：围绕读完日往前推 6~24 天，穿插未阅读的空档
        end = date(int(year), month, day)
        span = rnd.randint(6, 24)
        daily = []
        for k in range(span):
            d = end - timedelta(days=span - 1 - k)
            if rnd.random() < 0.28:
                continue  # 那天没读
            base = seconds / max(1, int(span * 0.7))
            daily.append({
                "d": d.isoformat(),
                "s": max(60, int(base * rnd.uniform(0.35, 1.9))),
            })
        reading = None
        if daily:
            peak = max(daily, key=lambda x: x["s"])
            reading = {
                "begin": daily[0]["d"],
                "last": daily[-1]["d"],
                "days": len(daily),
                "longest": peak["d"],
                "longestSec": peak["s"],
                "daily": daily,
            }
            # 让「投入时长」与折线图自洽，避免演示页出现自相矛盾的数字
            seconds = sum(x["s"] for x in daily)
            cloud[-1]["seconds"] = seconds
        finished_books[year].append({
            "bookId": f"demo-{i:04d}",
            "title": title,
            "author": author,
            "cover": cover,
            "intro": "这是一段用于演示的虚构简介，展示书籍详情弹层的排版效果。",
            "publisher": "示例出版社",
            "rating": 800 + (i * 13) % 180,
            "myRating": (i % 5) + 1,
            "finished": f"{year}-{month:02d}-{day:02d}",
            "seconds": seconds,
            "reading": reading,
            "highlights": [{"text": "这是一句虚构的划线示例文字，用来展示引用样式。", "chapter": "示例章节"}] if i % 2 == 0 else [],
            "thoughts": [{"content": "这是一条虚构的个人想法，用来展示书评样式。", "abstract": "", "chapter": "", "star": (i % 5) + 1}] if i % 3 == 0 else [],
        })
    for y in finished_books:
        finished_books[y].sort(key=lambda x: x["finished"])

    overall = sum(year_time.values())
    # 虚构的时段分布：早上与深夜两个峰，形状固定可复现
    hours = [int(3600 * (0.5 + 2.6 * math.exp(-((h - 21.5) ** 2) / 6) + 1.5 * math.exp(-((h - 8) ** 2) / 8)))
             for h in range(24)]
    return {
        "fetchedAt": "2026-01-01T08:00:00+08:00",
        "includeSecret": False,
        "user": {"name": "示例用户", "avatar": demo_avatar()},
        "overall": {
            "readStat": [
                {"stat": "读过", "counts": "198本", "scheme": ""},
                {"stat": "读完", "counts": "128本", "scheme": ""},
                {"stat": "阅读", "counts": "742天", "scheme": ""},
                {"stat": "笔记", "counts": "536条", "scheme": ""},
            ],
            "totalReadTime": overall,
            "readRate": 63,
        },
        "profile": {
            "hours": hours,
            "peakHour": hours.index(max(hours)),
            "timeWord": "偏好夜间阅读",
            "authors": [
                {"name": "刘慈欣", "count": 5, "readTime": "42小时10分钟"},
                {"name": "费孝通", "count": 4, "readTime": "31小时5分钟"},
                {"name": "黄仁宇", "count": 3, "readTime": "26小时48分钟"},
                {"name": "兰小欢", "count": 3, "readTime": "22小时30分钟"},
                {"name": "圣埃克苏佩里", "count": 2, "readTime": "9小时12分钟"},
            ],
            "medals": [
                {"name": "21天阅读挑战", "date": "2024-12-01", "text": "示例勋章"},
                {"name": "连续阅读", "date": "2024-10-01", "text": "示例勋章"},
                {"name": "阅读时长", "date": "2024-07-01", "text": "示例勋章"},
            ],
            "medalCount": 9,
            "longest": {"title": "三体", "author": "刘慈欣",
                        "cover": finished_books[years[0]][0]["cover"], "seconds": 1316900},
            "yearly": [{"year": y, "seconds": t} for y, t in sorted(year_time.items())],
            "words": {"finished": 9600000, "total": 12400000},
            "listen": {"read": 1800000, "listen": 260000},
            "overview": [
                {"title": "读过神作", "value": "9本", "desc": "神作收藏家"},
                {"title": "发布推荐", "value": "3条", "desc": "夸夸达人"},
            ],
        },
        "secretStats": {"books": 6, "finished": 2, "finishedByYear": {"2024": 2}},
        "shelfSummary": {"books": 198, "albums": 0, "hasMp": False, "finishedMarked": 128},
        "years": {y: {"totalReadTime": t} for y, t in year_time.items()},
        "yearlyFinished": finished,
        "heatmap": heatmap,
        "finishedBooks": finished_books,
        "bookCloud": cloud,
        "categoryCloud": {
            "duration": [
                {"name": "精品小说", "value": 640000, "kind": "seconds"},
                {"name": "心理", "value": 390000, "kind": "seconds"},
                {"name": "历史", "value": 280000, "kind": "seconds"},
                {"name": "经济理财", "value": 210000, "kind": "seconds"},
                {"name": "社会文化", "value": 150000, "kind": "seconds"},
                {"name": "文学", "value": 96000, "kind": "seconds"},
                {"name": "科普", "value": 54000, "kind": "seconds"},
            ],
            "count": [{"name": "精品小说", "value": 22, "kind": "count"}],
        },
    }


def main():
    import build
    OUT.parent.mkdir(parents=True, exist_ok=True)
    bundle = build_bundle()
    tmp = ROOT / "data" / "demo_bundle.json"
    tmp.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    code = build.main(["--bundle", str(tmp), "--output", str(OUT)])
    tmp.unlink(missing_ok=True)
    if code == 0:
        print("已生成脱敏示例页：", OUT, "（%.1f KB）" % (OUT.stat().st_size / 1024))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
