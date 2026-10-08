#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
判定成品音频里到底有没有末尾那几句。

做法：把每句 clip 的「有声段包络」归一化重采样成固定长度的特征向量（形状指纹），
在音频的候选区间里滑窗比对。归一化到固定点数后与时间尺度无关，
所以 clip 是变速前的长度也不影响匹配。

对照组用第 1~10 句（必然存在），若末尾句的匹配分数与对照组相当，说明存在；
若明显偏低且找不到合理落点，说明这几句在成品里被丢掉了。
"""
import os
import subprocess

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
CLIPS = os.path.join(CACHE, "clips_v13x12")
AUDIO = os.path.join(ROOT, "audio", "ICAO900_whisper_v13x12.mp3")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
SR, HOP = 8000, 80
TH = -50.0
NPT = 64


def clip_env(path):
    raw = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-i", path,
                          "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, dtype="<f4")
    n = len(a) // HOP * HOP
    if n == 0:
        return None
    e = 20 * np.log10(np.sqrt((a[:n].reshape(-1, HOP) ** 2).mean(axis=1)) + 1e-12)
    v = e > TH
    if not v.any():
        return None
    i0, i1 = np.argmax(v), len(v) - np.argmax(v[::-1])
    return e[i0:i1], (i1 - i0) * 0.01


def feat(e):
    if e is None or len(e) < 4:
        return None
    x = np.interp(np.linspace(0, len(e) - 1, NPT), np.arange(len(e)), e)
    x = np.clip(x, -60, None)
    x = x - x.mean()
    s = x.std()
    return x / s if s > 1e-9 else None


def main():
    env = np.load(os.path.join(CACHE, "_env_diag.npy"))
    total = len(env) / 100.0
    print("音频 %.3f s" % total)

    groups = {
        "对照组 第1~10句": list(range(1, 11)),
        "末尾 第881~900句": list(range(881, 901)),
    }
    for name, idxs in groups.items():
        print("\n=== %s ===" % name)
        # 候选区间：对照组看开头 200 s，末尾组看最后 700 s
        lo, hi = (0, 200) if idxs[0] < 100 else (max(0, total - 700), total)
        for i in idxs:
            p = os.path.join(CLIPS, "%04d.mp3" % i)
            ce, cdur = clip_env(p)
            f = feat(ce)
            if f is None:
                print("  第%3d句  clip 无声，跳过" % i)
                continue
            # clip 是变速前长度，成品里约短 1/1.15
            wlen = max(0.5, cdur / 1.15)
            wn = int(wlen * 100)
            best, bpos = -2.0, None
            for st in range(int(lo * 100), int(hi * 100) - wn, 5):
                w = env[st:st + wn]
                wf = feat(w)
                if wf is None:
                    continue
                c = float(np.dot(f, wf) / NPT)
                if c > best:
                    best, bpos = c, st / 100.0
            flag = "✅" if best > 0.55 else ("⚠️" if best > 0.40 else "❌")
            print("  %s 第%3d句  最佳匹配 %.2f @ %.2f s  (clip语音 %.2f s)"
                  % (flag, i, best, bpos if bpos else -1, cdur))


if __name__ == "__main__":
    main()
