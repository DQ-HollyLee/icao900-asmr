# -*- coding: utf-8 -*-
"""数字 8 的拼写探针：同一句话用 7 种拼法各读一遍，挑出稳定读作 [eɪt]（押 eight）的写法。

背景：ICAO 规定 8 读 AIT（押 eight），但 eleven_v3 遇到 "ait" 会时快时慢地念成
"A-I-T" 三个字母。这里把候选拼法放进真实句子里让她读，挑一个 100% 读 [eɪt] 的。
"""
import os
import json
import subprocess
import urllib.request

ROOT = r"E:\Program Files\WorkBuddyProjects\icao900-asmr"
CACHE = os.path.join(ROOT, ".cache")
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")
VOICE = "EXAVITQu4vr4xnSDxMaL"        # Bella（用户已确认的 1 号配置）

# 候选拼法
SPELLINGS = ["eight", "ate", "ait", "ayt", "eit", "aite", "ei8ht"]
# 三种真实语境各读一遍，覆盖不同邻接音（检测是不是在个别位置才念错）
SENTS = [
    "Passing Flight Level one %s zero.",
    "Maintain Mach decimal %s zero.",
    "Contact Control on one one %s decimal niner.",
    "Descend to %s tousand feet.",
]


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
    gap = os.path.join(CACHE, "gap_10.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.7",
                    "-c:a", "libmp3lame", "-b:a", "192k", gap], check=True)
    lst = os.path.join(CACHE, "ei_list.txt")
    lines = []
    with open(lst, "w", encoding="utf-8") as f:
        # 外层：拼法（7 种）  内层：4 个句子
        for n, sp in enumerate(SPELLINGS):
            for m, s in enumerate(SENTS):
                p = os.path.join(CACHE, "ei_%d_%d.mp3" % (n, m))
                tts(s % sp, key, p)
                f.write("file '%s'\nfile '%s'\n" % (p, gap))
                lines.append("对照组 %d —— 拼法 \"%s\"： %s" % (n + 1, sp, s % sp))
    out = os.path.join(AUDIO, "eight_probe.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", lst,
                    "-c:a", "libmp3lame", "-b:a", "192k", out], check=True)
    open(os.path.join(AUDIO, "eight_probe.txt"), "w", encoding="utf-8").write(
        "数字 8 拼写对比（目标：稳定读作 [eɪt]，押 eight，不能念成 A-I-T）\n"
        "每组 7 个拼法 × 每拼法 4 句，按 1~7 顺序播放。\n\n"
        + "\n".join(lines) + "\n")
    print(out)


if __name__ == "__main__":
    main()
