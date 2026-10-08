# -*- coding: utf-8 -*-
"""
把「悄悄话的气声」和「烟嗓」分开：之前的错误是抬错频段。

   烟嗓 = 5.5k/8.5k 窄峰猛推 + 低频掏空 → 出来只有摩擦噪声的"沙"，没有"人"
   悄悄话气声 = 宽带柔和抬气流(从 5k 起 shelf) + 压掉 3.5k 的"糙"
              + 保留少量低频撑住声体 + 顶端回收避免沙沙刺耳

另外解决"还是太老"：两种手段对比 —— rubberband 保共振峰升调 vs TTS 直接描述年龄。

用法
  python whisper_soft.py gen
  python whisper_soft.py gen --line 5
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
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
MODEL_ID = "eleven_v3"
OUT_FMT = "mp3_44100_192"
LINE_NO = 4

JESSICA = "cgSgspJ2msm6clMCkdW9"

SETTINGS = {
    "stability": 0.35,
    "similarity_boost": 0.60,
    "style": 0.35,
    "speed": 1.0,
    "use_speaker_boost": True,
}

# 上一轮用户认定"正在靠近"的那版指令（几乎全靠气流、极少声带振动）
BREATH = ("[ASMR whisper spoken almost entirely on breath, pure airy voiceless tone "
          "with very little vocal cord vibration, breath clearly audible, soft and close] ")
# 在 TTS 侧直接要求年轻（不动音频，靠模型自己变）
YOUNG = ("[in a youthful young woman's voice, bright girlish tone, soft and sweet] "
         + BREATH)

# ---------- 后处理档 ----------
BASE_TAIL = ("acompressor=threshold=-28dB:ratio=2.2:attack=20:release=350:makeup=2,"
             "loudnorm=I=-19:TP=-2:LRA=9")

# 柔絮气声 v1（保守）：保留声体、宽带抬气、压 3.5k 的糙
SOFT1 = (
    "highpass=f=70,"
    "lowshelf=f=250:g=-2.5:t=q:w=0.7,"
    "equalizer=f=950:t=q:w=1.0:g=-1.5,"
    "equalizer=f=3500:t=q:w=1.5:g=-2.0,"     # 去"沙/糙"的关键
    "highshelf=f=5500:g=3.0:t=q:w=0.5,"      # 宽带柔和抬气流
    "equalizer=f=11000:t=q:w=1.2:g=-2.0,"    # 顶端回收，避免沙沙刺耳
    + BASE_TAIL)

# 柔絮气声 v2（气更多一点，但仍保声体）
SOFT2 = (
    "highpass=f=80,"
    "lowshelf=f=250:g=-3.5:t=q:w=0.7,"
    "equalizer=f=950:t=q:w=1.0:g=-2.0,"
    "equalizer=f=3500:t=q:w=1.5:g=-3.0,"
    "highshelf=f=5000:g=4.5:t=q:w=0.5,"
    "equalizer=f=11000:t=q:w=1.2:g=-1.5,"
    + BASE_TAIL)

# 上一轮那个"烟嗓"版本，留作反面参照
SMOKY = (
    "highpass=f=170,lowshelf=f=300:g=-9:t=q:w=0.7,"
    "equalizer=f=1200:t=q:w=1.0:g=-3.0,"
    "equalizer=f=5500:t=q:w=1.4:g=6.0,equalizer=f=8500:t=q:w=1.6:g=5.0,"
    "highshelf=f=12000:g=3.0:t=q:w=0.7," + BASE_TAIL)


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


def render(src, out, chain, pitch=0.0):
    af = "aresample=48000," + (("rubberband=pitch=%g:formant=1," % pitch) if pitch else "")
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
         "-af", af + chain, "-ac", "2", "-ar", "48000",
         "-c:a", "libmp3lame", "-b:a", "256k", out])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["gen"])
    ap.add_argument("--key", default=None)
    ap.add_argument("--line", type=int, default=LINE_NO)
    ap.add_argument("--out", default=os.path.join(AUDIO, "whisper_soft_AB.mp3"))
    a = ap.parse_args()
    key = a.key or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("缺少 API Key")

    src = [l.rstrip("\n") for l in open(os.path.join(ROOT, "02_tts_icao.txt"),
                                        encoding="utf-8") if l.strip()]
    text = src[a.line - 1]

    base = os.path.join(CACHE, "ws_base.mp3")
    tts(BREATH + text, key, JESSICA, base)
    young = os.path.join(CACHE, "ws_young.mp3")
    tts(YOUNG + text, key, JESSICA, young)

    gap = os.path.join(CACHE, "ws_gap.mp3")
    silence(gap, 0.7)
    lg = os.path.join(CACHE, "ws_lg.mp3")
    silence(lg, 2.4)

    lst = os.path.join(CACHE, "ws_list.txt")
    notes = []
    with open(lst, "w", encoding="utf-8") as f:

        def emit(raw, out_name, chain, pitch, note):
            p = os.path.join(CACHE, "ws_%s.mp3" % out_name)
            render(raw, p, chain, pitch)
            f.write("file '%s'\nfile '%s'\n" % (lg, p))
            f.write("file '%s'\n" % gap)
            notes.append(note)

        # ---- A 段：怎么变年轻 ----（统一用柔絮气声 v1）
        emit(base, "a1", SOFT1, 0.0, "A1 原调（Jessica 指令2 + 柔絮气声 v1）")
        emit(base, "a2", SOFT1, 2.0, "A2 +2 半音（保共振峰）")
        emit(base, "a3", SOFT1, 3.0, "A3 +3 半音（保共振峰）")
        emit(young, "a4", SOFT1, 0.0, "A4 TTS 侧要求年轻（不变调）")
        emit(young, "a5", SOFT1, 2.0, "A5 TTS 侧要求年轻 + 升 2 半音")

        # ---- B 段：气的质感 ----（不变调，纯比处理）
        emit(base, "b1", SOFT1, 0.0, "B1 柔絮气声 v1（保守）")
        emit(base, "b2", SOFT2, 0.0, "B2 柔絮气声 v2（气更多）")
        emit(base, "b3", SMOKY, 0.0, "B3 ← 上一版，已变成烟嗓的反面参照")

    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", lst,
         "-c:a", "libmp3lame", "-b:a", "256k", a.out])

    open(a.out.replace(".mp3", ".txt"), "w", encoding="utf-8").write(
        "悄悄话气声 · 精调一轮（改掉烟嗓 + 变年轻）\n"
        "========================================\n"
        "每段间隔约 0.7 秒。\n\n"
        "为什么要改：上一轮 5.5k/8.5k 用窄峰猛推 + 低频掏空 9dB，\n"
        "结果是只剩摩擦噪声的\"沙\"= 烟嗓。真正的悄悄话气声是**宽带**且**保留声体**的：\n"
        "  · highshelf 从 5k 起宽带抬（不是窄峰）\n"
        "  · 把 3.5k 附近的\"糙\"压掉 2~3 dB\n"
        "  · 低频只收 2.5~3.5 dB，不再掏空\n"
        "  · 11k 以上收回 2 dB，免得沙沙刺耳\n\n"
        + "\n".join(notes) + "\n\n试音第 %d 句：\n%s\n" % (a.line, text))
    print(a.out)
    print("\n".join(notes))


if __name__ == "__main__":
    main()
