# -*- coding: utf-8 -*-
"""单独实测 v3 扣减比例（与前次 v4+v3 混合测试分离）。"""
import json
import os
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
# ⚠️ 安全：不要在这类脚本里硬编码 API Key（历史版本曾泄露一枚，已轮换）。
#    请改为环境变量：set ELEVENLABS_API_KEY=sk_xxx
K = os.environ.get("ELEVENLABS_API_KEY", "")
EMMA = "nDJIICjR9zfJExIFeSCN"
T = "Maintaining Flight Level niner zero over Whiskey X-ray Juliett. " * 4  # 248 字符


def used():
    req = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription",
                                 headers={"xi-api-key": K, **UA})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())["character_count"]


def tts(model, out):
    body = {"text": T, "model_id": model,
            "voice_settings": {"stability": .4, "similarity_boost": .7, "style": .2, "speed": 1.0}}
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128" % EMMA,
        data=json.dumps(body).encode(), method="POST",
        headers={"xi-api-key": K, "Content-Type": "application/json", **UA})
    urllib.request.urlopen(req, timeout=120).read()
    open(out, "wb").write(b"ok")


c0 = used()
print("基准已用 %d（等 30 s 让上次结算落地）" % c0)
time.sleep(30)
c0 = used()
print("结算后基准 %d" % c0)

tts("eleven_v3", ".cache/fee_v3b.ok")
time.sleep(45)
c1 = used()
print("v3 生成 248 字符 -> 已用 %d，增量 %d（比例 %.2f）" % (c1, c1 - c0, (c1 - c0) / 248))
time.sleep(45)
c2 = used()
print("再等 45 s 确认无漂移：已用 %d，净增量 %d（比例 %.2f）" % (c2, c2 - c0, (c2 - c0) / 248))
