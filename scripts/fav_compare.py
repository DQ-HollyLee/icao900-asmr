# -*- coding: utf-8 -*-
"""用户挑中的三个社区音色 + Emmaline，用 eleven_v3 / eleven_v4 对比。
文本固定一句；无升调、无气声后处理，只做 loudnorm。
"""
import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
TEXT = "Maintaining Flight Level niner zero over Whiskey X-ray Juliett."
UA = {"User-Agent": "Mozilla/5.0"}

VOICES = [
    ("Luna 深夜甜心",  "Luna-LateNight"),      # id 查库填
    ("Natasha ASMR",   "Natasha-ASMR"),
    ("Lovejoy 轻语",   "Lovejoy-ASMR"),
    ("Emmaline 英音",  "Emmaline"),
]


def http_json(method, url, key, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "xi-api-key": key, "Content-Type": "application/json", **UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def resolve(key):
    """在账号音色列表里按备注名找 voice_id。"""
    acc = http_json("GET", "https://api.elevenlabs.io/v1/voices", key)
    m = {}
    for v in acc.get("voices", []):
        m[v["name"]] = v["voice_id"]
    return m


def tts(text, key, voice, out, model, stability=.35, similarity=.65, style=.3):
    url = "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128" % voice
    body = {"text": text, "model_id": model,
            "voice_settings": {"stability": stability, "similarity_boost": similarity,
                               "style": style, "speed": 1.0}}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json", **UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            with open(out, "wb") as f:
                f.write(r.read())
        return True
    except urllib.error.HTTPError as e:
        print("      失败: %s %s" % (e.code, e.read().decode("utf-8", "ignore")[:150]))
        return False


def loudnorm(src, dst):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                    "-af", "aresample=48000,loudnorm=I=-18:TP=-2:LRA=11",
                    "-c:a", "libmp3lame", "-b:a", "256k", dst], check=True)


def dur(p):
    o = subprocess.run([os.path.join(CACHE, "ffprobe.exe"), "-v", "error",
                        "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", p],
                       capture_output=True, text=True)
    return float(o.stdout.strip() or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    a = ap.parse_args()
    key = a.key

    names = resolve(key)
    print("账号音色 %d 个" % len(names))

    picks = [
        ("Luna 深夜甜心",  [n for n in names if n.startswith("Luna") and "Sweetheart" in n]),
        ("Natasha ASMR",   [n for n in names if n.startswith("Natasha")]),
        ("Lovejoy 轻语",   [n for n in names if "Lovejoy" in n]),
        ("Emmaline 英音",  [n for n in names if n.startswith("Emmaline")]),
    ]

    outs, lines = [], []
    i = 0
    for label, cand in picks:
        if not cand:
            print("!! 找不到 %s（未添加成功？）" % label)
            continue
        vid = names[cand[0]]
        for tag, model in (("v3", "eleven_v3"), ("v4", "eleven_v4")):
            i += 1
            raw = os.path.join(CACHE, "fav_%02d_raw.mp3" % i)
            ok = tts("[whispers] " + TEXT, key, vid, raw, model)
            if not ok:
                i -= 1
                continue
            norm = os.path.join(CACHE, "fav_%02d.mp3" % i)
            loudnorm(raw, norm)
            outs.append(norm)
            lines.append((label + " " + tag, vid))
            print("OK %2d %s %s" % (i, label, tag))

    gap = os.path.join(CACHE, "fav_gap.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=stereo", "-t", "1.0",
                    "-c:a", "libmp3lame", "-b:a", "256k", gap], check=True)
    lst = os.path.join(CACHE, "fav_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in outs:
            f.write("file '%s'\nfile '%s'\n" % (gap.replace("\\", "/"), p.replace("\\", "/")))
        f.write("file '%s'\n" % gap.replace("\\", "/"))
    out = os.path.join(AUDIO, "fav_compare.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                    "-safe", "0", "-i", lst, "-c:a", "libmp3lame", "-b:a", "256k", out], check=True)
    print("\n%.1f 秒 -> %s" % (dur(out), out))
    for i, ((label, vid), p) in enumerate(zip(lines, outs), 1):
        print("%2d  %-22s id=%s  %.2fs" % (i, label, vid[:10], dur(p)))

    with open(os.path.join(AUDIO, "fav_compare.txt"), "w", encoding="utf-8") as f:
        f.write("用户挑中的音色 + V3/V4 对比\n========================\n")
        f.write("文本：%s\n全部 [whispers] 标签；无升调、无气声 EQ，仅 loudnorm。段间 1 秒。\n\n" % TEXT)
        for i, (label, vid) in enumerate(lines, 1):
            f.write("%2d  %-22s id=%s\n" % (i, label, vid))


if __name__ == "__main__":
    main()
