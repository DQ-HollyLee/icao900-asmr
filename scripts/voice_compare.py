# -*- coding: utf-8 -*-
"""
音色 / 语速对比样音：同一段文本用几种配置各读一遍，串成一个文件供挑选。
eleven_v3 支持音频标签（audio tags），用 [soft-spoken] / [whispers] 控制气声程度。
"""
import os
import json
import subprocess
import urllib.request

ROOT = r"E:\Program Files\WorkBuddyProjects\icao900-asmr"
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
MODEL_ID = "eleven_v3"
SPEED = 0.95                      # 比原 0.85 稍快

# 对比文本：覆盖高度、航路点、程序代号、频率、应答机、跑道号
LINES = [4, 5, 18, 87]

# (标签, voice_id, 说明)
VARIANTS = [
    ("", "EXAVITQu4vr4xnSDxMaL", "Bella 原音（无标签）"),
    ("[soft-spoken] ", "EXAVITQu4vr4xnSDxMaL", "Bella 轻柔软语"),
    ("[whispers] ", "EXAVITQu4vr4xnSDxMaL", "Bella 耳边气声"),
    ("[whispers] ", "pFZP5JQG7iQjIQuC4Bku", "Lily 耳边气声（英音）"),
    ("[soft-spoken] ", "Xb7hH8MSUJpSbSDYk0k2", "Alice 轻柔软语（英音）"),
]


def tts(text, key, voice, out, speed=SPEED):
    url = ("https://api.elevenlabs.io/v1/text-to-speech/%s"
           "?output_format=mp3_44100_192" % voice)
    body = {
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": {"stability": 0.68, "similarity_boost": 0.78,
                           "style": 0.12, "speed": speed,
                           "use_speaker_boost": True},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("xi-api-key", key)
    req.add_header("Content-Type", "application/json")
    req.add_header("accept", "audio/mpeg")
    with urllib.request.urlopen(req, timeout=120) as r:
        open(out, "wb").write(r.read())


def main():
    key = os.environ.get("ELEVENLABS_API_KEY") or input("xi-api-key: ").strip()
    os.makedirs(AUDIO, exist_ok=True)
    src = [l.rstrip("\n") for l in open(os.path.join(ROOT, "02_tts_icao.txt"),
                                        encoding="utf-8") if l.strip()]
    text = " ".join(src[i - 1] for i in LINES)

    gap = os.path.join(CACHE, "gap_10.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "1.0",
                    "-c:a", "libmp3lame", "-b:a", "192k", gap], check=True)

    lst = os.path.join(CACHE, "vc_list.txt")
    notes = []
    with open(lst, "w", encoding="utf-8") as f:
        for n, (tag, voice, note) in enumerate(VARIANTS):
            p = os.path.join(CACHE, "vc_%d.mp3" % n)
            tts(tag + text, key, voice, p)
            f.write("file '%s'\nfile '%s'\n" % (p, gap))
            notes.append("%d. %s   (voice=%s, speed=%.2f)" % (n + 1, note, voice, SPEED))
    out = os.path.join(AUDIO, "voice_compare.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", lst,
                    "-c:a", "libmp3lame", "-b:a", "192k", out], check=True)
    open(os.path.join(AUDIO, "voice_compare.txt"), "w", encoding="utf-8").write(
        "音色对比（同一段文本，每遍之间 1 秒间隔）\n语速 %.2f\n\n" % SPEED
        + "\n".join(notes) + "\n\n文本：\n" + text + "\n")
    print(out)
    print("\n".join(notes))


if __name__ == "__main__":
    main()
