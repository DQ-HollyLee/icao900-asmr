# -*- coding: utf-8 -*-
"""
拿用户自己录的「同一句的正常版 vs 气声版」，反推"从正常声变成气声"到底动了什么。

核心思路：Δ(f) = 气声的平均谱(dB) - 正常声的平均谱(dB)
这条曲线是**说话人无关**的相对变换，可以直接套到任意 TTS 音色上——
比我自己凭感觉配 EQ 靠谱得多。

用法
  python analyze_breath.py <正常.wav/.m4a> <气声.wav/.m4a>
"""
import os
import re
import sys
import wave
import subprocess
import numpy as np

CACHE = r"E:\Program Files\WorkBuddyProjects\icao900-asmr\.cache"
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")

# 1/3 倍频程中心频率（取人声有效段）
BANDS = [63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800,
         1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500]


def to_wav(src, dst):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", src, "-ac", "1", "-ar", "48000", dst], check=True)


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return sr, data


def voiced_frames(x, sr, win=0.05, hop=0.025):
    """切成 50ms 帧，返回有声帧列表（按 RMS 剔除静音/尾音）"""
    n, h = int(win * sr), int(hop * sr)
    frames = []
    for s in range(0, len(x) - n, h):
        fr = x[s:s + n]
        frames.append((fr, np.sqrt(np.mean(fr ** 2))))
    rms_all = np.array([r for _, r in frames])
    thr = max(rms_all.max() * 0.05, 1e-6)
    return [f for f, r in frames if r > thr]


def welch_psd(x, sr, nperseg=2048):
    """Welch 平均功率谱。返回 (freqs, power_db)"""
    step = nperseg // 2
    win = np.hanning(nperseg)
    acc = np.zeros(nperseg // 2 + 1)
    cnt = 0
    for s in range(0, len(x) - nperseg, step):
        seg = x[s:s + nperseg] * win
        acc += np.abs(np.fft.rfft(seg)) ** 2
        cnt += 1
    if not cnt:
        seg = np.zeros(nperseg)
        cnt = 1
    p = acc / cnt
    return np.fft.rfftfreq(nperseg, 1.0 / sr), 10 * np.log10(p + 1e-20)


def band_levels(freqs, db, bands):
    """把 PSD 积分到 1/3 倍频程带里，得到每个带的平均 dB"""
    p_lin = 10 ** (db / 10.0)
    out = []
    for i, fc in enumerate(bands):
        lo = fc / (2 ** (1 / 6))
        hi = fc * (2 ** (1 / 6))
        if i == 0:
            lo = 20.0
        if i == len(bands) - 1:
            hi = 16000.0
        m = (freqs >= lo) & (freqs < hi)
        out.append(10 * np.log10(p_lin[m].mean() + 1e-20) if m.any() else np.nan)
    out = np.array(out, dtype=float)
    # 分辨率不足时会有空带（低频尤其），用相邻带插值补上，否则后面全是 NaN
    good = ~np.isnan(out)
    if good.sum() >= 2:
        fcs = np.array(bands, dtype=float)
        out[~good] = np.interp(fcs[~good], fcs[good], out[good])
    return out


def hnr(x, sr, fmin=60, fmax=400):
    """自相关法估谐波-噪声比：声带振动越强，周期性越强，HNR 越高"""
    n = int(0.05 * sr)
    lo_lag, hi_lag = int(sr / fmax), int(sr / fmin)
    vals = []
    for fr in x:
        f = fr - fr.mean()
        energy = np.dot(f, f)
        if energy < 1e-9:
            continue
        acf = np.correlate(f, f, mode="full")[len(f) - 1:]
        acf = acf / acf[0]
        peak = acf[lo_lag:hi_lag].max()
        if 0.01 < peak < 0.999:
            vals.append(10 * np.log10(peak / (1 - peak)))
    return float(np.mean(vals)) if vals else float("nan")


def summarize(tag, src, sr_hint=48000):
    wav = os.path.join(CACHE, "ab_%s.wav" % tag)
    to_wav(src, wav)
    sr, x = read_wav(wav)
    frames = voiced_frames(x, sr)
    # 只统计有声帧的能量和时长分布
    y = np.concatenate(frames) if frames else x
    rms = np.sqrt(np.mean(y ** 2))
    y = y / rms                                   # 归一化：只比谱形状，不比音量
    freqs, db = welch_psd(y, sr)
    bl = band_levels(freqs, db, BANDS)
    low = bl[np.array(BANDS) < 300].mean()
    mid = bl[(np.array(BANDS) >= 300) & (np.array(BANDS) < 2000)].mean()
    hi = bl[np.array(BANDS) >= 2000].mean()
    h = hnr(frames, sr)
    centroid = float((freqs * 10 ** (db / 10)).sum() / (10 ** (db / 10)).sum())
    return dict(tag=tag, sr=sr, dur=len(x) / sr, voiced=len(frames), bl=bl,
                low=low, mid=mid, hi=hi, hnr=h, centroid=centroid)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    a = summarize("normal", sys.argv[1])
    b = summarize("breath", sys.argv[2])

    # 用 HNR 判断谁是气声：声带参与越少，周期性越弱
    print("=" * 68)
    for d in (a, b):
        print("%-7s 时长 %.2fs  有声帧 %3d  谐波-噪声比 HNR = %6.2f dB  谱质心 %.0f Hz"
              % (d["tag"], d["dur"], d["voiced"], d["hnr"], d["centroid"]))
    normal, breath = (a, b) if a["hnr"] >= b["hnr"] else (b, a)
    print("\n→ 判定：[-%s-] 声带参与更多（正常发声），[-%s-] 周期性更弱（气声）"
          % (normal["tag"], breath["tag"]))

    print("\n频段能量对比（各自归一化后，dB）")
    print("%8s %10s %10s %10s" % ("中心Hz", "正常", "气声", "Δ(气-正)"))
    delta = breath["bl"] - normal["bl"]
    for fc, nh, bh, d in zip(BANDS, normal["bl"], breath["bl"], delta):
        bar = ("+" * int(max(d, 0) / 1.2)) or ("-" * int(max(-d, 0) / 1.2))
        print("%8d %10.1f %10.1f %+10.1f  %s" % (fc, nh, bh, d, bar))

    print("\n粗略三分：低频<300Hz %+.1f dB | 中频300-2k %+.1f dB | 高频>2k %+.1f dB"
          % (breath["low"] - normal["low"], breath["mid"] - normal["mid"],
             breath["hi"] - normal["hi"]))

    # ---- 生成可直接用的 ffmpeg equalizer 链 ----
    # 只在 Δ 明显的频点上落 6 个 EQ（太少拟合不好，太多会过拟合录音噪声）
    knots = [i for i, fc in enumerate(BANDS) if 80 <= fc <= 10000]
    step = max(1, len(knots) // 7)
    picks = knots[::step][:7]
    gains = np.clip(delta, -14, 14)
    # 轻平滑：相邻三次取平均，避免单个 1/3 oct 带的测量尖峰
    sm = np.convolve(gains, [0.25, 0.5, 0.25], mode="same")
    parts = []
    for i in picks:
        g = float(sm[i])
        if abs(g) < 0.4:
            continue
        q = 1.0
        w = BANDS[i] / q
        parts.append("equalizer=f=%d:t=q:w=%.2f:g=%+.1f" % (BANDS[i], w, g))
    print("\n套到 TTS 上的 ffmpeg 链（这是 Δ 曲线本身的 fit）：")
    print("  " + ",".join(parts))
    open(os.path.join(CACHE, "delta_eq.txt"), "w").write(",".join(parts))

    np.save(os.path.join(CACHE, "delta_curve.npy"), np.array([BANDS, delta]))


if __name__ == "__main__":
    main()
