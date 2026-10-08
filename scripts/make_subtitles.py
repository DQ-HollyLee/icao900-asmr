# -*- coding: utf-8 -*-
"""
把「中英对照原文」+「成品时间戳」合成字幕文件（SRT / WebVTT）。

用法
    python scripts/make_subtitles.py                       # 用默认路径，生成双语 + 纯英 + 纯中
    python scripts/make_subtitles.py --mode continuous      # 字幕连续显示（不保留句间静音空档）
    python scripts/make_subtitles.py --cn <对照txt> --ts <timestamps.txt> --out subtitles

输入
    --cn   中英对照 txt（**GB18030 编码**，每行英文 + 下一行中文，带 `N. ` 序号）
    --ts   时间戳目录（TSV：`序号 \\t HH:MM:SS \\t 规范化文本`）

输出（默认 --mode gap）
    subtitles/ICAO900_<tag>_bilingual.srt   双语（英文在上，中文在下）
    subtitles/ICAO900_<tag>_en.srt          纯英文
    subtitles/ICAO900_<tag>_zh.srt          纯中文
    subtitles/ICAO900_<tag>_bilingual.vtt   WebVTT（双语）

两种时间模式
    gap（默认）  字幕停留到本句说完 + 0.2 s，句间 2.3 s 静音不留字幕 —— 视觉节奏与音频一致
    continuous  字幕一直显示到下一句开始 —— 适合跟读，但静音期屏幕也有字

兼容性
    SRT 一律写 **UTF-8 with BOM + CRLF**，这是 Windows 播放器（PotPlayer / VLC /
    Windows Media Player）与 Premiere Pro / 剪映识别最稳的组合。
"""
import os
import re
import sys
import difflib
import argparse
import subprocess
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CN = r"E:\BaiduNetdiskDownload\民航飞行员英语900句.txt"
GAP_SEC = 2.5      # 句间静音（成品实际值）
TAIL = 0.2         # 句末多留的时间
MIN_SHOW = 1.2     # 最短停留（短句不至于一闪而过）


# ---------------------------------------------------------------- 读取
def read_cn_en(path):
    """解析中英对照文件。返回 [(idx, en, zh), ...]，并把标题/空行跳过。"""
    for enc in ("gb18030", "utf-8", "utf-8-sig"):
        try:
            raw = open(path, "rb").read().decode(enc)
            print("对照文件编码：%s" % enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        sys.exit("无法解码对照文件：%s" % path)

    lines = [l.strip() for l in raw.replace("\r\n", "\n").split("\n")]
    rows, heads, pending = [], [], None   # heads 收集章节标题
    num = re.compile(r"^(\d+)\.\s*(.+)$")
    # ⚠️ 这个文件有三个坑，三点都要处理：
    #   ① 中文翻译可能以 `N. ` 开头**（如第 99 句的译文「118.3 校波。」）→
    #      必须按序号连续性驱动，见下面 expected 的约束；
    #   ② 长英文句会被折成两行（如第 87 句）→ 无中文字符的行要并入上一句的英文；
    #   ③ 中文翻译也会被折成两行（如第 82 句）→ 上条译文未以句号结尾时继续追加。
    title = re.compile(r"^第[一二三四五六七八九十百]+[章节部分篇]")
    stop_zh = "。！？!?"
    expected, rows, heads = 1, [], []

    def has_zh(s):
        return any("一" <= c <= "鿿" for c in s)

    for l in lines:
        if not l:
            continue
        m = num.match(l)
        if m and abs(int(m.group(1)) - expected) <= 1:
            n = int(m.group(1))
            rows.append([n, m.group(2).strip(), ""])
            expected = n + 1
            continue
        if not rows:
            heads.append(l)
            continue
        cur = rows[-1]
        if not has_zh(l):                       # ② 英文续行
            cur[1] = cur[1].rstrip() + " " + l
        elif cur[2] == "":                      # 第一行中文
            cur[2] = l
        elif cur[2][-1] not in stop_zh:         # ③ 中文续行
            cur[2] += l
        elif title.match(l):                    # 章节标题
            heads.append(l)
        else:                                   # 归属不明：并入上条译文比丢掉更好
            cur[2] += l
    rows = [(a, b, c) for a, b, c in rows]
    print("章节标题 %d 行：%s" % (len(heads), " / ".join(heads[:5])))
    return rows


def read_timestamps(path):
    rows = []
    for l in open(path, encoding="utf-8"):
        if l.startswith("#") or not l.strip():
            continue
        parts = l.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        idx, t = int(parts[0]), parts[1]
        h, m, s = [int(x) for x in t.split(":")]
        rows.append((idx, h * 3600 + m * 60 + s, parts[2]))
    return rows


def probe_duration(mp3):
    """用 ffprobe 拿成品总时长（秒）。失败返回 None。"""
    ff = os.path.join(ROOT, ".cache", "ffmpeg.exe")
    for exe in (ff, "ffprobe", "ffprobe.exe"):
        try:
            out = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration",
                                  "-of", "default=noprint_wrappers=1:nokey=1", mp3],
                                 capture_output=True, text=True, timeout=60)
            v = float(out.stdout.strip())
            if v > 0:
                return v
        except Exception:
            continue
    return None


# ---------------------------------------------------------------- 校验
def verify(cn_rows, ts_rows):
    """对齐校验：行数一致、序号连续、每句有中文，并用首词 + 相似度抽查串行的可能。"""
    ok = True
    if len(cn_rows) != len(ts_rows):
        print("❌ 行数不一致：对照 %d vs 时间戳 %d" % (len(cn_rows), len(ts_rows)))
        ok = False
    idx_cn = [r[0] for r in cn_rows]
    idx_ts = [r[0] for r in ts_rows]
    if idx_cn != idx_ts:
        print("❌ 序号序列不一致")
        ok = False
    if idx_cn != list(range(1, len(idx_cn) + 1)):
        miss = sorted(set(range(1, max(idx_cn) + 1)) - set(idx_cn))
        print("❌ 序号不连续，缺失：%s" % miss[:20])
        ok = False
    no_zh = [r[0] for r in cn_rows if not r[2]]
    if no_zh:
        print("⚠️ 缺中文翻译 %d 句：%s" % (len(no_zh), no_zh[:20]))
    # 译文本身就没写完的（源语料缺陷，非解析问题）。例：第 45 句原文即为
    # 「保持高度层 350，可以按计划航路飞往目的地机场，」后面直接接下一句。
    trunc = [r[0] for r in cn_rows if r[2] and r[2][-1] not in "。！？!?"]
    if trunc:
        print("ℹ️ 中文疑未收尾 %d 句（源语料如此，未改动）：%s" % (len(trunc), trunc[:20]))

    # 相似度抽查：英文原文 vs 时间戳里的规范化文本（同一句，措辞会因 ICAO 读法而变，故阈值放宽）
    def norm(s):
        return re.sub(r"[^a-z ]", " ", s.lower()).split()

    def med(offset):
        rs = []
        for k in range(len(cn_rows)):
            j = k + offset
            if not (0 <= j < len(ts_rows)):
                continue
            rs.append(difflib.SequenceMatcher(
                None, " ".join(norm(cn_rows[k][1])), " ".join(norm(ts_rows[j][2]))).ratio())
        rs.sort()
        return rs[len(rs) // 2] if rs else 0.0

    m0, m1, mm1 = med(0), med(1), med(-1)
    print("相似度中位：对齐 %.2f ／ 前移一句 %.2f ／ 后移一句 %.2f" % (m0, m1, mm1))
    if m1 > m0 + 0.08 or mm1 > m0 + 0.08:
        print("❌ 疑似整体串行：平移后反而更匹配")
        ok = False

    bad = []
    for (i, en, _zh), (_j, _t, spoken) in zip(cn_rows, ts_rows):
        r = difflib.SequenceMatcher(
            None, " ".join(norm(en)), " ".join(norm(spoken))).ratio()
        if r < 0.35:
            bad.append((i, round(r, 2), en, spoken))
    print("相似度抽查：%d / %d 句低于 0.35" % (len(bad), len(cn_rows)))
    for i, r, en, spoken in bad[:15]:
        print("   #%d (%.2f) 原文：%s" % (i, r, en[:70]))
        print("           规范：%s" % spoken[:70])
    return ok


# ---------------------------------------------------------------- 生成
def fmt_srt(t):
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def fmt_vtt(t):
    return fmt_srt(t).replace(",", ".")


def build(items, mode, total):
    """items = [(idx, start, en, zh), ...] → [(start, end), ...]"""
    spans = []
    for k, (idx, st, _en, _zh) in enumerate(items):
        if k + 1 < len(items):
            nxt = items[k + 1][1]
            if mode == "continuous":
                end = nxt - 0.05
            else:
                end = nxt - (GAP_SEC - TAIL)
                if end - st < MIN_SHOW:
                    end = min(nxt - 0.05, st + MIN_SHOW)
        else:
            end = (total if total else st + 6.0)
        if end <= st:
            end = st + 0.5
        spans.append((st, end))
    return spans


def write_srt(path, items, spans, pick):
    """pick: 'both' | 'en' | 'zh'"""
    out = []
    for n, ((idx, _st, en, zh), (s, e)) in enumerate(zip(items, spans), 1):
        if pick == "en":
            body = en
        elif pick == "zh":
            body = zh
        else:
            body = en if not zh else "%s\n%s" % (en, zh)
        out.append("%d\n%s --> %s\n%s\n" % (n, fmt_srt(s), fmt_srt(e), body))
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(out))


def write_vtt(path, items, spans):
    out = ["WEBVTT", ""]
    for n, ((idx, _st, en, zh), (s, e)) in enumerate(zip(items, spans), 1):
        body = en if not zh else "%s\n%s" % (en, zh)
        out.append("%d\n%s --> %s\n%s\n" % (n, fmt_vtt(s), fmt_vtt(e), body))
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(out))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cn", default=DEFAULT_CN)
    ap.add_argument("--ts", default=os.path.join(ROOT, "05_timestamps_whisper_v13x12.txt"))
    ap.add_argument("--out", default=os.path.join(ROOT, "subtitles"))
    ap.add_argument("--tag", default="v13x12")
    ap.add_argument("--mode", choices=["gap", "continuous"], default="gap")
    ap.add_argument("--mp3", default=os.path.join(ROOT, "audio", "ICAO900_whisper_v13x12.mp3"))
    ap.add_argument("--no-verify", action="store_true")
    a = ap.parse_args()

    cn_rows = read_cn_en(a.cn)
    ts_rows = read_timestamps(a.ts)
    print("对照 %d 句 / 时间戳 %d 句" % (len(cn_rows), len(ts_rows)))

    if not a.no_verify and not verify(cn_rows, ts_rows):
        sys.exit("对齐校验未通过，请修数据后重试（加 --no-verify 可强制生成）")

    items = [(i, st, en, zh) for (i, en, zh), (_j, st, _sp) in zip(cn_rows, ts_rows)]
    total = probe_duration(a.mp3)
    if total:
        print("成品总时长 %.3f s（%s）" % (total, str(timedelta(seconds=int(total)))))
    spans = build(items, a.mode, total)

    os.makedirs(a.out, exist_ok=True)
    base = "ICAO900_%s" % a.tag
    write_srt(os.path.join(a.out, base + "_bilingual.srt"), items, spans, "both")
    write_srt(os.path.join(a.out, base + "_en.srt"), items, spans, "en")
    write_srt(os.path.join(a.out, base + "_zh.srt"), items, spans, "zh")
    write_vtt(os.path.join(a.out, base + "_bilingual.vtt"), items, spans)
    print("已生成 4 个字幕到 %s  （模式=%s）" % (a.out, a.mode))
    print("示例首条：")
    print("  %s --> %s | %s | %s" % (fmt_srt(spans[0][0]), fmt_srt(spans[0][1]),
                                     items[0][2], items[0][3]))


if __name__ == "__main__":
    main()
