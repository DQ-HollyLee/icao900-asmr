# -*- coding: utf-8 -*-
"""估算每段试音的中位基频 F0 —— 客观反映"听起来的年龄感"。
儿童 250~400 Hz，成年女性 165~255 Hz，成年男性 85~180 Hz。
"""
import json
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")


def load(p, sr=24000):
    out = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", p,
                          "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                         capture_output=True)
    return np.frombuffer(out.stdout, dtype=np.float32), sr


def f0_median(x, sr):
    # 去掉首尾静音，只留能量段
    win = int(sr * 0.02)
    env = np.array([np.sqrt((x[i:i + win] ** 2).mean()) for i in range(0, len(x) - win, win)])
    thr = env.max() * 0.08
    idx = np.where(env > thr)[0]
    if len(idx) == 0:
        return 0.0
    x = x[idx[0] * win: idx[-1] * win]

    frame = int(sr * 0.040)          # 40 ms 帧
    hop = int(sr * 0.020)
    lo, hi = int(sr / 500), int(sr / 70)
    vals = []
    for s in range(0, len(x) - frame, hop):
        f = x[s:s + frame].astype(np.float64)
        f = f - f.mean()
        if np.sqrt((f ** 2).mean()) < 1e-4:
            continue
        ac = np.correlate(f, f, "full")[frame - 1:]
        ac = ac / (ac[0] + 1e-12)
        seg = ac[lo:hi]
        k = int(np.argmax(seg))
        if seg[k] < 0.35:            # 周期性太弱 = 纯气声，跳过
            continue
        vals.append(sr / (lo + k))
    return float(np.median(vals)) if vals else 0.0


def main():
    meta = json.load(open(sys.argv[1], encoding="utf-8")) if len(sys.argv) > 1 else None
    items = []
    for i in range(1, 30):
        p = os.path.join(CACHE, "kid_%02d.mp3" % i)
        if not os.path.exists(p):
            break
        items.append(i)
    print("段   名称                              基频F0     判读")
    labels = {}
    if meta:
        labels = {int(k): v for k, v in meta.items()}
    for i in items:
        x, sr = load(os.path.join(CACHE, "kid_%02d.mp3" % i))
        f = f0_median(x, sr)
        if f == 0:
            judge = "纯气声 / 无周期性"
        elif f >= 250:
            judge = "童声区间"
        elif f >= 205:
            judge = "偏年轻"
        elif f >= 180:
            judge = "成年女声"
        else:
            judge = "偏低沉"
        print("%2d   %-32s %6.1f Hz   %s" % (i, labels.get(i, ""), f, judge))


if __name__ == "__main__":
    main()
