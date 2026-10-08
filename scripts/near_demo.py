# -*- coding: utf-8 -*-
"""
用现成的 whisper 干声做「距离感」AB 对比，**不消耗任何 API 额度**。

同一个句子连放三遍：
  ① 现状  —— 当前成品链路（房间回声 + 10.5k 低通 + 强展宽）
  ② 去房间 —— 去掉回声、放开高频，其余不变
  ③ 贴耳  —— 近讲效应（低频抬升）+ 压缩 + 几乎居中，模拟嘴就在耳边

用法：python near_demo.py            （可选 --lines 4,5,87）
"""
import os
import sys
import argparse
import subprocess

ROOT = r"E:\Program Files\WorkBuddyProjects\icao900-asmr"
CACHE = os.path.join(ROOT, ".cache")
DRY = os.path.join(CACHE, "clips_whisper")     # 已合成好的 [whispers] 干声
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")

TEMPO = 1.15
LINES = [4, 5, 87]

# ① 现状：与 ICAO900_whisper.mp3 完全相同的主体处理（省掉声场漂移，句长短无需漂移）
CHAIN_NOW = (
    "aresample=48000,atempo=%g,highpass=f=55,lowpass=f=10500,"
    "bass=g=1.8:f=110:w=0.7,"
    "aecho=0.86:0.9:32|57:0.20|0.11,"
    "asplit=2[l][r];"
    "[l]adelay=11,lowpass=f=8800,volume=0.9589,"
    "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[L];"
    "[r]highpass=f=95,lowpass=f=11000,volume=0.965,"
    "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[R];"
    "[L][R]amerge=inputs=2,extrastereo=m=1.6,"
    "loudnorm=I=-18:TP=-2:LRA=11"
) % TEMPO

# ② 去房间：去掉 aecho，高频放到 14 kHz，仍保留一点宽度
CHAIN_DRY = (
    "aresample=48000,atempo=%g,highpass=f=45,lowpass=f=14000,"
    "asplit=2[l][r];"
    "[l]lowpass=f=12000,volume=0.99,"
    "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[L];"
    "[r]highpass=f=80,volume=0.99,"
    "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[R];"
    "[L][R]amerge=inputs=2,extrastereo=m=0.6,"
    "loudnorm=I=-18:TP=-2:LRA=11"
) % TEMPO

# ③ 温柔：用户原话"原来的音频感觉都是在耳边喊出来的"——方向不是更近更大，而是更柔更小。
#    削中高频硬度（喊的主因）+ 深压缩抹平动态 + 整体降 2 dB，几乎居中。
#    （早期曾做过"猛抬低频 6.5dB"的播客式近讲版，太壮太有存在感，被否。）
CHAIN_NEAR = (
    "aresample=48000,atempo=%g,highpass=f=55,"
    "equalizer=f=2200:t=q:w=1.2:g=-2.5,"
    "equalizer=f=6500:t=q:w=2.0:g=-3.0,"
    "equalizer=f=11000:t=q:w=1.0:g=-2.0,"
    "lowshelf=f=160:g=1.5:t=q:w=0.7,"
    "acompressor=threshold=-30dB:ratio=4:attack=25:release=400:makeup=3,"
    "asplit=2[l][r];"
    "[l]volume=1.0,aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[L];"
    "[r]adelay=0.4,volume=0.985,"
    "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[R];"
    "[L][R]amerge=inputs=2,"
    "loudnorm=I=-20:TP=-2.5:LRA=8"
) % TEMPO

CHAINS = [("现状", CHAIN_NOW), ("去房间", CHAIN_DRY), ("温柔", CHAIN_NEAR)]


def run(args):
    p = subprocess.run(args, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr.decode("utf-8", "ignore"))
        p.check_returncode()


def silence(path, sec):
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=48000:cl=stereo", "-t", str(sec),
         "-c:a", "libmp3lame", "-b:a", "256k", path])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", default=",".join(map(str, LINES)))
    ap.add_argument("--out", default=os.path.join(AUDIO, "whisper_nearmic_AB.mp3"))
    a = ap.parse_args()
    lines = [int(x) for x in a.lines.replace("，", ",").split(",") if x.strip()]

    gap = os.path.join(CACHE, "nd_gap.mp3")
    silence(gap, 0.8)
    long_gap = os.path.join(CACHE, "nd_gap_long.mp3")
    silence(long_gap, 2.0)

    lst = os.path.join(CACHE, "nd_list.txt")
    notes = []
    with open(lst, "w", encoding="utf-8") as f:
        f.write("file '%s'\n" % long_gap)
        for ln in lines:
            src = os.path.join(DRY, "%04d.mp3" % ln)
            if not os.path.exists(src):
                print("[SKIP] 缺少干声 %s" % src)
                continue
            for name, chain in CHAINS:
                dst = os.path.join(CACHE, "nd_%d_%s.mp3" % (ln, name))
                run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                     "-i", src, "-filter_complex", chain,
                     "-ac", "2", "-ar", "48000",
                     "-c:a", "libmp3lame", "-b:a", "256k", dst])
                f.write("file '%s'\n" % dst)
                f.write("file '%s'\n" % gap)
            notes.append("第 %d 句：现状(1) → 去房间(2) → 温柔(3)" % ln)
        f.write("file '%s'\n" % long_gap)

    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", lst,
         "-c:a", "libmp3lame", "-b:a", "256k", a.out])

    src_txt = [l.rstrip("\n") for l in open(os.path.join(ROOT, "02_tts_icao.txt"),
                                            encoding="utf-8") if l.strip()]
    open(a.out.replace(".mp3", ".txt"), "w", encoding="utf-8").write(
        "Whisper 距离感 AB 对比（同一句连放三遍，每遍间隔 0.8 秒，句间 2 秒）\n"
        "① 现状：成品链路 = 回声(32/57ms) + 10.5k 低通 + 强展宽  → 房间里、约几米远\n"
        "② 去房间：去掉回声、高频放到 14k、展宽减到 0.6        → 近距离朗读\n"
        "③ 温柔：削中高频硬度 + 深压缩抹平动态 + 整体降 2dB → 悄悄话，不喊\n\n"
        + "\n".join(notes) + "\n\n"
        + "\n".join("第 %d 句：%s" % (ln, src_txt[ln - 1]) for ln in lines) + "\n")
    print(a.out)
    print("\n".join(notes))


if __name__ == "__main__":
    main()
