# -*- coding: utf-8 -*-
"""THOUSAND 拼写探针：同一个高度句用 5 种拼法各读一遍，挑出最干脆的 [ˈtaʊzənd]。"""
import os
import json
import subprocess
import urllib.request

ROOT = r"E:\Program Files\WorkBuddyProjects\icao900-asmr"
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
VOICE = "EXAVITQu4vr4xnSDxMaL"        # Bella（用户已确认的 1 号配置）

SPELLINGS = ["tousand", "touzand", "tou-sand", "thousand", "towzand"]
SENT = "Descend to tree %s feet, one zero %s fife hundred feet."


def tts(text, key, out):
    url = ("https://api.elevenlabs.io/v1/text-to-speech/%s"
           "?output_format=mp3_44100_192" % VOICE)
    body = {"text": text, "model_id": "eleven_v3",
            "voice_settings": {"stability": 0.68, "similarity_boost": 0.78,
                               "style": 0.12, "speed": 0.95,
                               "use_speaker_boost": True}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("xi-api-key", key)
    req.add_header("Content-Type", "application/json")
    req.add_header("accept", "audio/mpeg")
    with urllib.request.urlopen(req, timeout=120) as r:
        open(out, "wb").write(r.read())


def main():
    key = os.environ.get("ELEVENLABS_API_KEY") or input("xi-api-key: ").strip()
    gap = os.path.join(CACHE, "gap_08.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.8",
                    "-c:a", "libmp3lame", "-b:a", "192k", gap], check=True)
    lst = os.path.join(CACHE, "th_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for n, sp in enumerate(SPELLINGS):
            p = os.path.join(CACHE, "th_%d.mp3" % n)
            tts(SENT % (sp, sp), key, p)
            f.write("file '%s'\nfile '%s'\n" % (p, gap))
    out = os.path.join(AUDIO, "thousand_probe.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", lst,
                    "-c:a", "libmp3lame", "-b:a", "192k", out], check=True)
    open(os.path.join(AUDIO, "thousand_probe.txt"), "w", encoding="utf-8").write(
        "THOUSAND 拼写对比（目标音 [ˈtaʊzənd]，干脆不拖长）\n"
        + "\n".join("%d. %s" % (i + 1, s) for i, s in enumerate(SPELLINGS)) + "\n")
    print(out)


if __name__ == "__main__":
    main()
