# -*- coding: utf-8 -*-
"""解决 [whispers] 标签续航不足：句中会退回本音。

对比几种"中途补标签"策略，用谐噪比 HNR 量化每一段到底有没有变成正常发声：
  HNR 高 = 声带振动强 = 本音（不是我们要的）
  HNR 低 = 周期性弱 = 气声
对每句取 前1/3 / 中1/3 / 末1/3 三段的 HNR 中位值，若数值从前往后明显上涨 = 标签掉了。
"""
import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
UA = {"User-Agent": "Mozilla/5.0"}
EMMA = "nDJIICjR9zfJExIFeSCN"
MODEL = os.environ.get("EL_MODEL", "eleven_v4")


# ------------------------------------------------------------------ 策略
def every_n(text, n):
    """每 n 个词注入一个 [whispers]，维持整句气声状态。"""
    ws = text.split()
    out = []
    for i, w in enumerate(ws):
        if i and i % n == 0:
            out.append("[whispers]")
        out.append(w)
    return " ".join(out)


STRONG = ("[whispers throughout the entire sentence, never stop whispering, "
          "keep every single word breathy and hushed, do not raise your voice at all] ")

STRATEGIES = [
    ("S1 句首一次                ", lambda t: "[whispers] " + t),
    ("S2 句首+末重申             ", lambda t: "[whispers] " + t + " [whispers]"),
    ("S3 每5词补一次             ", lambda t: "[whispers] " + every_n(t, 5)),
    ("S4 每3词补一次             ", lambda t: "[whispers] " + every_n(t, 3)),
    ("S5 强化描述                ", lambda t: STRONG + t),
    ("S6 强化描述+每5词补        ", lambda t: STRONG + every_n(t, 5)),
]


# ------------------------------------------------------------------ 工具
def tts(text, key, voice, out, model=MODEL, stability=.35, similarity=.65, style=.3):
    body = {"text": text, "model_id": model,
            "voice_settings": {"stability": stability, "similarity_boost": similarity,
                               "style": style, "speed": 1.0}}
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128" % voice,
        data=json.dumps(body).encode(), method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json", **UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            open(out, "wb").write(r.read())
        return True
    except urllib.error.HTTPError as e:
        print("   失败 %s %s" % (e.code, e.read().decode("utf-8", "ignore")[:160]))
        return False


def load(p, sr=24000):
    o = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", p,
                        "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                       capture_output=True)
    return np.frombuffer(o.stdout, dtype=np.float32), sr


def voiced(x, sr):
    """裁掉静音，返回有效段。"""
    win = int(sr * 0.02)
    env = np.array([np.sqrt((x[i:i + win] ** 2).mean()) for i in range(0, len(x) - win, win)])
    idx = np.where(env > env.max() * 0.08)[0]
    if len(idx) == 0:
        return x
    return x[idx[0] * win: idx[-1] * win]


def hnr_and_rms(seg, sr):
    """中位 HNR(dB) 与 RMS(dB)。"""
    frame, hop = int(sr * 0.040), int(sr * 0.020)
    lo, hi = int(sr / 500), int(sr / 70)
    hs, envs = [], []
    for s in range(0, len(seg) - frame, hop):
        f = seg[s:s + frame].astype(np.float64)
        f = f - f.mean()
        e = np.sqrt((f ** 2).mean())
        if e < 1e-4:
            continue
        envs.append(e)
        ac = np.correlate(f, f, "full")[frame - 1:]
        ac /= ac[0] + 1e-12
        r = float(ac[lo:hi].max())
        r = min(max(r, 0.05), 0.995)
        hs.append(10 * np.log10(r / (1 - r)))
    return (float(np.median(hs)) if hs else 0.0), 20 * np.log10(np.median(envs) + 1e-12)


def analyze(p, out_lines, label):
    x, sr = load(p)
    x = voiced(x, sr)
    n = len(x) // 3
    parts = [x[:n], x[n:2 * n], x[2 * n:]]
    res = [hnr_and_rms(s, sr) for s in parts]
    h = [r[0] for r in res]
    e = [r[1] for r in res]
    drift = h[2] - h[0]
    flag = "标签掉了" if drift > 3 else ("基本稳住" if drift > -1 else "全程气声")
    print("%s  HNR 前%5.1f 中%5.1f 末%5.1f  漂移%+5.1f dB -> %s" %
          (label, h[0], h[1], h[2], drift, flag))
    out_lines.append((label, h, e, drift, flag))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--lines", default="80,5")
    ap.add_argument("--strategies", default="1,2,3,4,5,6")
    ap.add_argument("--noaudio", action="store_true")
    a = ap.parse_args()

    src = [l.strip() for l in open(os.path.join(ROOT, "02_tts_icao.txt"), encoding="utf-8")
           if l.strip()]
    picks = [int(s) for s in a.strategies.split(",")]
    strats = [STRATEGIES[i - 1] for i in picks]

    lines_ = []
    for ln in [int(s) for s in a.lines.split(",")]:
        text = src[ln - 1]
        print("\n=== 第 %d 句（%d 词）：%s ===" % (ln, len(text.split()), text[:70]))
        rows = []
        n = 1
        for name, fn in strats:
            i = picks[n - 1]
            raw = os.path.join(CACHE, "wh_%d_s%d.mp3" % (ln, i))
            if not os.path.exists(raw) or os.path.getsize(raw) < 1000:
                ok = tts(fn(text), a.key, EMMA, raw, model=a.model)
                if not ok:
                    n += 1
                    continue
            analyze(raw, rows, name)
            n += 1
        lines_.append((ln, len(text.split()), rows))

    print("\n" + "=" * 78)
    print("判读：HNR 越高 = 越像正常发声；末段相对首段上涨 >3 dB 说明后半句变回本音。")
    best = {}
    for ln, wc, rows in lines_:
        print("\n第 %d 句（%d 词）" % (ln, wc))
        for label, h, e, drift, flag in rows:
            print("  %s HNR %5.1f→%5.1f→%5.1f  漂移%+5.1f  %s" %
                  (label, h[0], h[1], h[2], drift, flag))
            best[label.strip()] = best.get(label.strip(), []) + [drift]

    print("\n各策略跨句平均漂移（越小越好，负值=越到后面越气）：")
    for k, v in sorted(best.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        print("  %-28s %+.1f dB" % (k, sum(v) / len(v)))


if __name__ == "__main__":
    main()
