# -*- coding: utf-8 -*-
"""
找「气声」而不是「轻声」。

   轻声 = 音量小、弱、温柔      → 压缩 + 削中高频（之前那条路，用户否决）
   气声 = 几乎不用声带，靠气流摩擦出声 → 砍低频谐波 + 抬 5~9kHz 气流噪声（这才对）

同一句先给三种 TTS 指令，每种再挂四档后处理挨着播：
   原声 / 温柔版(旧方向，作反面参照) / 气声版 / 气声加强版
最后附一段：现役 Sarah 干声 + 气声处理（零额度，看老素材能不能救回来）。

用法
  python whisper_breath.py gen
  python whisper_breath.py gen --line 5
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
DRY = os.path.join(CACHE, "clips_whisper")     # 现役 Sarah 耳语干声
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
MODEL_ID = "eleven_v3"
OUT_FMT = "mp3_44100_192"
LINE_NO = 4

JESSICA = "cgSgspJ2msm6clMCkdW9"   # 萌妹向
SARAH = "EXAVITQu4vr4xnSDxMaL"     # 现役成品音色

SETTINGS = {
    "stability": 0.35,
    "similarity_boost": 0.60,      # 再放低一点，让表演指令压过原音色特征
    "style": 0.35,
    "speed": 1.0,
    "use_speaker_boost": True,
}

# 三档 TTS 指令：从"普通耳语"一路推到"几乎不用声带"
PLAIN = "[whispers] "
BREATH = ("[ASMR whisper spoken almost entirely on breath, pure airy voiceless tone "
          "with very little vocal cord vibration, breath clearly audible, soft and close] ")
UNVOICED = ("[unvoiced whispering, almost no voicing at all, only gentle turbulent breath "
            "shaping the words, extremely breathy ASMR, no vocal cord tone] ")

# ---- 后处理四档 ----
# ① 温柔（旧方向）：削中高频 + 深压缩 → 结果是"小声朗读"，不是气声
TENDER_CHAIN = (
    "aresample=48000,highpass=f=55,"
    "equalizer=f=2200:t=q:w=1.2:g=-2.5,"
    "equalizer=f=6500:t=q:w=2.0:g=-3.0,"
    "equalizer=f=11000:t=q:w=1.0:g=-2.0,"
    "lowshelf=f=160:g=1.5:t=q:w=0.7,"
    "acompressor=threshold=-30dB:ratio=4:attack=25:release=400:makeup=3,"
    "loudnorm=I=-20:TP=-2.5:LRA=8"
)

# ② 气声（正解）：声带谐波集中在低频，砍掉它；气流噪声在 5~9k，抬起来
BREATH_CHAIN = (
    "aresample=48000,"
    "highpass=f=130,"                            # 切掉声带的低频谐波
    "lowshelf=f=250:g=-6:t=q:w=0.7,"             # 再去一层"肉感/胸腔"
    "equalizer=f=1200:t=q:w=1.0:g=-2.0,"         # 去喉音、鼻音
    "equalizer=f=5500:t=q:w=1.4:g=4.0,"          # ★ 气流摩擦主体
    "equalizer=f=8500:t=q:w=1.6:g=3.0,"          # ★ 气声高频
    "highshelf=f=12000:g=2.0:t=q:w=0.7,"         # 顶端空气感
    "acompressor=threshold=-28dB:ratio=2.5:attack=20:release=350:makeup=2,"
    "loudnorm=I=-19:TP=-2:LRA=9"
)

# ③ 气声加强：再狠一点，接近"只有气"
BREATH_STRONG_CHAIN = (
    "aresample=48000,"
    "highpass=f=170,"
    "lowshelf=f=300:g=-9:t=q:w=0.7,"
    "equalizer=f=1200:t=q:w=1.0:g=-3.0,"
    "equalizer=f=5500:t=q:w=1.4:g=6.0,"
    "equalizer=f=8500:t=q:w=1.6:g=5.0,"
    "highshelf=f=12000:g=3.0:t=q:w=0.7,"
    "acompressor=threshold=-28dB:ratio=2.2:attack=20:release=350:makeup=2,"
    "loudnorm=I=-19:TP=-2:LRA=9"
)

PROCESS = [("原声", None), ("温柔(旧)", TENDER_CHAIN),
           ("气声", BREATH_CHAIN), ("气声加强", BREATH_STRONG_CHAIN)]

VOICE_TAGS = [(JESSICA, "Jessica", [PLAIN, BREATH, UNVOICED])]


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
    body = {"text": text, "model_id": MODEL_ID, "voice_settings": SETTINGS}
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


def render(src, chain, dst):
    if chain is None:
        # 原声也要统一到 48k 立体声，避免 concat 时参数不一致
        run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
             "-af", "aresample=48000,loudnorm=I=-19:TP=-2:LRA=9",
             "-ac", "2", "-ar", "48000", "-c:a", "libmp3lame", "-b:a", "256k", dst])
    else:
        run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
             "-af", chain, "-ac", "2", "-ar", "48000",
             "-c:a", "libmp3lame", "-b:a", "256k", dst])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["gen"])
    ap.add_argument("--key", default=None)
    ap.add_argument("--line", type=int, default=LINE_NO)
    ap.add_argument("--out", default=os.path.join(AUDIO, "whisper_breath_AB.mp3"))
    a = ap.parse_args()

    key = a.key or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("缺少 API Key")

    src = [l.rstrip("\n") for l in open(os.path.join(ROOT, "02_tts_icao.txt"),
                                        encoding="utf-8") if l.strip()]
    text = src[a.line - 1]

    gap = os.path.join(CACHE, "wb_gap.mp3")
    silence(gap, 0.7)
    lg = os.path.join(CACHE, "wb_lg.mp3")
    silence(lg, 2.2)

    lst = os.path.join(CACHE, "wb_list.txt")
    notes = []
    with open(lst, "w", encoding="utf-8") as f:
        for vid, vname, tags in VOICE_TAGS:
            for ti, tag in enumerate(tags, 1):
                raw = os.path.join(CACHE, "wb_%s_%d_raw.mp3" % (vname, ti))
                tts(tag + text, key, vid, raw)
                label = "%s / 指令%d" % (vname, ti)
                for pi, (pname, chain) in enumerate(PROCESS, 1):
                    dst = os.path.join(CACHE, "wb_%s_%d_%d.mp3" % (vname, ti, pi))
                    render(raw, chain, dst)
                    f.write("file '%s'\nfile '%s'\n" % (lg if pi == 1 else gap, dst))
                notes.append("%s  ①原声 ②温柔(旧) ③气声 ④气声加强" % label)

        # 附：现役 Sarah 干声（旧的 [whispers] 素材）+ 新的气声处理，零额度
        dry = os.path.join(DRY, "%04d.mp3" % a.line)
        if os.path.exists(dry):
            for pi, (pname, chain) in enumerate(PROCESS, 1):
                dst = os.path.join(CACHE, "wb_sarah_%d.mp3" % pi)
                render(dry, chain, dst)
                f.write("file '%s'\nfile '%s'\n" % (lg if pi == 1 else gap, dst))
            notes.append("Sarah 现役干声  ①原声 ②温柔(旧) ③气声 ④气声加强")
        f.write("file '%s'\n" % lg)

    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", lst,
         "-c:a", "libmp3lame", "-b:a", "256k", a.out])

    open(a.out.replace(".mp3", ".txt"), "w", encoding="utf-8").write(
        "「气声」而不是「轻声」——对比样音\n"
        "================================\n"
        "每组四段，间隔 0.7 秒：①原声 ②温柔处理(旧方向) ③气声处理(新) ④气声加强\n"
        "旧方向错在：把 2.2k/6.5k/11k 压掉了，那几个频段恰恰是气流噪声所在。\n"
        "气声处理 = 切 130Hz 以下(声带谐波) + 低频 -6dB + 5.5k +4dB + 8.5k +3dB。\n\n"
        "指令1 = [whispers]\n"
        "指令2 = 几乎全靠气流、极少声带振动\n"
        "指令3 = 纯 unvoiced，只有气流塑形\n\n"
        + "\n".join(notes) + "\n\n试音第 %d 句：\n%s\n" % (a.line, text))
    print(a.out)
    print("\n".join(notes))


if __name__ == "__main__":
    main()
