# -*- coding: utf-8 -*-
"""从 ElevenLabs 公共音色库搜索童声 / 少女声候选，并加入账号。"""
import argparse
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
UA = {"User-Agent": "Mozilla/5.0"}

QUERIES = ["young girl", "little girl", "girly young", "teen girl", "cute girl voice",
           "child voice", "sweet young female whisper", "anime girl", "young anime",
           "soft young female ASMR", "kid voice girl"]


def get(url, key):
    req = urllib.request.Request(url, headers={"xi-api-key": key, **UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def post(url, key, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"xi-api-key": key, "Content-Type": "application/json", **UA},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def mode_search(a):
    seen = {}
    for q in QUERIES:
        url = ("https://api.elevenlabs.io/v1/shared-voices?search=%s"
               "&language=en&gender=female&page_size=25" % urllib.parse.quote(q))
        try:
            r = get(url, a.key)
        except Exception as e:
            print("  [%s] 失败 %s" % (q, e))
            continue
        for v in r.get("voices", []):
            vid = v["voice_id"]
            if vid in seen:
                continue
            seen[vid] = v
        time.sleep(0.4)

    cands = []
    for v in seen.values():
        age = (v.get("age") or "").lower()
        if v.get("gender") != "female":
            continue
        if age not in ("young",):
            continue
        if not v.get("free_users_allowed", True):
            continue
        u = v.get("usage_character_count_1y", 0)
        name = v.get("name", "")
        if u < 20000:          # 太冷门的不敢用，怕是噪音模型
            continue
        cands.append(v)

    cands.sort(key=lambda v: -v.get("usage_character_count_1y", 0))
    print("候选 %d 个（female + young + 使用量 >2万）\n" % len(cands))
    for i, v in enumerate(cands[:30], 1):
        print("%2d  %-42s %-14s desc=%-22s 1y=%-10d cloned=%d" % (
            i, v["name"][:42], (v.get("descriptive") or "-")[:14],
            (v.get("descriptive") or "-")[:22],
            v.get("usage_character_count_1y", 0), v.get("cloned_by_count", 0)))
    json.dump(cands[:30], open(os.path.join(CACHE, "lib_candidates.json"), "w",
                               encoding="utf-8"), ensure_ascii=False, indent=1)


def post_add(key, pub, vid, name):
    # 路径式端点：POST /v1/voices/add/{public_user_id}/{voice_id}?new_name=
    # 必须显式带上 Content-Length，否则网关返回 411
    safe = "".join(ch for ch in name if ch.isalnum() or ch in " -_")[:40].strip()
    url = "https://api.elevenlabs.io/v1/voices/add/%s/%s" % (pub, vid)
    req = urllib.request.Request(url, data=json.dumps({"new_name": safe}).encode("utf-8"),
                                 headers={"xi-api-key": key, "Content-Type": "application/json",
                                          **UA}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def mode_add(a):
    cands = json.load(open(os.path.join(CACHE, "lib_candidates.json"), encoding="utf-8"))
    picks = [int(x) - 1 for x in a.pick.split(",")]
    added = []
    for i in picks:
        v = cands[i]
        try:
            r = post_add(a.key, v["public_owner_id"], v["voice_id"], v["name"])
            new_id = r.get("voice_id")
            print("已加入 %-40s -> %s" % (v["name"][:40], new_id))
            added.append({"name": v["name"], "id": new_id,
                          "desc": v.get("description", "")[:120]})
        except Exception as e:
            print("失败 %s: %s" % (v["name"], e))
    json.dump(added, open(os.path.join(CACHE, "voice_lib.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["search", "add"])
    ap.add_argument("--key", required=True)
    ap.add_argument("--pick", default="")
    a = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    {"search": mode_search, "add": mode_add}[a.mode](a)


if __name__ == "__main__":
    main()
