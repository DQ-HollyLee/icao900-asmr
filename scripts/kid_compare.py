# -*- coding: utf-8 -*-
"""童声路线：Voice Design 造音色 + 与 Jessica / Bella 原樣对比。

关键约束（用户明确要求）：
  * 文本只用一句 "Maintaining Flight Level niner zero over Whiskey X-ray Juliett."
  * 不做任何升调、不做气声化后处理 —— 只做 loudnorm 统一响度以便公平对比。
"""
import argparse
import base64
import json
import os
import re
import subprocess
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")

TEXT = "Maintaining Flight Level niner zero over Whiskey X-ray Juliett."
SAMPLE_TEXT = (
    "Maintaining Flight Level tree one zero. Descending to Flight Level two niner zero. "
    "Reaching Flight Level one niner zero. Maintaining Flight Level niner zero over "
    "Whiskey X-ray Juliett."
)

JESSICA = "cgSgspJ2msm6clMCkdW9"
BELLA = "hpp4J3VqNfWAUOO0d1Us"
SARAH = "EXAVITQu4vr4xnSDxMaL"
LAURA = "FGY2WhTYpPnrIDTdsKH5"
ALICE = "Xb7hH8MSUJpSbSDYk0k2"
OUT_FMT = "mp3_44100_128"
MODEL = "eleven_v3"

UA = {"User-Agent": "Mozilla/5.0"}


def http(method, url, key, body=None, timeout=180):
    data = None
    hdr = {"xi-api-key": key}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=dict(hdr, **UA), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("  HTTP %s %s" % (e.code, e.read().decode("utf-8", "ignore")[:400]))
        raise


def tts(text, key, voice, out, stability=0.35, similarity=0.65, style=0.35, speed=1.0):
    """eleven_v3 优先；社区克隆音色若不支持 v3 则退回 multilingual_v2 并去掉方括号标签。"""
    url = "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=%s" % (voice, OUT_FMT)
    body = {
        "text": text,
        "model_id": MODEL,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity,
            "style": style,
            "speed": speed,
        },
    }
    for attempt in range(2):
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"xi-api-key": key, "Content-Type": "application/json", **UA}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                with open(out, "wb") as f:
                    f.write(r.read())
            if attempt == 1:
                print("      (已退回 multilingual_v2)")
            return out
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore")[:200]
            if attempt == 0 and ("voice" in msg.lower() or "model" in msg.lower()):
                body["model_id"] = "eleven_multilingual_v2"
                body["text"] = re.sub(r"\[[^\]]*\]", "", text).strip()
                continue
            raise


def loudnorm(src, dst):
    """只做响度归一，不做 EQ / 变调 / 压缩 / 混响。"""
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                    "-af", "aresample=48000,loudnorm=I=-18:TP=-2:LRA=11",
                    "-c:a", "libmp3lame", "-b:a", "256k", dst], check=True)


def silence(sec, dst):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=stereo", "-t", str(sec),
                    "-c:a", "libmp3lame", "-b:a", "256k", dst], check=True)


def concat(files,gap_sec, out):
    gap = os.path.join(CACHE, "kid_gap.mp3")
    silence(gap_sec, gap)
    lst = os.path.join(CACHE, "kid_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in files:
            f.write("file '%s'\nfile '%s'\n" % (gap.replace("\\", "/"), p.replace("\\", "/")))
        f.write("file '%s'\n" % gap.replace("\\", "/"))
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                    "-safe", "0", "-i", lst, "-c:a", "libmp3lame", "-b:a", "256k", out],
                   check=True)


def dur(p):
    out = subprocess.run([os.path.join(CACHE, "ffprobe.exe"), "-v", "error",
                          "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", p],
                         capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


# ---------------------------------------------------------------- Voice Design
DESIGNS = [
    ("D1", "A sweet little girl around 7 years old, cute high-pitched child voice, innocent, "
           "gentle and bright, reading softly out loud"),
    ("D2", "A young girl about 10 years old, clear youthful child voice, light and sweet, "
           "like a kid reading a textbook aloud in class"),
    ("D3", "A teenage girl about 14, soft youthful girlish voice, playful and cute, "
           "slightly breathy, gentle bedroom ASMR tone"),
]


def mode_design(a):
    key = a.key
    got = []
    for tag, desc in DESIGNS:
        print("设计 %s：%s" % (tag, desc[:40]))
        r = http("POST", "https://api.elevenlabs.io/v1/text-to-voice/create-previews", key,
                 {"text": SAMPLE_TEXT, "voice_description": desc, "loudness": -1, "quality": 0.7})
        prevs = r.get("previews") or []
        for i, p in enumerate(prevs[:2], 1):
            vid = p.get("generated_voice_id")
            b64 = p.get("audio_base_64") or p.get("audio_base64")
            if not vid or not b64:
                continue
            raw = os.path.join(CACHE, "vd_%s_%d_design.mp3" % (tag, i))
            with open(raw, "wb") as f:
                f.write(base64.b64decode(b64))
            # 持久化为账号音色，便于后续全量生成
            name = "ASMR-%s-%d" % (tag, i)
            try:
                sv = http("POST", "https://api.elevenlabs.io/v1/text-to-voice/create-voice-from-preview",
                          key, {"voice_name": name, "voice_description": desc,
                                "generated_voice_id": vid})
                real = sv.get("voice_id")
                print("   预览%d -> 音色 %s (%s)" % (i, real, name))
            except Exception as e:
                real = vid
                print("   预览%d 持久化失败，用临时 ID" % i)
            got.append({"tag": "%s-%d" % (tag, i), "desc": desc, "id": real})
    json.dump(got, open(os.path.join(CACHE, "voice_design.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n共 %d 个候选音色，已写入 .cache/voice_design.json" % len(got))


# ---------------------------------------------------------------- 对比生成
COQUETTISH = ("[cute and coquettish, playfully teasing and pampering, intimate close "
              "to the microphone] ")
WHISPER = "[whispers] "

# 用户指定的基准（重新生成，排除模型随机性造成的偶然差异）
BASE = [
    ("1 Jessica 撒娇挑逗", JESSICA, COQUETTISH, dict(stability=.35, similarity=.65, style=.35)),
    ("7 Bella 撒娇挑逗",   BELLA,   COQUETTISH, dict(stability=.35, similarity=.65, style=.35)),
]

# 公共库里的年轻 / 童声音色：清读 + 部分加耳语标签
LIB = [
    ("Lulu Lolipop 高音甜美", "ocZQ262SsZb9RIxcQBOj", True),
    ("Candy 年轻甜美",        "Nggzl2QAXh3OijoXD116", True),
    ("Emmaline 英音小女孩",   "nDJIICjR9zfJExIFeSCN", True),
    ("Isabel 轻声少女",       "RwZADRjd8b3vxKTsTtLP", True),
    ("Mini 活泼可爱女孩",     "hO2yZ8lxM3axUxL8OeKX", False),
    ("Fena 娇俏女孩角色",     "BlgEcC0TfWpBak7FmvHW", False),
    ("Claire 古灵精怪女孩",   "B4wUDSZmHFnxqY60nxXm", False),
    ("Faith 温柔甜美",        "bIQlQ61Q7WgbyZAL7IWj", False),
]


def build_variants(key):
    vs = list(BASE)
    for name, vid, extra in LIB:
        vs.append((name + " 清读", vid, "",
                   dict(stability=.4, similarity=.7, style=.2)))
    for name, vid, extra in LIB:
        if extra:
            vs.append((name + " 耳语", vid, WHISPER,
                       dict(stability=.35, similarity=.65, style=.3)))
    return vs


def mode_gen(a):
    key = a.key
    vs = build_variants(key)
    if a.variants != "all":
        keep = [int(x) for x in a.variants.split(",")]
        vs = [vs[i - 1] for i in keep if 1 <= i <= len(vs)]

    outs, lines = [], []
    for i, (name, vid, tag, st) in enumerate(vs, 1):
        raw = os.path.join(CACHE, "kid_%02d_raw.mp3" % i)
        tts(tag + TEXT, key, vid, raw, **st)
        norm = os.path.join(CACHE, "kid_%02d.mp3" % i)
        loudnorm(raw, norm)
        outs.append(norm)
        lines.append("%2d  %-24s id=%s  %.2fs" % (i, name, vid[:8], dur(norm)))
        print("OK %2d %s" % (i, name))

    out = os.path.join(AUDIO, a.out)
    concat(outs, a.gap, out)
    print("\n%.1f 秒 -> %s" % (dur(out), out))
    print("顺序：\n" + "\n".join(lines))

    txt = os.path.join(AUDIO, os.path.splitext(a.out)[0] + ".txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("童声路线对比\n============\n")
        f.write("文本：%s\n" % TEXT)
        f.write("全程无升调、无气声化 EQ；每段只做 loudnorm 统一到 -18 LUFS，便于公平对比。\n")
        f.write("段间静音 %.1f 秒。\n\n" % a.gap)
        for l in lines:
            f.write(l + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["design", "gen"])
    ap.add_argument("--key", required=True)
    ap.add_argument("--variants", default="all")
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--out", default="kid_compare.mp3")
    a = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(AUDIO, exist_ok=True)
    {"design": mode_design, "gen": mode_gen}[a.mode](a)


if __name__ == "__main__":
    main()
