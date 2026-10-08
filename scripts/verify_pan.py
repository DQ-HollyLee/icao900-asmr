# -*- coding: utf-8 -*-
"""验证声场参数。

难点：语料里每句之间有 2.5 秒静音，直接用窗口 RMS 会把静音也算进去，
得到 -240 dB 这种假数据。这里只统计"有声帧"，静音一律跳过。

检查三项：
  1. 左右极限配比 ≈ 90:10（±19 dB）
  2. 单侧停留时长落在 20~30 秒
  3. 总音量起伏 ≤ 10%
"""
import os
import sys
import math
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import tts_generate as G

CACHE = G.CACHE
FF = G.FFMPEG
SEG = os.path.join(CACHE, "speech_seg.mp3")
OUT = os.path.join(CACHE, "pan_verify.mp3")
SR = 8000          # 分析用的低采样率：只比电平，不需要高频，省内存


def load():
    """解码成 numpy，返回 (L, R) 数组"""
    p = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-i", OUT,
                        "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                       capture_output=True)
    a = np.frombuffer(p.stdout, dtype=np.float32).reshape(-1, 2)
    return a[:, 0].astype(np.float64), a[:, 1].astype(np.float64)


def windows(L, R, win=2.0, hop=1.0):
    """逐窗口统计有声帧的 L/R 功率，返回 [(t, LdB, RdB, total_dB)]"""
    n = int(win * SR)
    h = int(hop * SR)
    fr = int(0.02 * SR)
    m = len(L) // fr * fr
    e = (L[:m].reshape(-1, fr) ** 2 + R[:m].reshape(-1, fr) ** 2).mean(axis=1)
    thr = e.max() * 10 ** (-3.0)          # 相对峰值 -30 dB 以内算有声
    out = []
    for s in range(0, len(L) - n, h):
        seg_l, seg_r = L[s:s + n], R[s:s + n]
        k = len(seg_l) // fr * fr
        if k == 0:
            continue
        ee = (seg_l[:k].reshape(-1, fr) ** 2 + seg_r[:k].reshape(-1, fr) ** 2).mean(axis=1)
        sel = ee > thr
        if sel.sum() < 5:                 # 有声帧太少，跳过
            continue
        pl = (seg_l[:k].reshape(-1, fr)[sel] ** 2).mean()
        pr = (seg_r[:k].reshape(-1, fr)[sel] ** 2).mean()
        out.append((s / SR, 10 * np.log10(pl + 1e-20),
                    10 * np.log10(pr + 1e-20),
                    10 * np.log10(pl + pr + 1e-20)))
    return out


def main():
    if not os.path.exists(SEG):
        src = os.path.join(CACHE, "full_cat.mp3")
        G.ff("-ss", "1800", "-t", "600", "-i", src, "-ac", "1", "-ar", "44100",
             "-c:a", "libmp3lame", "-b:a", "192k", SEG)
    G.asmr_chain(SEG, OUT, ctl_path=os.path.join(CACHE, "pan_ctl_verify.raw"))
    L, R = load()
    rows = windows(L, R)
    if not rows:
        sys.exit("没能取到有效窗口")

    target = 20 * math.log10(G.PAN_BALANCE / (1 - G.PAN_BALANCE))
    print("=== 设定 ===")
    print("极限配比 %.2f:%.2f → 目标两耳差 %.1f dB" %
          (G.PAN_BALANCE, 1 - G.PAN_BALANCE, target))
    print("停留 %.0f~%.0f 秒随机，换边 %.1f 秒，远近深度 %.0f%%\n" %
          (G.PAN_HOLD_MIN, G.PAN_HOLD_MAX, G.PAN_SWAP_SEC, G.DIST_DEPTH * 100))

    diffs = [x[1] - x[2] for x in rows]
    print("=== 1. 左右差别 ===")
    print("  实测最大  L>R %+.2f dB    R>L %+.2f dB   （目标 ±%.1f）" %
          (max(diffs), min(diffs), target))

    print("\n=== 2. 单侧停留时长 ===")
    TH = 12.0                                   # 超过这个差值才算"停留在一侧"
    runs, cur = [], None
    for t, l, r, _ in rows:
        d = l - r
        side = 1 if d > TH else (-1 if d < -TH else 0)
        if side == 0:
            if cur:
                runs.append(cur)
                cur = None
            continue
        if cur is None or cur[0] != side:
            if cur:
                runs.append(cur)
            cur = (side, t, t)
        else:
            cur = (side, cur[1], t)
    if cur:
        runs.append(cur)
    durs = [(r[2] - r[1]) for r in runs if r[2] > r[1]]
    if durs:
        print("  共 %d 段停留，时长(秒)：%s" %
              (len(durs), ", ".join("%.0f" % d for d in durs)))
        print("  范围 %.0f ~ %.0f 秒   （要求 %.0f~%.0f）" %
              (min(durs), max(durs), G.PAN_HOLD_MIN, G.PAN_HOLD_MAX))
    else:
        print("  未检出")

    print("\n=== 3. 总音量起伏 ===")
    tot = [x[3] for x in rows]
    span = max(tot) - min(tot)
    print("  有声段总能量范围 %.2f ~ %.2f dB，波动 %.2f dB" %
          (min(tot), max(tot), span))
    print("  折算最大降幅 %.1f%%   （要求 <= %.0f%%）" %
          ((1 - 10 ** (-span / 20)) * 100, G.DIST_DEPTH * 100))

    print("\n=== 前 80 秒逐秒明细 ===")
    print("  时间    L(dB)    R(dB)    L-R")
    for t, l, r, _ in rows[:80]:
        d = l - r
        tag = "全左" if d > 15 else ("全右" if d < -15 else
                                    ("偏左" if d > 3 else ("偏右" if d < -3 else "居中")))
        print("  %5.0fs %8.2f %8.2f  %+7.2f  %s" % (t, l, r, d, tag))


if __name__ == "__main__":
    main()
