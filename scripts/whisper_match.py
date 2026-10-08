# -*- coding: utf-8 -*-
"""
找"贴耳气声"音色：同一句话用多种表演指令 / 多种 voice 各读一遍，
每段再给出「原声」和「近讲处理后」两版，串成一个文件供试听挑选。

用法
  python whisper_match.py list                 # 列出账号可用音色（id / 名字 / 标签）
  python whisper_match.py gen                  # 生成对比样音

Key：环境变量 ELEVENLABS_API_KEY 或 --key 传入。
"""
import os
import re
import sys
import json
import argparse
import subprocess
import urllib.request

ROOT = r"E:\Program Files\WorkBuddyProjects\icao900-asmr"
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
MODEL_ID = "eleven_v3"
OUT_FMT = "mp3_44100_192"

# 试音句子（覆盖高度 + 航路点 + QNH）
LINE_NO = 4

VOICE_SETTINGS = {
    "stability": 0.55,        # 比清晰版(0.68)低一点，气声细节更多
    "similarity_boost": 0.72,
    "style": 0.18,
    "speed": 1.0,
    "use_speaker_boost": True,
}

# ⚠️ 重要：EXAVITQu4vr4xnSDxMaL 在本账号里其实是 **Sarah**，不是 Bella；
# Bella 是下面那个 hpp4...。之前两版成品用的都是 Sarah。
SARAH = "EXAVITQu4vr4xnSDxMaL"    # 美式女声，成熟安抚 —— 现有两版成品的音色
BELLA = "hpp4J3VqNfWAUOO0d1Us"    # 美式女声，明亮温暖（真·Bella）
LILY = "pFZP5JQG7iQjIQuC4Bku"     # 英音女声，丝绒质感 Velvety Actress
ALICE = "Xb7hH8MSUJpSbSDYk0k2"    # 英音女声，清晰叙事
JESSICA = "cgSgspJ2msm6clMCkdW9"  # 美式年轻 cute
LAURA = "FGY2WhTYpPnrIDTdsKH5"    # 美式年轻
RIVER = "SAz9YHcvj6GT2YYXdXww"    # 中性偏柔 calm
GEORGE = "JBFqnCBsd6RMkjVDRZzb"   # 英音男声，温暖叙事（睡前男声备选）

ASMR = ("[ASMR whisper, mouth inches from the microphone, extremely breathy, "
        "incredibly intimate bedtime voice] ")
# 用户原话"原来的音频感觉都是在耳边喊出来的"——所以方向不是更近更大，而是
# 气声更多、力度更弱、几乎不用声带的那种悄悄话。
TENDER = ("[gentle tender whisper, soft and delicate as if not to wake a sleeping "
          "child, calm soothing bedtime voice, speaking very quietly and slowly] ")

# (表演指令, voice_id, 说明)
# eleven_v3 的方括号里可以写自然语言表演指令，不局限于 [whispers] 这种固定标签，
# 所以可以直接描述"怎么说"。
VARIANTS = [
    ("[whispers] ", SARAH, "基准：现有耳语版 Sarah"),
    ("[soft-spoken] ", SARAH, "Sarah + soft-spoken"),
    (TENDER,       SARAH,  "Sarah 温柔轻声 ★"),
    (ASMR,         SARAH,  "Sarah + 贴麦 ASMR 描述"),
    (TENDER,       LILY,   "Lily 温柔轻声（英音丝绒）★"),
    (ASMR,         LILY,   "Lily 贴麦 ASMR（英音丝绒）"),
    (TENDER,       BELLA,  "Bella 温柔轻声（真·Bella）★"),
    (TENDER,       ALICE,  "Alice 温柔轻声（英音清晰）"),
    (TENDER,       RIVER,  "River 温柔轻声（中性柔和）"),
    (TENDER,       GEORGE, "George 温柔轻声（英音男声）"),
]

# 「温柔贴耳」后处理链。注意和"播客式近讲"是两回事：
#   近讲式 = 猛抬低频 + 强齿音控制 → 厚、壮、有存在感，听着像"凑近了喊"
#   温柔式 = 削中高频硬度 + 深压缩抹平动态 + 整体降 2 dB → 弱、软、没有攻击性
# 另外一律不加任何混响/回声（成品链的 aecho 正是"像在房间那头"的主因）。
NEAR_CHAIN = (
    "aresample=48000,"
    "highpass=f=55,"                            # 切掉轰隆，不要浑厚感
    "equalizer=f=2200:t=q:w=1.2:g=-2.5,"        # 削中高频硬度（"喊"的主要来源）
    "equalizer=f=6500:t=q:w=2.0:g=-3.0,"        # 齿音柔和
    "equalizer=f=11000:t=q:w=1.0:g=-2.0,"       # 顶端去锐
    "lowshelf=f=160:g=1.5:t=q:w=0.7,"           # 只留一点点温度
    "acompressor=threshold=-30dB:ratio=4:attack=25:release=400:makeup=3,"
    "loudnorm=I=-20:TP=-2.5:LRA=8"              # 整体比成品低 2 dB，动态更平
)


def req(url, key, body=None, accept="application/json"):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data)
    r.add_header("accept", accept)
    r.add_header("xi-api-key", key)
    if data:
        r.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(r, timeout=180)


def tts(text, key, voice, out):
    url = "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=%s" % (voice, OUT_FMT)
    body = {"text": text, "model_id": MODEL_ID, "voice_settings": VOICE_SETTINGS}
    with req(url, key, body, "audio/mpeg") as fp:
        open(out, "wb").write(fp.read())


def run(args_list):
    p = subprocess.run(args_list, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr.decode("utf-8", "ignore"))
        p.check_returncode()


def silence(path, sec):
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=44100:cl=mono", "-t", str(sec),
         "-c:a", "libmp3lame", "-b:a", "192k", path])


def list_voices(key):
    with req("https://api.elevenlabs.io/v1/voices", key) as fp:
        v = json.load(fp)
    rows = []
    for it in v.get("voices", []):
        lab = it.get("labels") or {}
        rows.append((it["voice_id"], it["name"], lab.get("accent", "?"),
                     lab.get("gender", "?"), ",".join(sorted(lab.values())[:6])))
    rows.sort(key=lambda r: (r[3], r[1]))
    for r in rows:
        print("%-26s %-14s [%s/%s] %s" % r)
    print("\n共 %d 个音色" % len(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["list", "gen"])
    ap.add_argument("--key", default=None)
    ap.add_argument("--line", type=int, default=LINE_NO)
    ap.add_argument("--variants", default="all",
                    help="用逗号分隔的序号，如 1,3,5；默认全部")
    ap.add_argument("--near-only", action="store_true",
                    help="只出近讲处理后版本，文件短一半")
    a = ap.parse_args()

    key = a.key or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("缺少 API Key：设置环境变量 ELEVENLABS_API_KEY 或用 --key 传入")

    if a.mode == "list":
        list_voices(key)
        return

    os.makedirs(AUDIO, exist_ok=True)
    src = [l.rstrip("\n") for l in open(os.path.join(ROOT, "02_tts_icao.txt"),
                                        encoding="utf-8") if l.strip()]
    text = src[a.line - 1]

    picks = VARIANTS
    if a.variants != "all":
        want = [int(x) for x in re.split(r"[,\s]+", a.variants) if x]
        picks = [VARIANTS[i - 1] for i in want]

    gap = os.path.join(CACHE, "wm_gap.mp3")
    silence(gap, 0.9)
    long_gap = os.path.join(CACHE, "wm_gap_long.mp3")
    silence(long_gap, 1.8)

    lst = os.path.join(CACHE, "wm_list.txt")
    notes = []
    with open(lst, "w", encoding="utf-8") as f:
        for n, (tag, voice, note) in enumerate(picks, 1):
            raw = os.path.join(CACHE, "wm_%d_raw.mp3" % n)
            try:
                tts(tag + text, key, voice, raw)
            except Exception as e:
                print("[SKIP] %d %s：%s" % (n, note, e))
                continue
            f.write("file '%s'\n" % long_gap)
            f.write("file '%s'  # %d. %s（原声）\n" % (raw, n, note))
            notes.append("%2d. %-28s voice=%s  原声(先) / 近讲(后)" % (n, note, voice))
            if not a.near_only:
                near = os.path.join(CACHE, "wm_%d_near.mp3" % n)
                run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                     "-i", raw, "-af", NEAR_CHAIN,
                     "-ar", "48000", "-ac", "2", "-c:a", "libmp3lame",
                     "-b:a", "256k", near])
                f.write("file '%s'\nfile '%s'\n" % (gap, near))
        f.write("file '%s'\n" % long_gap)

    out = os.path.join(AUDIO, "whisper_match.mp3")
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", lst,
         "-c:a", "libmp3lame", "-b:a", "256k", out])

    open(os.path.join(AUDIO, "whisper_match.txt"), "w", encoding="utf-8").write(
        "贴耳气声音色对比\n================\n"
        "每个变体先播「原声」，停 0.9 秒后播「温柔处理后」版本，再停 1.8 秒进下一个。\n"
        "温柔处理 = 削中高频硬度(-2.5dB@2.2k) / 齿音 -3dB / 深压缩抹平动态 / 整体 -20 LUFS / 无混响。\n\n"
        + "\n".join(notes) + "\n\n试音文本：\n" + text + "\n")

    print(out)
    print("\n".join(notes))


if __name__ == "__main__":
    main()
