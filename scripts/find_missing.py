#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
用 900 个 clip 的时长，与成品音频里实测到的 890 个语音段做动态规划序列比对，
判断成品是"某几段里并了两句"还是"整句被漏掉了"，并列出漏掉的句子。

判据
----
  D_j  = 音频里第 j 段的实测语音时长（890 段）
  Q_i  = k · clip_i 时长（900 句，k 为变速+修剪的综合系数）
  DP 允许四种转移，代价单位是"秒的误差"：
    1 句↔1 段      cost = |D_j - Q_i|
    2 句↔1 段(并句) cost = |D_j - (Q_i + Q_{i+1} + 短停顿)|
    该句在音频中缺失  cost = MISS_PEN
    该段是多余切分    cost = SPUR_PEN
"""
import os
import subprocess

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
CLIPS = os.path.join(CACHE, "clips_v13x12")
AUDIO = os.path.join(ROOT, "audio", "ICAO900_whisper_v13x12.mp3")
OLD_TS = os.path.join(ROOT, "05_timestamps_whisper_v13x12.txt")
FFPROBE = os.path.join(CACHE, "ffprobe.exe")

SR, HOP = 8000, 80
TH = -50.0
ANCHOR_SIL = 1.5
EDGE_SIL = 0.35
MISS_PEN = 3.0
SPUR_PEN = 3.0
INTRA_GAP = 0.5          # 并句时两句之间的停顿估计


def probe_duration(p):
    return float(subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                                 "-of", "default=noprint_wrappers=1:nokey=1", p],
                                capture_output=True, text=True).stdout.strip())


def main():
    total = probe_duration(AUDIO)
    env = np.load(os.path.join(CACHE, "_env_diag.npy"))
    v = env > TH

    def sil_before(p):
        q, n = p, 0
        while q > 0 and not v[q - 1]:
            q -= 1
            n += 1
        return n * 0.01

    def sil_after(p):
        q, n = p, 0
        while q < len(v) and not v[q]:
            q += 1
            n += 1
        return n * 0.01

    up = np.where(np.diff(v.astype(np.int8)) == 1)[0] + 1
    anchors = [0] + [p for p in up if sil_before(p) >= ANCHOR_SIL]
    A = np.array(anchors) / 100.0
    dn = np.where(np.diff(v.astype(np.int8)) == -1)[0] + 1
    E = np.array([p for p in dn if sil_after(p) >= EDGE_SIL]) / 100.0

    D = np.empty(len(A))
    for j, s in enumerate(A):
        nxt = A[j + 1] if j + 1 < len(A) else total
        c = E[(E > s) & (E < nxt)]
        D[j] = c[-1] if len(c) else nxt - 0.05
    D = D - A
    print("音频实测语音段 %d 个，时长 中位 %.2f s，最大 %.2f s" % (len(D), np.median(D), D.max()))

    C = np.array([probe_duration(os.path.join(CLIPS, "%04d.mp3" % i)) for i in range(1, 901)])
    print("clip 时长 中位 %.2f s，最大 %.2f s（变速前）" % (np.median(C), C.max()))

    gaps = np.diff(A)
    G = float(np.median(gaps))
    print("音频实测句间静音中位 %.3f s" % G)

    # k 用"总时长守恒"迭代估计：每次按当前对齐重算
    k = (total - len(A) * G) / C.sum()
    for _ in range(6):
        Q = k * C
        res = align(D, Q)
        matched = [(i, j) for i, j in res if i is not None and j is not None]
        if not matched:
            break
        nk = np.sum(D[[j for _i, j in matched]]) / np.sum(C[[i for i, _j in matched]])
        if abs(nk - k) < 1e-6:
            k = nk
            break
        k = nk
    print("变速系数 k = %.4f" % k)

    Q = k * C
    res = align(D, Q)
    miss = [i for i, j in res if j is None]
    spur = [j for i, j in res if i is None]
    merged = [(i, j) for i, j in res if isinstance(i, tuple)]
    print()
    print("=== 比对结果 ===")
    print("音频中缺失的句子：%d 句" % len(miss))
    print("被判为多余的切分：%d 处" % len(spur))
    print("一段里并了两句：%d 处" % len(merged))

    rows = []
    for l in open(OLD_TS, encoding="utf-8"):
        if l.startswith("#") or not l.strip():
            continue
        p = l.rstrip("\n").split("\t")
        rows.append((int(p[0]), p[2]))

    if miss:
        print("\n缺失句子清单（第 N 句 / clip 时长 / 文本）：")
        for i in miss:
            print("  #%d  clip %.2f s  →  %s" % (rows[i][0], C[i], rows[i][1][:70]))
    if merged:
        print("\n并在一起的段：")
        for (a, b), j in merged:
            print("  段#%d（%.2f s）= 第%d句 + 第%d句" % (j + 1, D[j], rows[a][0], rows[b][0]))


def align(D, Q):
    """DP：返回 [(句子索引 or (i,i+1) or None, 段索引 or None), ...]"""
    n, m = len(Q), len(D)
    INF = 1e18
    f = np.full((n + 1, m + 1), INF)
    back = np.empty((n + 1, m + 1), dtype=object)
    f[0, 0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            cur = f[i, j]
            if cur >= INF:
                continue
            if i < n and j < m:                                  # 1↔1
                c = cur + abs(D[j] - Q[i])
                if c < f[i + 1, j + 1]:
                    f[i + 1, j + 1] = c
                    back[i + 1, j + 1] = ("m", i, j)
            if i + 1 < n and j < m:                              # 2↔1 并句
                c = cur + abs(D[j] - (Q[i] + Q[i + 1] + INTRA_GAP))
                if c < f[i + 2, j + 1]:
                    f[i + 2, j + 1] = c
                    back[i + 2, j + 1] = ("g", i, j)
            if i < n:                                            # 该句缺失
                c = cur + MISS_PEN
                if c < f[i + 1, j]:
                    f[i + 1, j] = c
                    back[i + 1, j] = ("s", i, None)
            if j < m:                                            # 该段多余
                c = cur + SPUR_PEN
                if c < f[i, j + 1]:
                    f[i, j + 1] = c
                    back[i, j + 1] = ("x", None, j)
    i, j, out = n, m, []
    while i > 0 or j > 0:
        b = back[i, j]
        if b is None:
            break
        t, bi, bj = b
        if t == "m":
            out.append((bi, bj)); i -= 1; j -= 1
        elif t == "g":
            out.append(((bi, bi + 1), bj)); i -= 2; j -= 1
        elif t == "s":
            out.append((bi, None)); i -= 1
        else:
            out.append((None, bj)); j -= 1
    out.reverse()
    print("DP 总代价 %.1f" % f[n, m])
    return out


if __name__ == "__main__":
    main()
