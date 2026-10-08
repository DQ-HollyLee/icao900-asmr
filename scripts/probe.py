# -*- coding: utf-8 -*-
"""
航路点 / 程序代号 读音 A-B 对照探针
同一个代号读两遍：第一遍「原始写法」，第二遍「规范化写法」，用来判断 TTS 到底读成什么。
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
VOICE = "EXAVITQu4vr4xnSDxMaL"          # Bella
SETTINGS = {"stability": 0.68, "similarity_boost": 0.78,
            "style": 0.12, "speed": 0.95, "use_speaker_boost": True}

# (原始写法, 规范化写法, 中文说明)
PAIRS = [
    ("WXJ.", "Whiskey X-ray Juliett.", "三字母航路点"),
    ("DAPRO.", "Dapro.", "五字母命名航路点"),
    ("BK-02 RNAV Departure.", "Bravo Kilo zero two R Nav Departure.", "离场程序代号"),
    ("KODAP-01 Departure.", "Kodap zero one Departure.", "五字母+编号"),
    ("ILS approach.", "I L S approach.", "ILS 缩略语"),
    ("VOR.", "V O R.", "VOR 缩略语"),
    ("APU.", "A P U.", "APU 缩略语"),
    ("Hold at ST VOR.", "Hold at Sierra Tango V O R.", "两字母+导航台"),
    ("SID.", "Cancel SID.", "SID 是否读成单词"),
    ("NOTAM.", "FOD.", "NOTAM / FOD 是否读成单词"),
    ("Descend to 3000 feet.", "Descend to tree tou-sand feet.", "高度：整千"),
    ("Descend to 10500 feet.", "Descend to one zero tou-sand fife hundred feet.", "高度：万位+整百"),
    ("tree thousand feet.", "tree tou-sand feet.", "thousand vs tou-sand 发音对比"),
    ("Passing 2500 feet.", "Passing two tou-sand fife hundred feet.", "高度：千+整百"),
    ("RVR 350 meters.", "R V R tree hundred fife zero meters.", "RVR：百位"),
    ("Cancel SID.", "Cancel S I D.", "SID 逐字母，不读成 sid"),
    ("Flight Level 340.", "Flight Level tree four zero.", "数字 4 读 four"),
]


def tts(text, key, out):
    url = ("https://api.elevenlabs.io/v1/text-to-speech/%s"
           "?output_format=mp3_44100_192" % VOICE)
    body = {"text": text, "model_id": MODEL_ID, "voice_settings": SETTINGS}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("xi-api-key", key)
    req.add_header("Content-Type", "application/json")
    req.add_header("accept", "audio/mpeg")
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    open(out, "wb").write(data)
    return len(data)


def main():
    key = os.environ.get("ELEVENLABS_API_KEY") or input("xi-api-key: ").strip()
    os.makedirs(AUDIO, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    gap = os.path.join(CACHE, "gap_06.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.7",
                    "-c:a", "libmp3lame", "-b:a", "192k", gap], check=True)
    lst = os.path.join(CACHE, "probe_list.txt")
    notes = []
    with open(lst, "w", encoding="utf-8") as f:
        for n, (raw, norm, note) in enumerate(PAIRS):
            p1 = os.path.join(CACHE, "probe_%02da.mp3" % n)
            p2 = os.path.join(CACHE, "probe_%02db.mp3" % n)
            tts(raw, key, p1)
            tts(norm, key, p2)
            f.write("file '%s'\nfile '%s'\n" % (p1, gap))
            f.write("file '%s'\nfile '%s'\n" % (p2, gap))
            notes.append("%2d. %-24s | 原: %-28s | 改: %s" % (n + 1, note, raw, norm))
    out = os.path.join(AUDIO, "probe_waypoints.mp3")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", lst,
                    "-c:a", "libmp3lame", "-b:a", "192k", out], check=True)
    txt = os.path.join(ROOT, "audio", "probe_waypoints.txt")
    open(txt, "w", encoding="utf-8").write(
        "航路点读音 A-B 对照（每组：先原写法，后规范化写法）\n" + "\n".join(notes) + "\n")
    print(out)
    print("\n".join(notes))


if __name__ == "__main__":
    main()
