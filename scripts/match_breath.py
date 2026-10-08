# -*- coding: utf-8 -*-
"""
用用户本人录的「正常声 vs 气声」做模板，把 TTS 的音色推成同样的气声。

为什么不直接套用户的 Δ：
    用户的 Δ = 从"正常说话"变成"气声"要花的变化量。
    但 ElevenLabs 的 [whispers] 输出**本身已经是气声**了，再套一遍会过头。
所以只补差额：
    Δ_need(f) = Δ_用户(f) - Δ_TTS(f)
    Δ_用户 = 谱(用户气声) - 谱(用户正常)
    Δ_TTS  = 谱(TTS气声) - 谱(TTS正常)
两边都是"自己跟自己比"，说话人性别差异大部分被抵消。

整形不用 ffmpeg 的 bell 串联（拟合差、Q 值还容易写错），改成 STFT 域直接乘曲线。

用法
  python match_breath.py run --key <KEY>
"""
import os
import sys
import json
import wave
import argparse
import subprocess
import urllib.request
import numpy as np

ROOT = r"E:\Program Files\WorkBuddyProjects\icao900-asmr"
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
MODEL_ID = "eleven_v3"
OUT_FMT = "mp3_44100_192"
LINE_NO = 4

JESSICA = "cgSgspJ2msm6clMCkdW9"
SETTINGS = {"stability": 0.35, "similarity_boost": 0.60,
            "style": 0.35, "speed": 1.0, "use_speaker_boost": True}

BREATH = ("[ASMR whisper spoken almost entirely on breath, pure airy voiceless tone "
          "with very little vocal cord vibration, breath clearly audible, soft and close] ")

BANDS = np.array([63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800,
                  1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000,
                  10000, 12500], dtype=float)


# ---------------- 频谱分析（与 analyze_breath.py 同一套口径） ----------------
def to_wav(src, dst):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", src, "-ac", "1", "-ar", "48000", dst], check=True)


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return sr, x


def voiced(x, sr, win=0.05, hop=0.025):
    n, h = int(win * sr), int(hop * sr)
    fr = [(x[s:s + n], np.sqrt(np.mean(x[s:s + n] ** 2)))
          for s in range(0, max(1, len(x) - n), h)]
    if not fr:
        return [x]
    thr = max(np.array([r for _, r in fr]).max() * 0.05, 1e-6)
    return [f for f, r in fr if r > thr]


def long_term_db(path):
    """返回 1/3 倍频程的长期平均谱（已按整体 RMS 归一，只保留形状）"""
    wav = os.path.join(CACHE, "mb_%d.wav" % (abs(hash(path)) % 10 ** 9))
    if not path.lower().endswith(".wav"):
        to_wav(path, wav)
    else:
        to_wav(path, wav)
    sr, x = read_wav(wav)
    frames = voiced(x, sr)
    y = np.concatenate(frames) if frames else x
    y = y / (np.sqrt(np.mean(y ** 2)) + 1e-9)

    n = 2048
    win = np.hanning(n)
    acc = np.zeros(n // 2 + 1)
    cnt = 0
    for s in range(0, len(y) - n, n // 2):
        acc += np.abs(np.fft.rfft(y[s:s + n] * win)) ** 2
        cnt += 1
    if not cnt:
        acc += 1e-12
        cnt = 1
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    psd = 10 * np.log10(acc / cnt + 1e-20)

    out = []
    for i, fc in enumerate(BANDS):
        lo = 20.0 if i == 0 else fc / 2 ** (1 / 6)
        hi = 16000.0 if i == len(BANDS) - 1 else fc * 2 ** (1 / 6)
        m = (freqs >= lo) & (freqs < hi)
        out.append(psd[m].mean() if m.any() else np.nan)
    out = np.array(out)
    good = ~np.isnan(out)
    if good.sum() >= 2:
        out[~good] = np.interp(BANDS[~good], BANDS[good], out[good])
    return out, sr, y


# ---------------- STFT 频谱整形 ----------------
def shape(x, sr, bands_db, n=4096, hop=1024):
    """按 1/3 倍频程曲线整形：STFT 域乘以插值后的增益，再 overlap-add 回来"""
    g = np.clip(bands_db, -18, 18)
    k = np.array([0.2, 0.3, 0.5, 0.6, 0.5, 0.3, 0.2])   # 轻平滑，去掉测量毛刺
    g = np.convolve(g, k / k.sum(), mode="same")
    f = np.fft.rfftfreq(n, 1.0 / sr)
    gain = np.interp(np.log(np.clip(f, 30, 16000)), np.log(BANDS), g)
    gain = 10 ** (gain / 20.0)

    win = np.hanning(n)
    out = np.zeros(len(x) + n)
    for s in range(0, max(1, len(x) - n), hop):
        out[s:s + n] += np.fft.irfft(np.fft.rfft(x[s:s + n] * win) * gain) * win
    out = out[:len(x)]
    out /= ((win ** 2).sum() / hop)          # 补偿 overlap-add 的叠加增益
    peak = np.abs(out).max()
    return out / peak * 0.7 if peak > 0 else out


def save_wav(x, sr, path):
    d = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(d)


def tts(text, key, voice, out, tag=""):
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return                                   # 已有就不重合成，省额度
    url = "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=%s" % (voice, OUT_FMT)
    body = {"text": tag + text, "model_id": MODEL_ID, "voice_settings": SETTINGS}
    req = urllib.request.Request(url, data=json.dumps(body).encode())
    req.add_header("xi-api-key", key)
    req.add_header("accept", "audio/mpeg")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=180) as r:
        open(out, "wb").write(r.read())


def loudnorm(src, dst, i=-20):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                    "-af", "loudnorm=I=%d:TP=-2:LRA=9" % i, "-ac", "2", "-ar", "48000",
                    "-c:a", "libmp3lame", "-b:a", "256k", dst], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run"])
    ap.add_argument("--key", default=None)
    ap.add_argument("--line", type=int, default=LINE_NO)
    ap.add_argument("--normal-ref", default=r"D:\33748\Documents\录音\录音 (2).m4a")
    ap.add_argument("--breath-ref", default=r"D:\33748\Documents\录音\录音 (3).m4a")
    a = ap.parse_args()
    key = a.key or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("缺少 API Key")

    src = [l.rstrip("\n") for l in open(os.path.join(ROOT, "02_tts_icao.txt"),
                                        encoding="utf-8") if l.strip()]
    text = src[a.line - 1]

    # TTS 侧同一个音色的"正常"和"气声"两句（伸自己的已经气化了多少）
    tts_norm = os.path.join(CACHE, "mb_tts_normal.mp3")
    tts_br = os.path.join(CACHE, "mb_tts_breath.mp3")
    tts(text, key, JESSICA, tts_norm, tag="")
    tts(text, key, JESSICA, tts_br, tag=BREATH)

    un, _, _ = long_term_db(a.normal_ref)
    ub, _, _ = long_term_db(a.breath_ref)
    tn, srt, xbr = long_term_db(tts_br)
    tnn, _, _ = long_term_db(tts_norm)

    d_user = ub - un                 # 真人：正常 → 气声
    d_tts = tn - tnn                 # TTS：正常 → 气声（已经有了一部分）
    need = d_user - d_tts            # 还要补多少

    print("\n%8s %10s %10s %10s" % ("中心Hz", "用户Δ", "TTS已有Δ", "还要补"))
    for f, du, dt, nd in zip(BANDS, d_user, d_tts, need):
        print("%8.0f %+10.1f %+10.1f %+10.1f" % (f, du, dt, nd))

    need = np.where(BANDS < 300, np.clip(need, -14, 6), need)   # 低频别掏太狠
    np.save(os.path.join(CACHE, "need_curve.npy"), np.array([BANDS, need]))

    _, sr, x = long_term_db(tts_br)

    # 完整匹配可能过头（2kHz 处要补 +19dB，容易变沙/齿音爆炸），
    # 所以再给一档六成的，中间站 LYWebView
    strengths = [(0.6, "6成"), (1.0, "10成")]
    outs = []
    gap = os.path.join(CACHE, "mb_gap.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=stereo", "-t", "1.4",
                    "-c:a", "libmp3lame", "-b:a", "256k", gap], check=True)

    parts = [("真人参照", a.breath_ref), ("TTS原样", tts_br)]
    for name, p in parts:
        dst = os.path.join(CACHE, "mb_out_%s.mp3" % name)
        loudnorm(p, dst)
        outs.append((name, dst))
    for s, sname in strengths:
        shaped = shape(x, sr, need * s)
        wavp = os.path.join(CACHE, "mb_shaped_%d.wav" % int(s * 10))
        save_wav(shaped, sr, wavp)
        mp3p = os.path.join(CACHE, "mb_out_%s.mp3" % sname)
        loudnorm(wavp, mp3p)
        outs.append(("补齐%s" % sname, mp3p))

    lst = os.path.join(CACHE, "mb_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for _, p in outs:
            f.write("file '%s'\nfile '%s'\n" % (gap, p))
        f.write("file '%s'\n" % gap)
    out = os.path.join(AUDIO, "breath_matched.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", lst,
                    "-c:a", "libmp3lame", "-b:a", "256k", out], check=True)
    print("\n样音：", out)
    print("顺序：" + "  →  ".join(n for n, _ in outs))

    # 顺便把 execute 后的谱也量一遍，看有没有走偏
    ref, _, _ = long_term_db(a.breath_ref)
    for n, p in outs:
        b, _, _ = long_term_db(p)
        err = np.abs((b - b.mean()) - (ref - ref.mean()))
        print("  %-10s 与真人参照的形状偏差 RMS = %.2f dB" % (n, np.sqrt(np.mean(err ** 2))))


if __name__ == "__main__":
    main()
