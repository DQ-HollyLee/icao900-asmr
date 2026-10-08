#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从成品音频本身重建 900 句的时间轴，替代旧的时间戳文件。

为什么必须重建
--------------
旧时间戳 05_timestamps_whisper_v13x12.txt 是拿「逐句 clip 的时长」累加出来的，
而 clip 是**变速（atempo 1.15）之前**的原始长度，比成品里的实际时长长约 1.2 倍。
为了让总时长对上，脚本反解出的句间静音只有 1.83 s（真实是 2.71 s），
于是每句的起点都带上了累积误差：实测落点常常是"上一句的结尾"而不是"本句的开头"。

本脚本的做法（音频实测为骨架 + 结构模型补漏）
----------------------------------------------
  1. 对成品音频做 10 ms 能量包络，取「前面静音 >= 1.5 s」的起点作为高置信句间边界
     （实测：句间静音 2.4~3.2 s，句内停顿 < 0.8 s，两者之间没有任何样本 → 判据很干净）
  2. 但音频里有 10 处句间静音没检测出来（相邻两句被并成一段），故只能拿到 890 个锚点
  3. 用结构模型补齐：先按总时长反解出「变速系数 k」与「真实句间静音 G」，
     得到 900 句的预测时间轴 P；再用 890 个锚点逐句校正 P 的累积误差
  4. 最终起点 = 能用锚点就用锚点，否则用就近校正过的预测值

输出
----
  05_timestamps_whisper_v13x12_audio.txt（秒字段带毫秒，供 make_subtitles.py 使用）
"""
import os
import subprocess

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
CLIPS = os.path.join(CACHE, "clips_v13x12")
AUDIO = os.path.join(ROOT, "audio", "ICAO900_whisper_v13x12.mp3")
OLD_TS = os.path.join(ROOT, "05_timestamps_whisper_v13x12.txt")
NEW_TS = os.path.join(ROOT, "05_timestamps_whisper_v13x12_audio.txt")
FFPROBE = os.path.join(CACHE, "ffprobe.exe")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")

SR, HOP = 8000, 80          # 分析用 8 kHz / 10 ms
TH = -50.0                  # 有声判定 dBFS
ANCHOR_SIL = 1.5            # 高置信句间边界：前面静音 >= 1.5 s
EDGE_SIL = 0.35             # 句首/句末判定的最短静音
NEAR = 3.0                  # 锚点与预测值匹配的最大距离


def probe_duration(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


def envelope():
    npy = os.path.join(CACHE, "_env_diag.npy")
    if os.path.exists(npy):
        return np.load(npy)
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-v", "error",
           "-i", AUDIO, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10 ** 7)
    blocks = []
    while True:
        raw = p.stdout.read(SR * 60 * 4)
        if not raw:
            break
        a = np.frombuffer(raw, dtype="<f4")
        n = len(a) // HOP * HOP
        if n:
            blocks.append(np.sqrt((a[:n].reshape(-1, HOP) ** 2).mean(axis=1)))
    p.stdout.close()
    p.wait()
    env = 20 * np.log10(np.concatenate(blocks) + 1e-12)
    np.save(npy, env)
    return env


def silence_before(v, p):
    q, n = p, 0
    while q > 0 and not v[q - 1]:
        q -= 1
        n += 1
    return n * 0.01


def silence_after(v, p):
    q, n = p, 0
    while q < len(v) and not v[q]:
        q += 1
        n += 1
    return n * 0.01


def main():
    total = probe_duration(AUDIO)
    env = envelope()
    v = env > TH
    print("成品音频 %.3f s，包络 %d 帧" % (total, len(env)))

    # ---- 1. 高置信句间边界 ----
    up = np.where(np.diff(v.astype(np.int8)) == 1)[0] + 1
    anchors = [0]
    for p in up:
        if silence_before(v, p) >= ANCHOR_SIL:
            anchors.append(p)
    anchors = np.array(anchors) / 100.0
    print("高置信句间边界 %d 个（900 句需要 899 个，缺 %d 处漏检）"
          % (len(anchors), 900 - len(anchors)))

    # ---- 2. clip 时长（变速前） ----
    durs = []
    for i in range(1, 901):
        hits = [f for f in os.listdir(CLIPS)
                if f == "%04d.mp3" % i or f.startswith("%04d_" % i)]
        if not hits:
            raise SystemExit("缺第 %d 句的 clip" % i)
        durs.append(probe_duration(os.path.join(CLIPS, sorted(hits)[0])))
    C = np.array(durs)

    # ---- 3. 反解变速系数 k 与真实句间静音 G ----
    # 每段：起点=锚点，句末=该段内最后一个「后面静音 >= EDGE_SIL」的下降沿
    dn = np.where(np.diff(v.astype(np.int8)) == -1)[0] + 1
    ends_all = np.array([p for p in dn if silence_after(v, p) >= EDGE_SIL]) / 100.0
    speech = np.empty(len(anchors))
    for k, s in enumerate(anchors):
        nxt = anchors[k + 1] if k + 1 < len(anchors) else total
        cand = ends_all[(ends_all > s) & (ends_all < nxt)]
        speech[k] = cand[-1] if len(cand) else min(nxt - 0.05, s + 1.0)
    seg = speech - anchors                     # 每段内的语音时长
    total_speech = seg.sum()
    k = total_speech / C.sum()                 # 变速+修剪的综合系数
    G = (total - total_speech) / 899.0
    print("语音总时长 %.1f s | 变速系数 k=%.4f | 真实句间静音 G=%.3f s" % (total_speech, k, G))

    # ---- 4. 结构模型预测 + 锚点校正 ----
    P = np.concatenate([[0.0], np.cumsum(k * C[:-1] + G)])
    onset = np.empty(900)
    j, drift = 0, 0.0
    used_anchor = 0
    for i in range(900):
        guess = P[i] + drift
        if j < len(anchors) and abs(anchors[j] - guess) <= NEAR:
            onset[i] = anchors[j]
            drift += anchors[j] - guess      # 用锚点逐步吸收累积误差
            j += 1
            used_anchor += 1
        else:
            onset[i] = guess                 # 漏检处：用校正后的预测值补
    print("采用音频实测锚点 %d 句，结构模型补齐 %d 句" % (used_anchor, 900 - used_anchor))

    # 单调化 + 最小间隔
    for i in range(1, 900):
        if onset[i] <= onset[i - 1] + 0.30:
            onset[i] = onset[i - 1] + 0.30
    onset[-1] = min(onset[-1], total - 1.0)

    # ---- 5. 自检 ----
    def frac(t0, t1):
        a, b = max(0, int(t0 * 100)), min(len(v), int(t1 * 100))
        return float(v[a:b].mean()) if b > a else float("nan")

    before = np.array([frac(s - 0.60, s - 0.05) for s in onset])
    after = np.array([frac(s + 0.05, s + 0.60) for s in onset])
    print("\n=== 新时间轴自检 ===")
    print("起点前 0.55s 有声占比 中位 %.2f（应≈0）| 起点后 0.55s 有声占比 中位 %.2f（应≈1）"
          % (np.nanmedian(before), np.nanmedian(after)))
    print("起点落在静音中的句数 %d / 900" % (before <= 0.05).sum())
    print("起点后立刻有声的句数 %d / 900" % (after >= 0.95).sum())

    old = []
    for l in open(OLD_TS, encoding="utf-8"):
        if l.startswith("#") or not l.strip():
            continue
        h, m, s = [int(x) for x in l.split("\t")[1].split(":")]
        old.append(h * 3600 + m * 60 + s)
    old = np.array(old)
    err_old = onset - old
    print("\n相对旧时间戳的修正量：中位 %+.2f s | 均值 %+.2f s | 最大 |%.2f| s"
          % (np.median(err_old), err_old.mean(), np.abs(err_old).max()))
    print("修正量 >3 s 的句数 %d (%.0f%%)" % ((np.abs(err_old) > 3).sum(), 100 * (np.abs(err_old) > 3).mean()))

    # ---- 6. 写出 ----
    rows = []
    for l in open(OLD_TS, encoding="utf-8"):
        if l.startswith("#") or not l.strip():
            continue
        p = l.rstrip("\n").split("\t")
        rows.append((int(p[0]), p[2]))
    with open(NEW_TS, "w", encoding="utf-8", newline="\n") as f:
        f.write("# 句\t开始时间\t原文\n")
        f.write("# 由 scripts/rebuild_timeline.py 依据成品音频实测重建（亚秒精度）\n")
        for i, (idx, text) in enumerate(rows):
            t = onset[i]
            f.write("%d\t%02d:%02d:%06.3f\t%s\n" % (idx, int(t // 3600), int((t % 3600) // 60), t % 60, text))
    print("\n已写出 %s" % NEW_TS)
    print("下一步：python scripts/make_subtitles.py --ts %s" % os.path.basename(NEW_TS))
    print("（提示：句间静音实测中位 %.2f s，make_subtitles.py 的 GAP_SEC 应改为此值）" % G)


if __name__ == "__main__":
    main()
