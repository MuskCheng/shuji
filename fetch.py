"""抓取层：把微信读书账号数据整理成一份本地 bundle.json。

设计要点：
- 只拉「有数据」的年份：先逐年探测 totalReadTime，为 0 的年份直接丢弃。
- 逐书时长走本地缓存，二次运行只增量拉新书。
- 隐私过滤（secret）与去重在抓取层完成，渲染层拿到的就是干净数据。
- 所有原始响应落 data/raw/，该目录已在 .gitignore 中。
"""

import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

import weread

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
BUNDLE = RAW / "bundle.json"

SHANGHAI = dt.timezone(dt.timedelta(hours=8))
MIN_BOOK_SECONDS = 5 * 60          # 词云词条最低时长：5 分钟
PLACEHOLDER_CATEGORY_TYPE = 32745  # preferCategory 里的默认占位分类
API_GAP = 0.12                     # 逐书补抓的请求间隔（秒），避免打爆网关
MAX_NOTES_PER_BOOK = 6             # 每本书最多带几条划线/想法，控制页面体积
MAX_READ_DAYS = 400                # 每本书逐日明细上限，防止极端账号撑大产物


def ts(year, month, day):
    return int(dt.datetime(year, month, day, tzinfo=dt.timezone.utc).timestamp())


def day_iso(stamp):
    """把接口里的日期时间戳按北京时间转成 YYYY-MM-DD；异常值返回 None。"""
    try:
        return dt.datetime.fromtimestamp(int(stamp), SHANGHAI).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def year_range(regist_time):
    """从注册年份到今年，只列候选年；是否保留由 totalReadTime 决定。"""
    if regist_time:
        start = dt.datetime.fromtimestamp(regist_time, SHANGHAI).year
    else:
        start = 2020
    end = dt.datetime.now(SHANGHAI).year
    return list(range(max(start, 2020), end + 1))


def normalize_title(title):
    """全角/半角标点归一化，用于同名合并（如『参与感:』与『参与感：』）。"""
    s = unicodedata.normalize("NFKC", title or "")
    s = re.sub(r"\s+", "", s)
    return s.lower()


def discover_years(candidates):
    """逐年探测，返回 {year: annual_data}，只保留 totalReadTime>0 的年份。

    当前年份不读缓存：它是唯一还会变的年份，缓存住会让热力图和年度统计
    停在第一次运行的那天。
    """
    years = {}
    cache = RAW / "years"
    this_year = dt.datetime.now(SHANGHAI).year
    for y in candidates:
        cached = None if y == this_year else read_json(cache / ("%d.json" % y))
        data = cached or weread.call(
            "/readdata/detail", mode="annually", baseTime=ts(y, 6, 1)
        )
        if not cached:
            write_json(cache / ("%d.json" % y), data)
        total = data.get("totalReadTime") or 0
        if total > 0:
            years[str(y)] = data
            print("  [year] %d 有数据：%d 秒" % (y, total))
        else:
            print("  [year] %d 无数据，跳过" % y)
    return years


def readinfo_of(bid, force=False):
    """取单本书的 /book/readinfo，带本地缓存与重试。

    首次抓取可能被限流或中途打断，因此这里失败不写缓存，
    下次运行会自动重试；返回 None 表示这次仍拿不到。
    force=True 时忽略缓存（最近在读的书时长每天都在变）。
    """
    path = RAW / "books" / ("%s.json" % bid)
    if not force:
        cached = read_json(path)
        if cached is not None:
            return cached
    for attempt in range(2):
        try:
            time.sleep(API_GAP)
            data = weread.call("/book/readinfo", bookId=bid)
        except weread.WereadError as exc:
            if attempt == 1:
                print("  [readinfo] %s 放弃：%s" % (bid, str(exc)[:70]), file=sys.stderr)
                return None
            time.sleep(1.2)
            continue
        write_json(path, data)
        return data
    return None


def fetch_books(shelf, include_secret):
    """遍历书架取逐书累计时长，返回合并后的书名词云条目。

    三层去重：bookId 去重 → 时长阈值 → 标题归一化后同名取 MAX。
    """
    books = shelf.get("books") or []
    cache_dir = RAW / "books"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 第一层：按 bookId 去重
    unique = {}
    for b in books:
        bid = b.get("bookId")
        if bid and bid not in unique:
            unique[bid] = b

    merged = {}
    skipped_secret = 0
    total_books = len(unique)
    # 最近 3 天动过的书强制刷新，否则「在读」的累计时长会停在缓存那天
    now_ts = time.time()
    recent = {
        bid for bid, b in unique.items()
        if (b.get("readUpdateTime") or 0) and now_ts - b["readUpdateTime"] < 3 * 86400
    }
    for idx, (bid, b) in enumerate(unique.items(), 1):
        if b.get("secret") == 1 and not include_secret:
            skipped_secret += 1
            continue

        info = readinfo_of(bid, force=(bid in recent))
        if not info:
            print("  [book] 跳过 %s（接口报错）" % b.get("title"), file=sys.stderr)
            continue

        # isSecret 以逐书接口为准（书架字段可能缺失）
        if info.get("isSecret") == 1 and not include_secret:
            skipped_secret += 1
            continue

        seconds = info.get("readingTime") or 0
        # 第二层：时长阈值
        if seconds < MIN_BOOK_SECONDS:
            continue

        title = b.get("title") or ""
        key = normalize_title(title)
        record = {
            "title": title,
            "author": b.get("author") or "",
            "category": b.get("category") or "",
            "seconds": seconds,
            "bookIds": [bid],
        }
        # 第三层：同名取 MAX，不取 SUM
        if key in merged and merged[key]["seconds"] >= seconds:
            merged[key]["bookIds"].append(bid)
        elif key in merged:
            record["bookIds"] = merged[key]["bookIds"] + [bid]
            merged[key] = record
        else:
            merged[key] = record

        if idx % 50 == 0 or idx == total_books:
            print("  [book] %d/%d 已处理" % (idx, total_books))

    print("  [book] 私密跳过 %d 本，有效词条 %d 条" % (skipped_secret, len(merged)))
    return sorted(merged.values(), key=lambda x: x["seconds"], reverse=True)


def build_category_cloud(overall, shelf, include_secret):
    """返回两种口径的分类词云数据。"""
    duration = []
    for c in overall.get("preferCategory") or []:
        if c.get("categoryType") == PLACEHOLDER_CATEGORY_TYPE:
            continue
        sec = c.get("readingTime") or 0
        if sec <= 0:
            continue
        duration.append(
            {"name": c.get("categoryTitle") or "", "value": sec, "kind": "seconds"}
        )

    counts = {}
    for b in shelf.get("books") or []:
        if b.get("secret") == 1 and not include_secret:
            continue
        cat = (b.get("category") or "").strip()
        if not cat:
            continue  # 165 本空分类：剔除出排名，不静默丢弃成「未分类」巨词
        counts[cat] = counts.get(cat, 0) + 1
    by_count = [
        {"name": k, "value": v, "kind": "count"}
        for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    ]
    return {"duration": duration, "count": by_count}


def cached_call(path, api_name, force=False, **params):
    """带本地缓存的接口调用：缓存命中直接返回，否则请求后落盘。"""
    if not force:
        cached = read_json(path)
        if cached is not None:
            return cached
    time.sleep(API_GAP)
    data = weread.call(api_name, **params)
    write_json(path, data)
    return data


def build_profile(overall):
    """把「阅读画像」相关的全局字段整理成页面能直接用的形状。

    全部来自 /readdata/detail?mode=overall，属于用户自己的数据。
    preferTime 的顺序是从 6 点开始、到次日 5 点，这里旋转回 0-23 点。
    """
    raw_hours = overall.get("preferTime") or []
    hours = [0] * 24
    for i in range(min(24, len(raw_hours))):
        hours[(6 + i) % 24] = int(raw_hours[i] or 0)
    peak = max(hours) if hours else 0
    peak_hour = hours.index(peak) if peak else None

    authors = []
    for a in (overall.get("preferAuthor") or [])[:8]:
        authors.append({
            "name": a.get("name") or "",
            "count": a.get("count") or 0,
            "readTime": a.get("readTime") or "",
        })

    # 勋章按名字去重，保留最近一次获得，避免「21天挑战」刷满整屏
    medals, seen = [], set()
    for m in sorted(overall.get("medals") or [], key=lambda x: x.get("ctime") or 0, reverse=True):
        name = m.get("name") or ""
        if not name or name in seen:
            continue
        seen.add(name)
        medals.append({
            "name": name,
            "date": day_iso(m.get("ctime")) or "",
            "text": (m.get("rankText") or m.get("styleDesc") or m.get("hint") or "")[:60],
        })
        if len(medals) >= 12:
            break

    longest = None
    for r in overall.get("readLongest") or []:
        b = r.get("book") or {}
        if b.get("title"):
            longest = {"title": b.get("title"), "author": b.get("author") or "",
                       "cover": b.get("cover") or "", "seconds": int(r.get("readTime") or 0)}
            break

    # 年度总时长：overall.readTimes 的 key 是年份起点时间戳
    yearly = []
    for key, sec in (overall.get("readTimes") or {}).items():
        day = day_iso(key)
        if not day or not sec:
            continue
        yearly.append({"year": day[:4], "seconds": int(sec)})
    yearly.sort(key=lambda x: x["year"])

    share = overall.get("shareInfo") or {}
    all_medals = overall.get("medals") or []
    return {
        "hours": hours,
        "peakHour": peak_hour,
        "timeWord": overall.get("preferTimeWord") or "",
        "authors": authors,
        "medals": medals,
        "medalCount": len(all_medals),
        "longest": longest,
        "yearly": yearly,
        "words": {
            "finished": int(share.get("finishReadingWordCount") or 0),
            "total": int(share.get("readingWordCount") or 0),
        },
        "listen": {
            "read": int(overall.get("wrReadTime") or 0),
            "listen": int(overall.get("wrListenTime") or 0),
        },
        "overview": [
            {"title": x.get("title") or "", "value": x.get("subTitle") or "", "desc": x.get("desc") or ""}
            for x in (share.get("readOverView") or []) if x.get("title")
        ],
    }


def count_secret(shelf):
    """统计被私密过滤挡掉的内容，让页面能说明「少掉的那几本去哪了」。"""
    books = 0
    finished = {}
    for b in shelf.get("books") or []:
        bid = str(b.get("bookId") or "")
        if not bid:
            continue
        info = read_json(RAW / "books" / ("%s.json" % bid)) or {}
        if b.get("secret") != 1 and info.get("isSecret") != 1:
            continue
        books += 1
        fd = info.get("finishedDate")
        if fd:
            year = str(dt.datetime.fromtimestamp(fd, SHANGHAI).year)
            finished[year] = finished.get(year, 0) + 1
    return {"books": books, "finishedByYear": finished,
            "finished": sum(finished.values())}


def fetch_finished_books(include_secret):
    """按 finishedDate 把读完的书分组到年份，并补齐封面、简介与个人笔记。

    数据来源全部是「当前用户」：书架元数据、/book/info 的书籍简介、
    自己的划线（/book/bookmarklist）与自己的想法（/review/list/mine）。
    不拉取任何他人的点评或热门划线。
    """
    shelf = read_json(RAW / "shelf.json") or {}
    shelf_map = {}
    for b in shelf.get("books") or []:
        bid = str(b.get("bookId") or "")
        if bid and bid not in shelf_map:
            shelf_map[bid] = b

    info_dir = RAW / "bookinfo"
    mark_dir = RAW / "bookmarks"
    review_dir = RAW / "myreviews"
    grouped = {}
    # 以书架为准遍历：只读缓存目录会漏掉「这次没抓到的书」，
    # 曾经因此把刚读完的书整本漏在书墙之外。
    ids = list(shelf_map.keys())
    for path in RAW.joinpath("books").glob("*.json"):
        if path.stem not in shelf_map:
            ids.append(path.stem)

    missing = 0
    now_ts = time.time()
    # 最近一个月读过的书，详情与笔记强制刷新（新划线/新想法要能反映出来）
    fresh = {
        bid for bid, b in shelf_map.items()
        if (b.get("readUpdateTime") or 0) and now_ts - b["readUpdateTime"] < 30 * 86400
    }
    for bid in ids:
        readinfo = readinfo_of(bid) or {}
        if not readinfo:
            missing += 1
            continue
        finished = readinfo.get("finishedDate")
        if not finished:
            continue
        meta = shelf_map.get(bid) or {}
        if meta.get("secret") == 1 and not include_secret:
            continue

        # 简介 / 评分：书籍自身信息，不含他人点评。
        # 单本接口失败不能拖垮整份数据，降级为空对象即可。
        def safe_call(directory, api, **params):
            try:
                return cached_call(directory / (bid + ".json"), api,
                                   force=(bid in fresh), **params)
            except Exception as exc:
                print("  [detail] %s %s 跳过：%s" % (bid, api, str(exc)[:60]), file=sys.stderr)
                return {}

        info = safe_call(info_dir, "/book/info", bookId=bid)
        marks = safe_call(mark_dir, "/book/bookmarklist", bookId=bid)
        mine = safe_call(review_dir, "/review/list/mine", bookid=bid)

        # 章节 UID → 标题，用于给划线标注出处
        chapters = {}
        for c in marks.get("chapters") or []:
            if c.get("chapterUid") is not None:
                chapters[str(c["chapterUid"])] = c.get("title") or ""

        highlights = []
        for m in (marks.get("updated") or [])[:MAX_NOTES_PER_BOOK]:
            text = (m.get("markText") or "").strip()
            if not text:
                continue
            highlights.append({
                "text": text[:300],
                "chapter": chapters.get(str(m.get("chapterUid")), ""),
            })

        thoughts = []
        for item in (mine.get("reviews") or [])[:MAX_NOTES_PER_BOOK]:
            r = item.get("review") or {}
            content = (r.get("content") or "").strip()
            if not content:
                continue
            thoughts.append({
                "content": content[:400],
                "abstract": (r.get("abstract") or "")[:200],
                "chapter": r.get("chapterName") or "",
                "star": r.get("star") if isinstance(r.get("star"), int) else None,
            })

        year = str(dt.datetime.fromtimestamp(finished, SHANGHAI).year)
        rating_detail = info.get("newRatingDetail") or {}

        # 逐日阅读轨迹：readDetail.data 是「这本书」每天的阅读秒数，
        # 只有自己的记录，不含任何他人数据。
        rd = readinfo.get("readDetail") or {}
        daily = []
        for p in rd.get("data") or []:
            d, sec = day_iso(p.get("readDate")), p.get("readTime")
            if d and isinstance(sec, (int, float)) and sec > 0:
                daily.append({"d": d, "s": int(sec)})
        daily.sort(key=lambda x: x["d"])
        if len(daily) > MAX_READ_DAYS:
            daily = daily[-MAX_READ_DAYS:]
        reading = None
        if daily:
            reading = {
                # 起止按接口给的首次/最后阅读日；缺失时退回明细首末条
                "begin": day_iso(rd.get("beginReadingDate")) or daily[0]["d"],
                "last": day_iso(rd.get("lastReadingDate")) or daily[-1]["d"],
                "days": int(rd.get("totalReadDay") or len(daily)),
                "longest": day_iso(rd.get("longestReadingDate")),
                "longestSec": int(rd.get("longestReadingTime") or 0),
                "daily": daily,
            }

        record = {
            "bookId": bid,
            "title": meta.get("title") or info.get("title") or "",
            "author": meta.get("author") or info.get("author") or "",
            "cover": info.get("cover") or meta.get("cover") or "",
            "intro": (info.get("intro") or "").strip()[:600],
            "publisher": info.get("publisher") or "",
            "translator": info.get("translator") or "",
            "publishTime": (info.get("publishTime") or "")[:10],
            "category": info.get("category") or meta.get("category") or "",
            "rating": info.get("newRating"),
            "ratingCount": info.get("newRatingCount") or 0,
            "ratingTitle": rating_detail.get("title") or "",
            "myRating": rating_detail.get("myRating") or None,
            "finished": dt.datetime.fromtimestamp(finished, SHANGHAI).date().isoformat(),
            "seconds": readinfo.get("readingTime") or 0,
            "noteCount": len(highlights) + len(thoughts),
            "reading": reading,
            "highlights": highlights,
            "thoughts": thoughts,
        }
        if not record["title"]:
            continue
        grouped.setdefault(year, []).append(record)

    for year in grouped:
        grouped[year].sort(key=lambda x: (x["finished"], x["title"]))
    total = sum(len(v) for v in grouped.values())
    print("  [finished] 可读完书籍 %d 本，分布在 %d 个年份" % (total, len(grouped)))
    if missing:
        print("  [finished] 有 %d 本书这次仍取不到详情，已跳过（下次运行会重试）" % missing,
              file=sys.stderr)
    return grouped


def build_heatmap(years):
    """把每年的 dailyReadTimes 整理成逐日 [{date, seconds}]，按北京时间解析。"""
    result = {}
    today = dt.datetime.now(SHANGHAI).date()
    for year, data in years.items():
        daily = data.get("dailyReadTimes") or {}
        points = []
        for key, seconds in daily.items():
            day = dt.datetime.fromtimestamp(int(key), SHANGHAI).date()
            if str(day.year) != str(year):
                continue  # 跨年边界，只留属于该年的日期
            if day > today:
                continue  # 未来 0 值日不画
            points.append({"date": day.isoformat(), "seconds": int(seconds or 0)})
        points.sort(key=lambda x: x["date"])
        result[year] = points
    return result


def fetch_avatar(user):
    """把头像下载成 data URI 内嵌进页面。

    头像链接是第三方 CDN（thirdwx.qlogo.cn），可能过期或需要额外请求；
    直接内嵌成 base64（132px 的 JPEG 约 4KB）可以离线看、也能画进分享海报。
    失败不影响主流程，返回空串即可。
    """
    url = (user or {}).get("avatar") or ""
    if not url:
        return ""
    cache = RAW / "avatar.json"
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    cached = read_json(cache)
    if isinstance(cached, dict) and cached.get("key") == key and cached.get("data"):
        return cached["data"]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            raw = resp.read(600 * 1024)
    except Exception as exc:  # 网络/墙/链接失效都不该拖垮整次抓取
        print("  [avatar] 下载失败：%s" % exc, file=sys.stderr)
        return ""
    if not ctype.startswith("image/") or not raw or len(raw) > 500 * 1024:
        print("  [avatar] 跳过（非图片或体积过大）", file=sys.stderr)
        return ""
    data = "data:%s;base64,%s" % (ctype, base64.b64encode(raw).decode("ascii"))
    write_json(cache, {"key": key, "data": data})
    return data


def main():
    include_secret = "--include-secret" in sys.argv
    print("抓取开始（私密书%s）..." % ("包含" if include_secret else "排除"))

    overall = weread.call("/readdata/detail", mode="overall")
    write_json(RAW / "overall.json", overall)
    user = weread.call("/user")
    write_json(RAW / "user.json", user)
    avatar = fetch_avatar(user)
    shelf = weread.call("/shelf/sync")
    write_json(RAW / "shelf.json", shelf)

    regist = overall.get("registTime")
    candidates = year_range(regist)
    print("候选年份：%s" % ", ".join(map(str, candidates)))
    years = discover_years(candidates)

    print("拉取逐书时长（首次较慢，之后走缓存）...")
    book_cloud = fetch_books(shelf, include_secret)
    category_cloud = build_category_cloud(overall, shelf, include_secret)
    heatmap = build_heatmap(years)
    print("拉取读完书籍的封面、简介与个人笔记（首次较慢，之后走缓存）...")
    finished_books = fetch_finished_books(include_secret)

    # 年度读完加总（仅作数值核对，不断言与统计同源）
    yearly_finished = {}
    for year, data in years.items():
        for s in data.get("readStat") or []:
            if s.get("stat") == "读完":
                yearly_finished[year] = s.get("counts")

    bundle = {
        "fetchedAt": dt.datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "includeSecret": include_secret,
        "user": {
            "name": user.get("name") or "",
            "avatar": avatar,
        },
        "overall": {
            "readStat": overall.get("readStat") or [],
            "totalReadTime": overall.get("totalReadTime") or 0,
            "readRate": overall.get("readRate"),
            "wrReadTime": overall.get("wrReadTime") or 0,
            "wrListenTime": overall.get("wrListenTime") or 0,
            "authorCount": overall.get("authorCount"),
            "preferAuthor": overall.get("preferAuthor") or [],
            "yearReport": overall.get("yearReport") or [],
        },
        "shelfSummary": {
            "books": len(shelf.get("books") or []),
            "albums": len(shelf.get("albums") or []),
            "hasMp": bool(shelf.get("mp")),
            "finishedMarked": sum(
                1 for b in shelf.get("books") or [] if b.get("finishReading") == 1
            ),
        },
        "profile": build_profile(overall),
        "secretStats": {"books": 0, "finished": 0, "finishedByYear": {}}
        if include_secret else count_secret(shelf),
        "years": years,
        "yearlyFinished": yearly_finished,
        "heatmap": heatmap,
        "finishedBooks": finished_books,
        "bookCloud": book_cloud,
        "categoryCloud": category_cloud,
    }
    write_json(BUNDLE, bundle)
    print("抓取完成：%s" % BUNDLE)
    return bundle


if __name__ == "__main__":
    main()
