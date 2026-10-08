# -*- coding: utf-8 -*-
"""S7 方案：长句切成 ≤8 词的小段，每段独立带 [whispers] 合成，再无缝拼接。
避免 S4“句中插标签”可能引入的停顿/朗读风险，同时保证每段开头都有标签续力。
"""
import json
import os
import subprocess
import sys
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
FFPROBE = os.path.join(CACHE, "ffprobe.exe")
UA = {"User-Agent": "Mozilla/5.0"}
EMMA = "nDJIICjR9zfJExIFeSCN"
KEY = sys.argv[1]
MODEL = sys.argv[2] if len(sys.argv) > 2 else "eleven_v4"
LINES = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "80,316,82").split(",")]
JOINGAP = 0.12          # 分句拼接时的呼吸间隙（秒）


def split_chunks(text, maxw=8):
    """按逗号优先、其次按 maxw 词切分；返回小段列表（保留标点）。"""
    parts, cur = [], []
    for w in text.split():
        cur.append(w)
        too_long = len(cur) >= maxw
        ends = w.rstrip().endswith((",", ".", ";", ":"))
        if too_long or ends:
            parts.append(" ".join(cur))
            cur = []
    if cur:
        parts.append(" ".join(cur))
    return parts


def tts(text, out):
    body = {"text": text, "model_id": MODEL,
            "voice_settings": {"stability": .35, "similarity_boost": .65,
                               "style": .3, "speed": 1.0}}
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128" % EMMA,
        data=json.dumps(body).encode(), method="POST",
        headers={"xi-api-key": KEY, "Content-Type": "application/json", **UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        open(out, "wb").write(r.read())


def concat(parts, gap, out):
    g = os.path.join(CACHE, "hs_gap.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=mono", "-t", str(gap),
                    "-ar", "44100", "-ac", "1", g], check=True)
    lst = os.path.join(CACHE, "hs_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for i, p in enumerate(parts):
            if i:
                f.write("file '%s'\n" % g.replace("\\", "/"))
            f.write("file '%s'\n" % p.replace("\\", "/"))
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                    "-safe", "0", "-i", lst, "-c:a", "libmp3lame", "-b:a", "192k", out],
                   check=True)


def load(p, sr=24000):
    o = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", p,
                        "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"], capture_output=True)
    return np.frombuffer(o.stdout, dtype=np.float32), sr


def voiced(x, sr):
    win = int(sr * 0.02)
    env = np.array([np.sqrt((x[i:i + win] ** 2).mean()) for i in range(0, len(x) - win, win)])
    idx = np.where(env > env.max() * 0.08)[0]
    return x[idx[0] * win: idx[-1] * win] if len(idx) else x


def hnr(seg, sr):
    frame, hop = int(sr * .04), int(sr * .02)
    lo, hi = int(sr / 500), int(sr / 70)
    hs = []
    for s in range(0, len(seg) - frame, hop):
        f = seg[s:s + frame].astype(np.float64)
        f -= f.mean()
        if np.sqrt((f ** 2).mean()) < 1e-4:
            continue
        ac = np.correlate(f, f, "full")[frame - 1:]
        ac /= ac[0] + 1e-12
        r = min(max(float(ac[lo:hi].max()), .05), .995)
        hs.append(10 * np.log10(r / (1 - r)))
    return float(np.median(hs)) if hs else 0.


def drift(p):
    x, sr = load(p)
    x = voiced(x, sr)
    n = len(x) // 3
    h = [hnr(x[:n], sr), hnr(x[n:2 * n], sr), hnr(x[2 * n:], sr)]
    return h, h[2] - h[0]


def dur(p):
    o = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", p], capture_output=True, text=True)
    return float(o.stdout.strip() or 0)


src = [l.strip() for l in open(os.path.join(ROOT, "02_tts_icao.txt"), encoding="utf-8")
       if l.strip()]
print("S7 分块方案（每块 ≤8 词，独立带标签，间隙 %.2f s）\n" % JOINGAP)
print("句    词数  块数   时长     第三            HNR前→中→末        漂移")
outs = []
for ln in LINES:
    text = src[ln - 1]
    cs = split_chunks(text)
    parts = []
    for i, c in enumerate(cs):
        p = os.path.join(CACHE, "hs_%d_%02d.mp3" % (ln, i))
        if not os.path.exists(p) or os.path.getsize(p) < 800:
            tts("[whispers] " + c, p)
        parts.append(p)
    out = os.path.join(CACHE, "wh_%d_s7.mp3" % ln)
    concat(parts, JOINGAP, out)
    h, d = drift(out)
    wc = len(text.split())
    print("%-5d %4d  %3d  %6.2fs    %-14s %5.1f→%5.1f→%5.1f   %+5.1f  %s" %
          (ln, wc, len(cs), dur(out), "", h[0], h[1], h[2], d,
           "标签掉了" if d > 3 else "基本稳住"))
    outs.append(out)

# 对比音频：S1 基线 vs S7
gap = os.path.join(CACHE, "hs_g2.mp3")
subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=mono", "-t", "1.2", "-c:a", "libmp3lame",
                "-b:a", "192k", gap], check=True)
lst = os.path.join(CACHE, "hs_ab.txt")
with open(lst, "w", encoding="utf-8") as f:
    for ln in LINES:
        for s in (1, 7):
            p = os.path.join(CACHE, "wh_%d_s%d.mp3" % (ln, s))
            if os.path.exists(p):
                f.write("file '%s'\n" % p.replace("\\", "/"))
                f.write("file '%s'\n" % gap.replace("\\", "/"))
out = os.path.join(AUDIO, "hold_s1_vs_s7.mp3")
subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                "-safe", "0", "-i", lst, "-c:a", "libmp3lame", "-b:a", "256k", out], check=True)
print("\nAB 对比：%s（%.1f s）" % (out, dur(out)))
print("顺序：" + " / ".join("第%d句 S1→S7" % ln for ln in LINES))
