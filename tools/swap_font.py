"""从开源字体 TTF 提取「书」「迹」轮廓，替换 templates/index.html 中的艺术字路径。

用法：
  python tools/swap_font.py tools/font_candidates/mashanzheng.ttf --apply

不传 --apply 时只做预览（输出字形 bbox 与路径长度），不修改任何文件。
字体须为 SIL OFL 等允许嵌入再分发的授权；替换后请在 README 的字体署名处同步。
"""

import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "index.html"
CHARS = "书迹"
TARGET_CX, TARGET_CY = 500, 297
TARGET_W, TARGET_H = 800, 770


def u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def s16(b, o):
    return struct.unpack_from(">h", b, o)[0]


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def tables(data):
    out = {}
    for i in range(u16(data, 4)):
        o = 12 + i * 16
        out[data[o:o + 4].decode("latin1")] = (u32(data, o + 8), u32(data, o + 12))
    return out


def cmap_map(data, off):
    best = None
    for i in range(u16(data, off + 2)):
        rec = off + 4 + i * 8
        platform, encoding, sub = u16(data, rec), u16(data, rec + 2), u32(data, rec + 4)
        if platform in (0, 3) and u16(data, off + sub) == 4:
            best = off + sub
            if platform == 3 and encoding in (1, 10):
                break
    if best is None:
        raise ValueError("字体缺少 format4 cmap")
    seg = u16(data, best + 6) // 2
    ends, starts = best + 14, best + 16 + seg * 2
    deltas, ranges = starts + seg * 2, starts + seg * 4
    result = {}
    for i in range(seg):
        end, start = u16(data, ends + i * 2), u16(data, starts + i * 2)
        if start == 0xFFFF:
            continue
        delta, ro = s16(data, deltas + i * 2), u16(data, ranges + i * 2)
        for c in range(start, end + 1):
            if ro == 0:
                gid = (c + delta) & 0xFFFF
            else:
                gid = u16(data, ranges + i * 2 + ro + 2 * (c - start))
                if gid:
                    gid = (gid + delta) & 0xFFFF
            if gid:
                result[c] = gid
    return result


def glyph_contours(data, t, gid):
    loca, glyf = t["loca"][0], t["glyf"][0]
    short = s16(data, t["head"][0] + 50) == 0
    if short:
        a = u16(data, loca + gid * 2) * 2
        b = u16(data, loca + (gid + 1) * 2) * 2
    else:
        a, b = u32(data, loca + gid * 4), u32(data, loca + (gid + 1) * 4)
    if a == b:
        return []
    o = glyf + a
    nc = s16(data, o)
    if nc < 0:
        return []
    p = o + 10
    ends = [u16(data, p + i * 2) for i in range(nc)]
    npts = ends[-1] + 1
    p += nc * 2
    ilen = u16(data, p)
    p += 2 + ilen
    flags = []
    while len(flags) < npts:
        f = data[p]
        p += 1
        flags.append(f)
        if f & 8:
            flags.extend([f] * data[p])
            p += 1
    xs, x = [], 0
    for f in flags:
        if f & 2:
            d = data[p]
            p += 1
            x += d if f & 16 else -d
        elif not (f & 16):
            x += s16(data, p)
            p += 2
        xs.append(x)
    ys, y = [], 0
    for f in flags:
        if f & 4:
            d = data[p]
            p += 1
            y += d if f & 32 else -d
        elif not (f & 32):
            y += s16(data, p)
            p += 2
        ys.append(y)
    contours, start = [], 0
    for end in ends:
        contours.append([(xs[i], ys[i], bool(flags[i] & 1)) for i in range(start, end + 1)])
        start = end + 1
    return contours


def contours_to_path(contours, sx, sy, tx, ty):
    """保持 y 向上（TT 坐标），做缩放平移后输出 path。"""
    cmds = []
    for contour in contours:
        if not contour:
            continue
        idx = next((i for i, pt in enumerate(contour) if pt[2]), None)
        pts = [(x * sx + tx, y * sy + ty) for x, y, _ in contour]
        on = [c[2] for c in contour]
        if idx is None:
            x0 = (pts[0][0] + pts[-1][0]) / 2
            y0 = (pts[0][1] + pts[-1][1]) / 2
            cmds.append(f"M{x0:.1f} {y0:.1f}")
            ctrl = pts[0]
            for i in range(1, len(pts)):
                px, py = pts[i]
                cmds.append(f"Q{ctrl[0]:.1f} {ctrl[1]:.1f} {(ctrl[0]+px)/2:.1f} {(ctrl[1]+py)/2:.1f}")
                ctrl = (px, py)
            cmds.append(f"Q{ctrl[0]:.1f} {ctrl[1]:.1f} {x0:.1f} {y0:.1f}Z")
            continue
        ordered = list(zip(pts[idx:] + pts[:idx], on[idx:] + on[:idx]))
        cmds.append(f"M{ordered[0][0][0]:.1f} {ordered[0][0][1]:.1f}")
        i, n = 1, len(ordered)
        while i <= n:
            (px, py), is_on = ordered[i % n]
            if is_on:
                cmds.append(f"L{px:.1f} {py:.1f}")
                i += 1
            else:
                (nx, ny), n_on = ordered[(i + 1) % n]
                if n_on:
                    cmds.append(f"Q{px:.1f} {py:.1f} {nx:.1f} {ny:.1f}")
                    i += 2
                else:
                    cmds.append(f"Q{px:.1f} {py:.1f} {(px+nx)/2:.1f} {(py+ny)/2:.1f}")
                    i += 1
        cmds.append("Z")
    return "".join(cmds)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    font = Path(sys.argv[1])
    apply = "--apply" in sys.argv
    if not font.exists():
        print("字体文件不存在：", font)
        return 1
    data = font.read_bytes()
    t = tables(data)
    cmap = cmap_map(data, t["cmap"][0])
    paths = []
    for ch in CHARS:
        gid = cmap.get(ord(ch))
        if not gid:
            print(f"字体不含字形：{ch}")
            return 1
        contours = glyph_contours(data, t, gid)
        flat = [p for c in contours for p in c]
        x0, x1 = min(p[0] for p in flat), max(p[0] for p in flat)
        y0, y1 = min(p[1] for p in flat), max(p[1] for p in flat)
        scale = min(TARGET_W / (x1 - x0), TARGET_H / (y1 - y0))
        tx = TARGET_CX - (x0 + x1) / 2 * scale
        ty = TARGET_CY - (y0 + y1) / 2 * scale
        paths.append(contours_to_path(contours, scale, scale, tx, ty))
        print(f"{ch}: bbox=({x0},{y0})-({x1},{y1}) scale={scale:.3f} path={len(paths[-1])} chars")

    html = TEMPLATE.read_text(encoding="utf-8")
    pat = re.compile(r'(<g transform="translate\((\d+),802\) scale\(1,-1\)"><path d=")([^"]*)("/></g>)')
    matches = list(pat.finditer(html))
    if len(matches) != 2:
        print(f"模板中应有两个艺术字路径，实际找到 {len(matches)} 个，已中止")
        return 1
    out, last = [], 0
    for i, m in enumerate(matches):
        out.append(html[last:m.start(3)])
        out.append(paths[i])
        last = m.end(3)
    out.append(html[last:])
    new_html = "".join(out)
    if apply:
        TEMPLATE.write_text(new_html, encoding="utf-8")
        print("已替换 templates/index.html 中的两个艺术字路径")
    else:
        print("预览模式：未修改文件。加 --apply 才会写入模板。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
