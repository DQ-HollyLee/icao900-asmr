# -*- coding: utf-8 -*-
"""给 asmr_chain 的每一段滤镜测耗时，找出真正该优化的地方。

用法： profile_stage.py [片段秒数]
从 .cache/full_cat_*.mp3 中间切一段，逐级叠加滤镜，-f null - 输出到空设备。
"""
import os
import sys
import time
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tts_generate as tg

SEG = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
SS = 3000.0                       # 从成品中段开始取样，避开开头
FF = tg.FFMPEG
SRC = r"E:\Program Files\WorkBuddyProjects\icao900-asmr\.cache\full_cat_whisper_v13x12.mp3"
NULL = "-f", "null", "-"


def run(label, af, extra_tail=None, threads=None):
    """返回耗时（秒）。af=None 表示这一段只解码不做滤镜。"""
    cmd = [FF, "-hide_banner", "-v", "error", "-ss", str(SS), "-t", str(SEG), "-i", SRC]
    if af:
        cmd += ["-filter:a", af]
    cmd += list(NULL if extra_tail is None else extra_tail)
    env = os.environ.copy()
    if threads:
        env["FFREPORT"] = "file=0"
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    dt = time.time() - t0
    if r.returncode != 0:
        print("  !! %s 失败：%s" % (label, r.stderr.strip()[:300]))
    return dt


# 逐级叠加，每级只看增量
STAGES = [
    ("0  mp3 解码（基准，无滤镜）", None),
    ("1  + aresample→48k", "aresample=48000"),
    ("2  + atempo 1.15", "aresample=48000,atempo=%g" % tg.TEMPO),
    ("3  + highpass/lowpass/bass",
     "aresample=48000,atempo=%g,highpass=f=55,lowpass=f=10500,bass=g=1.8:f=110:w=0.7"
     % tg.TEMPO),
    ("4  + aecho（房间感）",
     "aresample=48000,atempo=%g,highpass=f=55,lowpass=f=10500,bass=g=1.8:f=110:w=0.7,"
     "aecho=0.86:0.9:32|57:0.20|0.11" % tg.TEMPO),
]

BRANCH = (
    "aresample=48000,atempo=%g,highpass=f=55,lowpass=f=10500,bass=g=1.8:f=110:w=0.7,"
    "aecho=0.86:0.9:32|57:0.20|0.11,"
    "asplit=2[l][r];"
    "[l]adelay=11,lowpass=f=8800,volume=%g,"
    "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[L];"
    "[r]highpass=f=95,lowpass=f=11000,volume=0.965,"
    "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[R];"
    "[L][R]amerge=inputs=2[st];"
    "[st]channelsplit=channel_layout=stereo[o1][o2];[o1][o2]amerge=inputs=2"
    % (tg.TEMPO, tg.L_BRANCH_GAIN)
)
STAGES.append(("5  + 左右分路/adelay/差异化EQ", BRANCH))

# 控制信号部分要第二个输入，单独处理
PRE = BRANCH.replace("[st]channelsplit=channel_layout=stereo[o1][o2];[o1][o2]amerge=inputs=2",
                     "")
CTL_MULT = (
    PRE + "[st]extrastereo=m=1.6,channelsplit=channel_layout=stereo[cl][cr];"
    "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000,"
    "channelsplit=channel_layout=stereo[cL][cR];"
    "[cl][cL]amultiply[pl];[cr][cR]amultiply[pr];[pl][pr]amerge=inputs=2"
)
STAGES.append(("6  + extrastereo + 控制曲线相乘", CTL_MULT))
STAGES.append(("7  + loudnorm（最终样式）",
               CTL_MULT + ",loudnorm=I=-18:TP=-2:LRA=11"))

# 控制信号文件（只需一小段，但 build_pan_track 要按总时长生成，这里按片段长度生成）
ctl_path = os.path.join(tg.CACHE, "_prof_ctl.raw")
tg.build_pan_track(SEG, ctl_path)
print("片段 %.0fs（从 %.0fs 开始），音频源 %s\n" % (SEG, SS, os.path.basename(SRC)))

prev = None
rows = []
for label, af in STAGES:
    if af and "[1:a]" in af:
        cmd = [FF, "-hide_banner", "-v", "error", "-ss", str(SS), "-t", str(SEG), "-i", SRC,
               "-f", "f32le", "-ar", str(tg.CTL_RATE), "-ac", "2", "-i", ctl_path,
               "-filter_complex", af, "-an", "-f", "null", "-"]
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        dt = time.time() - t0
        if r.returncode != 0:
            print("  !! %s 失败：%s" % (label, r.stderr.strip()[:300]))
    else:
        dt = run(label, af)
    inc = None if prev is None else dt - prev
    prev = dt
    rows.append((label, dt, inc))
    full = 6360.0                                  # 成品总秒数，用来折算全片
    print("%-34s %7.2fs  本段增量 %s   折算全片 %6.1f 分钟"
          % (label, dt, ("%6.2fs" % inc) if inc is not None else "   —   ",
             dt * full / SEG / 60))

# 最后单独测 mp3 编码本身的成本
out = os.path.join(tg.CACHE, "_prof_enc.mp3")
cmd = [FF, "-hide_banner", "-v", "error", "-ss", str(SS), "-t", str(SEG), "-i", SRC,
       "-filter:a", "aresample=48000,atempo=%g" % tg.TEMPO,
       "-ac", "2", "-ar", "48000", "-c:a", "libmp3lame", "-b:a", "256k", out]
t0 = time.time()
r = subprocess.run(cmd, capture_output=True, text=True)
dt = time.time() - t0
if r.returncode != 0:
    print("  !! mp3 编码失败：%s" % r.stderr.strip()[:300])
print("%-34s %7.2fs  本段增量 %6.2fs   折算全片 %6.1f 分钟"
      % ("8  libmp3lame 256k 编码（换 filter 版）", dt, dt, dt * 6360 / SEG / 60))

os.remove(out)
os.remove(ctl_path)
