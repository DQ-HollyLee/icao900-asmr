# -*- coding: utf-8 -*-
"""
找「清纯萌妹 + 气声撒娇」音色：同一句话用几种年轻音色 × 几种俏皮/挑逗指令各读一遍，
每段先原声、后上"温柔处理"，串成一个文件试听。

用法
  python whisper_cute.py gen                      # 全部变体
  python whisper_cute.py gen --variants 1,2,5     # 只跑指定几个
  python whisper_cute.py gen --line 5             # 换一句试音

Key：环境变量 ELEVENLABS_API_KEY 或 --key 传入。
"""
import os
import sys
import json
import argparse
import subprocess
import urllib.request

ROOT = r"E:\Program Files\WorkBuddyProjects\icao900-asmr"
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
DRY = os.path.join(CACHE, "clips_whisper")      # 已有 whisper 干声（仅基准对照用）
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
MODEL_ID = "eleven_v3"
OUT_FMT = "mp3_44100_192"

LINE_NO = 4

# stability 低 = 情绪起伏大、更像在"演"；萌妹撒娇需要这个。
# style 高 = 更有表演感。similarity 别太高，否则会死守原音色特征压过指令。
BASE_SETTINGS = {
    "stability": 0.35,
    "similarity_boost": 0.65,
    "style": 0.35,
    "speed": 1.0,
    "use_speaker_boost": True,
}
CALM_SETTINGS = dict(BASE_SETTINGS, stability=0.55, style=0.15)

JESSICA = "cgSgspJ2msm6clMCkdW9"   # 美式 young / cute / conversational ← 最贴"萌妹"
LAURA = "FGY2WhTYpPnrIDTdsKH5"     # 美式 young / sassy / 社交媒体腔
BELLA = "hpp4J3VqNfWAUOO0d1Us"     # 美式 bright warm（真·Bella）
RIVER = "SAz9YHcvj6GT2YYXdXww"     # 中性 calm / conversational
SARAH = "EXAVITQu4vr4xnSDxMaL"     # 现有成品音色（成熟安抚）→ 对照组

# 俏皮撒娇：sweet + playful + teasing + coquettish，口气轻，不能写成叫喊
COQUET = ("[soft breathy whisper, cute and coquettish, playfully teasing and pampering, "
          "like a spoiled young girl talking right by your ear, sweet and affectionate] ")
CUTE = ("[whispers in a young cute girly voice, sweet and playful, gently teasing, "
        "very close to the ear, soft breathy and affectionate] ")
SWEET = ("[gentle sweet whisper in a bright young voice, delicate mouth sounds, "
         "cozy bedtime tone, soft quiet and tender] ")

# pitch：ElevenLabs 不提供音高参数，用 rubberband 只变调不变速。
# 升 1.5~2 个半音 = 明显更年少；超过 3 会开始发尖。
VARIANTS = [
    dict(note="Jessica 撒娇挑逗", voice=JESSICA, tag=COQUET, pitch=0),
    dict(note="Jessica 撒娇 + 升2半音", voice=JESSICA, tag=COQUET, pitch=2.0),
    dict(note="Jessica 俏皮气声", voice=JESSICA, tag=CUTE, pitch=0),
    dict(note="Jessica 清纯温柔", voice=JESSICA, tag=SWEET, pitch=0),
    dict(note="Jessica 平稳版(stab.55)", voice=JESSICA, tag=COQUET, pitch=0,
         settings=CALM_SETTINGS),
    dict(note="Laura 撒娇挑逗", voice=LAURA, tag=COQUET, pitch=0),
    dict(note="Bella 撒娇挑逗", voice=BELLA, tag=COQUET, pitch=0),
    dict(note="River 撒娇挑逗（中性）", voice=RIVER, tag=COQUET, pitch=0),
    dict(note="Sarah 撒娇（现役音色对照）", voice=SARAH, tag=COQUET, pitch=0),
]

# 「温柔」后处理：削中高频硬度（喊的主因）+ 深压缩 + 整体压低 + 完全不加混响
TENDER_CHAIN = (
    "aresample=48000,"
    "highpass=f=55,"
    "equalizer=f=2200:t=q:w=1.2:g=-2.5,"
    "equalizer=f=6500:t=q:w=2.0:g=-3.0,"
    "equalizer=f=11000:t=q:w=1.0:g=-2.0,"
    "lowshelf=f=160:g=1.5:t=q:w=0.7,"
    "acompressor=threshold=-30dB:ratio=4:attack=25:release=400:makeup=3,"
    "loudnorm=I=-20:TP=-2.5:LRA=8"
)


def req(url, key, body=None, accept="application/json"):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data)
    r.add_header("accept", accept)
    r.add_header("xi-api-key", key)
    if data:
        r.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(r, timeout=180)


def tts(text, key, voice, out, settings):
    url = "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=%s" % (voice, OUT_FMT)
    body = {"text": text, "model_id": MODEL_ID, "voice_settings": settings}
    with req(url, key, body, "audio/mpeg") as fp:
        open(out, "wb").write(fp.read())


def run(args):
    p = subprocess.run(args, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr.decode("utf-8", "ignore"))
        p.check_returncode()


def silence(path, sec):
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=48000:cl=stereo", "-t", str(sec),
         "-c:a", "libmp3lame", "-b:a", "256k", path])


# ------------------------------------------------------------------ 1 vs 7 纯对比
def mode_ab(key, lines, out):
    """只放两个候选音色的原声 / 温柔版，同一句挨着播，便于直接抓音色差异"""
    voices = [(JESSICA, "①Jessica"), (BELLA, "⑦Bella")]
    gap = os.path.join(CACHE, "wc_gap.mp3")
    silence(gap, 0.7)
    lg = os.path.join(CACHE, "wc_lg.mp3")
    silence(lg, 1.6)
    lg2 = os.path.join(CACHE, "wc_lg2.mp3")
    silence(lg2, 2.6)

    src = [l.rstrip("\n") for l in open(os.path.join(ROOT, "02_tts_icao.txt"),
                                        encoding="utf-8") if l.strip()]
    lst = os.path.join(CACHE, "wc_ab_list.txt")
    notes = ["每段内部：①Jessica 原声 → ⑦Bella 原声 → ①温柔版 → ⑦温柔版"]
    with open(lst, "w", encoding="utf-8") as f:
        f.write("file '%s'\n" % lg2)
        for ln in lines:
            text = src[ln - 1]
            raws, nears = [], []
            for vi, (vid, vname) in enumerate(voices, 1):
                raw = os.path.join(CACHE, "ab_%d_%d_raw.mp3" % (ln, vi))
                tts(COQUET + text, key, vid, raw, BASE_SETTINGS)
                near = os.path.join(CACHE, "ab_%d_%d_near.mp3" % (ln, vi))
                run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                     "-i", raw, "-af", TENDER_CHAIN,
                     "-ac", "2", "-ar", "48000",
                     "-c:a", "libmp3lame", "-b:a", "256k", near])
                raws.append(raw)
                nears.append(near)
            for p in raws:
                f.write("file '%s'\nfile '%s'\n" % (p, gap))
            f.write("file '%s'\n" % lg)
            for p in nears:
                f.write("file '%s'\nfile '%s'\n" % (p, gap))
            f.write("file '%s'\n" % lg2)
            notes.append("第 %d 句：%s" % (ln, text))
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", lst,
         "-c:a", "libmp3lame", "-b:a", "256k", out])
    open(out.replace(".mp3", ".txt"), "w", encoding="utf-8").write(
        "①Jessica vs ⑦Bella 纯对比（同一句挨着播）\n"
        "=====================================\n"
        + "\n".join(notes) + "\n\n"
        "指令（两者相同）：\n" + COQUET + "\n"
        "温柔处理：削中高频硬度 / 齿音 -3dB / 深压缩 / -20 LUFS / 无混响\n")


def mode_pitch(out):
    """验证升调：rubberband 默认会把共振峰一起抬（花栗鼠），formant=1 才是自然升调"""
    base = os.path.join(CACHE, "wc_1_raw.mp3")     # 第 1 号变体的原声（Jessica 句4）
    if not os.path.exists(base):
        sys.exit("缺少 %s，先跑一次 gen" % base)
    variants = [
        ("原调", None),
        ("+2 半音 保持共振峰 formant=1", 2.0),
        ("+3 半音 保持共振峰 formant=1", 3.0),
    ]
    gap = os.path.join(CACHE, "wc_gap.mp3")
    silence(gap, 0.8)
    lg = os.path.join(CACHE, "wc_lg2.mp3")
    silence(lg, 2.2)
    lst = os.path.join(CACHE, "wc_pitch_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for name, semi in variants:
            p = os.path.join(CACHE, "pit_%s.mp3" % (name.replace(" ", "").replace(
                "+", "p").replace("半音", "s").replace(".", "_") or "orig"))
            if semi is None:
                chain = TENDER_CHAIN
            else:
                chain = ("rubberband=pitch=%g:formant=1," % semi) + TENDER_CHAIN
            run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                 "-i", base, "-af", chain, "-ac", "2", "-ar", "48000",
                 "-c:a", "libmp3lame", "-b:a", "256k", p])
            f.write("file '%s'\nfile '%s'\nfile '%s'\n" % (lg, p, gap))
        f.write("file '%s'\n" % lg)
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", lst,
         "-c:a", "libmp3lame", "-b:a", "256k", out])
    open(out.replace(".mp3", ".txt"), "w", encoding="utf-8").write(
        "升调算法修正验证（素材 = Jessica 第 4 句原声）\n"
        "=======================================\n"
        "之前变+2就成\"恶搞声\"的原因：rubberband 默认 formant=0，会把共振峰一起抬，\n"
        "基频变了但声道尺寸没变 → 典型花栗鼠/卡通化。加 formant=1 只动基频、保住共振峰。\n\n"
        + "\n".join("· " + v[0] for v in variants) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["gen", "ab", "pitch"])
    ap.add_argument("--key", default=None)
    ap.add_argument("--line", type=int, default=LINE_NO)
    ap.add_argument("--variants", default="all")
    ap.add_argument("--lines", default="4,5,87", help="ab 模式用的句子，逗号分隔")
    ap.add_argument("--out", default=os.path.join(AUDIO, "whisper_cute_match.mp3"))
    a = ap.parse_args()

    key = a.key or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("缺少 API Key：设置 ELEVENLABS_API_KEY 或用 --key 传入")

    src = [l.rstrip("\n") for l in open(os.path.join(ROOT, "02_tts_icao.txt"),
                                        encoding="utf-8") if l.strip()]
    if a.mode == "ab":
        mode_ab(key, [int(x) for x in a.lines.split(",") if x.strip()], a.out)
        print(a.out)
        return
    if a.mode == "pitch":
        mode_pitch(os.path.join(AUDIO, "whisper_pitch_test.mp3"))
        print(os.path.join(AUDIO, "whisper_pitch_test.mp3"))
        return

    text = src[a.line - 1]

    picks = VARIANTS
    if a.variants != "all":
        want = [int(x) for x in a.variants.replace("，", ",").split(",") if x.strip()]
        picks = [VARIANTS[i - 1] for i in want]

    gap = os.path.join(CACHE, "wc_gap.mp3")
    silence(gap, 0.8)
    long_gap = os.path.join(CACHE, "wc_gap_long.mp3")
    silence(long_gap, 1.8)

    lst = os.path.join(CACHE, "wc_list.txt")
    notes = []
    with open(lst, "w", encoding="utf-8") as f:
        f.write("file '%s'\n" % long_gap)
        for n, v in enumerate(picks, 1):
            raw = os.path.join(CACHE, "wc_%d_raw.mp3" % n)
            tts(v["tag"] + text, key, v["voice"], raw,
                v.get("settings") or BASE_SETTINGS)

            chain = TENDER_CHAIN
            if v.get("pitch"):
                # rubberband 变调不变速，正数 = 升调（更年轻）
                chain = "rubberband=pitch=%g," % v["pitch"] + chain
            near = os.path.join(CACHE, "wc_%d_near.mp3" % n)
            run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                 "-i", raw, "-af", chain,
                 "-ac", "2", "-ar", "48000",
                 "-c:a", "libmp3lame", "-b:a", "256k", near])

            f.write("file '%s'\n" % raw)
            f.write("file '%s'\n" % gap)
            f.write("file '%s'\n" % near)
            f.write("file '%s'\n" % long_gap)
            pitch = ("  pitch %+g 半音" % v["pitch"]) if v.get("pitch") else ""
            notes.append("%2d. %-26s%s%s" % (n, v["note"], "" if v.get("settings") is BASE_SETTINGS else "", pitch))
        f.write("file '%s'\n" % long_gap)

    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", lst,
         "-c:a", "libmp3lame", "-b:a", "256k", a.out])

    open(a.out.replace(".mp3", ".txt"), "w", encoding="utf-8").write(
        "萌妹气声对比（清纯 / 俏皮 / 撒娇）\n"
        "================================\n"
        "每个变体：先「原声」，隔 0.8 秒再播「温柔处理后」，再隔 1.8 秒进下一个。\n"
        "温柔处理 = 削中高频硬度(-2.5dB@2.2k) / 齿音 -3dB / 深压缩 / -20 LUFS / 无混响。\n"
        "pitch 为正 = 用 rubberband 升调（变年轻），不变语速。\n\n"
        + "\n".join(notes) + "\n\n试音第 %d 句：\n%s\n" % (a.line, text))
    print(a.out)
    print("\n".join(notes))


if __name__ == "__main__":
    main()
