#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
诊断：SRT 字幕时间轴 vs 成品音频的真实语音位置。

思路（不受"段数与句数不等"影响）：
  1. 把成品音频解码成 8 kHz 单声道，算 10 ms 一帧的 RMS 包络（流式，不吃内存）
  2. 对每一句，只在 [srt起点-12s, srt起点+12s] 的局部窗口里找"由静音转语音"的跳变
  3. 取离 srt 起点最近的那次跳变 → 该句的真实起点偏差

这样即便音频里句内还有小停顿（导致检测出的语音段多于 900），也不会串句。
"""
import os
import re
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio", "ICAO900_whisper_v13x12.mp3")
SRT = os.path.join(ROOT, "subtitles", "ICAO900_v13x12_bilingual.srt")
FFMPEG = os.path.join(ROOT, ".cache", "ffmpeg.exe")

SR = 8000          # 分析用采样率
HOP = 80           # 10 ms
WIN = 12           # 每句左右各看 12 秒


def build_envelope():
    """解码 -> 10ms 包络(dBFS)，缓存到 .cache/_env.npy"""
    npy = os.path.join(CACHE, "_env_diag.npy")
    if os.path.exists(npy):
        return np.load(npy)
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-v", "error",
           "-i", AUDIO, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10 ** 7)
    blocks = []
    CH = SR * 60                      # 每分钟一块
    while True:
        raw = p.stdout.read(CH * 4)
        if not raw:
            break
        a = np.frombuffer(raw, dtype="<f4")
        n = len(a) // HOP * HOP
        if n == 0:
            continue
        fr = a[:n].reshape(-1, HOP)
        blocks.append(np.sqrt((fr * fr).mean(axis=1)))
    p.stdout.close()
    p.wait()
    env = np.concatenate(blocks)
    env = 20 * np.log10(env + 1e-12)
    np.save(npy, env)
    return env


def parse_srt(path):
    raw = open(path, "rb").read().decode("utf-8-sig")
    blocks = [b for b in raw.replace("\r\n", "\n").split("\n\n") if b.strip()]
    out = []

    def pt(s):
        m = re.match(r"(\d+):(\d+):(\d+),(\d+)", s)
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000.0

    for b in blocks:
        ln = b.split("\n")
        a, e = ln[1].split(" --> ")
        out.append((pt(a), pt(e), "\n".join(ln[2:])))
    return out


def main():
    env = build_envelope()
    print("包络帧数 %d（%.1f s）" % (len(env), len(env) / 100.0))
    ps = np.percentile(env, [1, 5, 25, 50, 75, 95, 99])
    print("包络分位 dBFS: 1%%=%.1f 5%%=%.1f 25%%=%.1f 50%%=%.1f 75%%=%.1f 95%%=%.1f 99%%=%.1f" % tuple(ps))
    # 阈值取 1% 与 95% 的中点（静音地板与语音主体的分界）
    th = (ps[0] + ps[5]) / 2
    print("采用阈值 %.1f dBFS（取 1%% 与 5%% 分位中点）" % th)

    srt = parse_srt(SRT)
    print("srt 句数 %d" % len(srt))
    voiced = env > th

    drifts, ends = [], []
    miss = 0
    for i, (st, en, _txt) in enumerate(srt):
        lo = max(0, int((st - WIN) * 100))
        hi = min(len(voiced), int((st + WIN) * 100))
        seg = voiced[lo:hi]
        # 找 0->1 的跳变位置
        tr = np.where(seg[1:] & ~seg[:-1])[0] + 1
        if len(tr) == 0:
            miss += 1
            continue
        cand = lo + tr
        k = int(np.argmin(np.abs(cand / 100.0 - st)))
        drifts.append(cand[k] / 100.0 - st)
    drifts = np.array(drifts)
    print("\n=== 起点偏差（真实语音 - srt）===")
    print("参与统计 %d 句，窗口内找不到语音起点的 %d 句" % (len(drifts), miss))
    if len(drifts):
        print("中位 %+.3f s | 均值 %+.3f s | 标准差 %.3f s" %
              (np.median(drifts), drifts.mean(), drifts.std()))
        print("分位: 5%%=%+.3f 25%%=%+.3f 75%%=%+.3f 95%%=%+.3f" %
              tuple(np.percentile(drifts, [5, 25, 75, 95])))
        print("绝对偏差 >0.5s 的句数: %d (%.1f%%)" %
              ((np.abs(drifts) > 0.5).sum(), 100.0 * (np.abs(drifts) > 0.5).mean()))
        # 是否随时间线性漂移
        t = np.array([s[0] for s in srt[:len(drifts)]])
        a, b = np.polyfit(t, drifts, 1)
        print("线性拟合: 偏差 = %.4e * t %+.3f  → 全长漂移 %.2f s" % (a, b, a * t.max()))
        # 抽几句
        print("\n抽样：")
        for i in [0, 99, 299, 449, 699, 899]:
            if i < len(drifts):
                print("  第%3d句  srt %8.3f  偏差 %+6.3f s" % (i + 1, srt[i][0], drifts[i]))


if __name__ == "__main__":
    main()
