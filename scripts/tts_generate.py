# -*- coding: utf-8 -*-
"""
ICAO 900 句 → 逐句 ElevenLabs 合成 → 拼接 → 双声道 ASMR 后处理

用法
  python tts_generate.py voices                 # 列出可用音色
  python tts_generate.py sample                 # 生成 8 句样音（先试听再决定全量）
  python tts_generate.py all                    # 全量 900 句
  python tts_generate.py post                   # 只做拼接 + 后处理（clip 已存在时）
  python tts_generate.py selftest               # 用合成音验证后处理链路

API Key：环境变量 ELEVENLABS_API_KEY，或 --key 传入。
"""
import os
import re
import sys
import json
import time
import math
import shutil
import argparse
import threading
import subprocess
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import numpy as np
except ImportError:                                   # noqa
    np = None

ROOT = r"E:\Program Files\WorkBuddyProjects\icao900-asmr"
CACHE = os.path.join(ROOT, ".cache")
CLIPS = os.path.join(CACHE, "clips")          # 默认（清晰版）；耳语版用 --clips clips_whisper
AUDIO = os.path.join(ROOT, "audio")
FFMPEG = os.path.join(CACHE, "ffmpeg.exe")

TXT = os.path.join(ROOT, "02_tts_icao.txt")
MODEL_ID = "eleven_v4"   # 2026-10-08 起：v4 促销扣 0.28x 额度（至 10-12），且用户选定 Emmaline+v4；v3 按 0.46x

OUTPUT_FORMAT = "mp3_44100_192"

# 合成侧 speed 保持 1.0：实测 ElevenLabs 的 speed 在 eleven_v3 上效果不可靠，
# 语速统一由后处理的 TEMPO（ffmpeg atempo，确定性）控制。
VOICE_SETTINGS = {
    "stability": 0.35,
    "similarity_boost": 0.65,
    "style": 0.30,
    "speed": 1.0,
    "use_speaker_boost": True,
}
# eleven_v3 音频标签："" 原音 / "[soft-spoken] " 轻柔软语 / "[whispers] " 耳边气声
STYLE_TAG = ""
# ⚠️ EXAVITQu4vr4xnSDxMaL 在本账号里的名字是 **Sarah**（不是 Bella），Bella 是 hpp4J3VqNfWAUOO0d1Us。
# 现有两版成品（清晰版 / 耳语版）用的都是这个 Sarah。
# 2026-10-08：用户选定 Emmaline（英音小女孩，公共库）+ eleven_v4 为新全量版本。
DEFAULT_VOICE = "nDJIICjR9zfJExIFeSCN"   # Emmaline - young British girl
GAP_SEC = 2.5                              # 句间静音（成品中的实际值）

# eleven_v3/v4 的音频标签**续航有限**：长句读到后半段会退回正常发声
# （实测：43 词长句用单次 [whispers]，末段谐噪比 HNR 从 -3.7 dB 涨到 +2.9 dB = 变成本音）。
# 解决办法：把长句切成 ≤CHUNK_WORDS 词的小段，**每段各带一次标签**再拼接，
# 实测三句 40+ 词长句的 HNR 漂移从 +6.6 dB 降到 +0.5 dB 左右，全程保持气声。
# maxw：一个标点分句超过这么多词，才在其内部按词数再切（不是"每 8 词必切"！）
# ---- 分块策略（2026-10-08 第三版：语义感知）----
# 迭代史（别改回旧做法）：
#   v1「每 8 词硬切」→ 切点落在词组中间，出现 "X-ray | Juliett"、"tree six | right" 的莫名停顿
#   v2「只在标点处切」→ 修好了带逗号的长句，但**没有标点却超过预算**的句子仍被按词硬切（第 4 句就是受害者）
#   v3（当前）语义感知：先把句子粘成不可拆分的「语义单元」，切点只能落在单元边界；
#      且整句 ≤NO_SPLIT_WORDS 词时**完全不切**（短句标签续航足够，实测 +0.7 dB）。
NO_SPLIT_WORDS = 16    # 整句词数 ≤ 此值时一次合成，绝不切开；实测 14~16 词漂移仍 ≤3.6 dB
CHUNK_WORDS    = 8     # 超过 NOSPLIT 后，单元贪心打包的软预算（词）
CHUNK_HARD     = 16    # 单个语义单元超过这么多词，才允许在单元内部再切（罕见兜底）
CHUNK_GAP      = 0.0   # 拼接间隙（秒）；默认 0，靠交叉淡化过渡
CHUNK_XFADE    = 0.06  # 交叉淡化时长（秒）：比硬拼+静音自然得多，也不会咬掉尾音
TRIM_EDGES     = True  # 拼接前裁掉每块首尾静音（阈值调得很保守，避免吞掉弱辅音尾）

# 后处理变速。改这一个数字就能调整成品语速，**不用重新合成、不消耗额度**。
# 为什么不用 ElevenLabs 的 voice_settings.speed：实测该参数在 eleven_v3 上不可靠，
# 同一句分别按 0.95 / 1.05 合成，时长几乎相同（单次生成本身有 ±10% 抖动，盖过了 ±10% 的语速差）。
# atempo 是确定性变速且保持音高不变，1.15 = 快 15%。
TEMPO = 1.15

# ---- 双声道声场（用户要求：左右差别要大、换边要干脆、再叠一层轻微远近感）----
PAN_PERIOD   = None    # 已废弃：新版改为随机停留，不再用固定周期
# 2026-10-08 用户最终定稿：回到 10:90（±19.1 dB），并配合 PAN_DIP 补偿双耳响度求和。
#   b=0.90 → pos=0.859 → 两耳差 20·log10(9) ≈ 19.1 dB。
PAN_BALANCE  = 0.90    # 极限位置的声道配比 90:10 ≈ ±19.1 dB（曾试过 99:1 ≈ ±39.9 dB，太极端）
PAN_SWAP_SEC = 2.5     # 从一侧完全换到另一侧所需的秒数（用户要求 <3 s；旧值 5 s 偏拖沓）
PAN_HOLD_MIN = 20.0    # 单侧停留时长下限（秒），用户要求 20~30 秒随机
PAN_HOLD_MAX = 30.0    # 单侧停留时长上限（秒）
PAN_SEED     = 20261008  # 随机种子：固定住才能保证每次后处理结果一致（可复现）
CTL_RATE     = 200     # 声像控制信号的采样率（Hz）。曲线变化极慢，200 Hz 绰绰有余，
                       # 一小时只要几十 MB；喂给 ffmpeg 时再线性插值到 48 kHz。
DIST_DEPTH   = 0.10    # 远近带来的最大音量衰减，用户要求不超过 10%
DIST_PERIOD  = 217.0   # （旧版）远近感周期，仅供 dist_expr 备用

# ------------------------------------------------------------------------------
# 换边时的「中心下压」：补偿双耳响度求和（binaural loudness summation）
#
# 现象：同一个声音同时给两只耳朵听（居中），比只给一只耳朵听（完全偏到一侧）
#       来得更响。这是听觉中枢的求和效应，不是物理能量守恒能解释的。
#
# 文献实测（等响匹配法，宽带噪声 / 语音频段）：
#   Zwicker & Zwicker 1991 (JASA 89)           双耳比单耳响 ≈ 1.5 倍，且随 ILD 增大而衰减
#   "Interaural correlation and loudness" 2006  diotic 要匹配 monotic 需 monotic 高 4.6~6.5 dB
#   JASA 2014 (hearing-impaired, PMID 25096108) LDEL ≈ 5.6 dB @500 Hz / 4.2 dB @3-4 kHz
#   Schlittenlacher 2014 (反应时法)             ≈ 5 dB @1 kHz
#
# 但我们的等功率声像法则（L=cos、R=sin，L²+R²=1）已经把「能量」配平了：
#   居中时每耳各自降了 3 dB，所以真正剩下的只是上面那个 4.6~6.5 dB 求和量减去 3 dB，
#   再补回极限位置主导耳本来就有的 -0.05 dB。净剩约 **1.6 ~ 3.5 dB**（中位 2.5 dB）。
#   换算成本参数：1.6 dB→压 17%、2.5 dB→压 25%、3.5 dB→压 33%。
#   用户凭感觉猜的 20% 正好落在这个区间偏保守的一端 —— 有依据，不是瞎猜。
#
# 20*log10(1-PAN_DIP)：0.20 → -1.94 dB ｜ 0.25 → -2.50 dB ｜ 0.33 → -3.48 dB
# ------------------------------------------------------------------------------
PAN_DIP       = 0.20   # 居中时总音量最多下压的比例（线性幅度，不是 dB）
PAN_DIP_SHAPE = 1.0    # 下压曲线的锐度：下压权重 w = (0.5·(1+cos(π·x)))^shape，x=|ILD|/ILDmax
                       #   shape=1 余弦钟形（推荐，两端导数为 0，完全无折角）
                       #   shape>1 更集中在正中间，dip 更"尖"；<1 更铺开近似方波

# 左右两路各自的 EQ 本来就有差别（左婉、右稍亮），导致左路比右路响约 0.36 dB。
# 不校平的话，"总音量"会随声场漂移周期性晃动约 1.3 dB，叠加远近起伏就超过 10% 上限。
# 把左路衰减到与右路齐平即可；值是拿 600 秒真实语音实测出来的，别拍脑袋改。
L_BRANCH_GAIN = 0.9589

# 覆盖各类发音难点：航路点、程序代号、跑道号、频率、QNH、应答机、坐标、高度、RVR、缩略语
SAMPLE_IDX = [4, 18, 44, 51, 80, 87, 96, 206, 219, 334, 340, 403, 419, 445, 602]


# ------------------------------------------------------------------ 基础
def ensure_dirs():
    for d in (CACHE, CLIPS, AUDIO):
        os.makedirs(d, exist_ok=True)


def api_key(args):
    k = args.key or os.environ.get("ELEVENLABS_API_KEY")
    if not k:
        sys.exit("缺少 API Key：请设置环境变量 ELEVENLABS_API_KEY 或用 --key 传入")
    return k


def http_json(url, key=None, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("accept", "application/json")
    if key:
        req.add_header("xi-api-key", key)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


# ------------------------------------------------------------------ 合成
# ------------------------------------------------- 语义单元（不可切分的词组）
# 这些词组一旦被切开，听感就是"莫名其妙的停顿"（用户明确投诉过 X-ray|Juliett、tree six|right）。
# 说明：文本已经过 normalize.py 的 ICAO 发音规范化，所以数字是单词形式（tree/six/tousand）。
DIGIT_WORDS = {
    "zero", "one", "two", "tree", "fower", "four", "fife", "five", "six", "seven",
    "eight", "niner", "nine", "ten", "eleven", "twelve", "tousand", "thousand",
    "hundred", "decimal",
}
# 紧跟数字的单位 / 量词，必须和数字同在一块
NUM_UNITS = {
    "feet", "foot", "metre", "metres", "meter", "meters", "knot", "knots", "mile",
    "miles", "kilometre", "kilometres", "kilometer", "kilometers", "degree",
    "degrees", "level", "hectopascal", "hectopascals", "millibar", "millibars",
    "tonne", "tonnes", "pound", "pounds", "kilogram", "kilograms", "hours",
    "hour", "minutes", "minute", "seconds", "second",
}
# 跑道号后缀：36R → "tree six right"，right 必须跟数字在一起
RUNWAY_SUFFIX = {"left", "right", "center", "centre"}
# 领航词：它们后面紧跟的数字序列属于同一个意群（Runway tree six right / Heading two fife zero）
# 少了这条就会出现 "Runway | tree six right" 这种切开跑道号的错
NUM_HEADS = {
    "runway", "heading", "altitude", "altimeter", "level", "squawk", "qnh", "qfe",
    "frequency", "mach", "speed", "track", "course", "height", "visibility",
    "climb", "descend", "maintain", "expect", "back", "vector", "vectoring",
    "radials", "radial", "field", "ceiling", "minimums", "minima",
}
# ICAO 拼写字母：呼号/航路点/缩写是整串读的，中间不能切
ICAO_LETTERS = {
    "alfa", "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
    "hotel", "india", "juliett", "juliet", "kilo", "lima", "mike", "november",
    "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform", "victor",
    "whiskey", "xray", "x-ray", "yankee", "zulu",
}
# 呼号尾巴：Lima Kilo Oscar **Departure** / **Radar** / **Tower**
CALL_TAIL = {
    "radar", "approach", "tower", "ground", "control", "departure", "arrival",
    "center", "centre", "company", "radio", "helper", "information", "atis",
}
# 固定搭配的前缀词，永远跟后面的单元绑在一起（Flight | Level → Flight Level）
PREFIX_GLUE = {"flight", "holding", "holdingpoint", "descendto"}
# 多次拖.ernet(2026-10-08)：
#   * 句号和逗号后**标签都会衰减**（实测 219 跨句 +9.1 dB、340 逗号后 +7.1 dB），
#     所以两者都要断开——逗号处本来就有自然停顿，断开反而更自然。
#   * 少于 CHUNK_MIN_WORDS 词的碎块并入前一段，避免"every inch"式的细碎拼接。
CHUNK_MIN_WORDS = 3
_SENT_END = (".", "?", "!")
_SOFT_END = (",", ";", ":")
_PUNCT_TAIL = (",", ".", ";", ":", "?", "!")


def _key(w):
    """归一化成小写裸词，用于查表"""
    return w.strip().strip(".,;:?!\"'").lower()


def build_units(words):
    """把一串词粘成不可再切的语义单元列表（list[list[str]]）。

    规则：
      数字串（连续数字词）→ 一个单元，连同后面的单位 / 跑道后缀
      航路点-呼号串（连续拼写字母）→ 一个单元，连同后面的数字与单位呼号尾
      其余单词各自成单元（因此本身就是合法切点）
    """
    units, i, n = [], 0, len(words)
    while i < n:
        k = _key(words[i])
        grp = [words[i]]
        i += 1
        if k in NUM_HEADS and i < n and _key(words[i]) in DIGIT_WORDS:
            # Runway / Heading / Squawk ... + 数字串 (+单位/跑道后缀)
            while i < n and _key(words[i]) in DIGIT_WORDS:
                grp.append(words[i]); i += 1
            if i < n and _key(words[i]) in NUM_UNITS:
                grp.append(words[i]); i += 1
            if i < n and _key(words[i]) in RUNWAY_SUFFIX:
                grp.append(words[i]); i += 1
        elif k in DIGIT_WORDS:
            while i < n and _key(words[i]) in DIGIT_WORDS:
                grp.append(words[i]); i += 1
            if i < n and _key(words[i]) in NUM_UNITS:
                grp.append(words[i]); i += 1
            if i < n and _key(words[i]) in RUNWAY_SUFFIX:
                grp.append(words[i]); i += 1
        elif k in ICAO_LETTERS:
            while i < n and _key(words[i]) in ICAO_LETTERS:
                grp.append(words[i]); i += 1
            if i < n and _key(words[i]) in DIGIT_WORDS:   # 呼号后的航班号数字
                grp.append(words[i]); i += 1
                while i < n and _key(words[i]) in DIGIT_WORDS:
                    grp.append(words[i]); i += 1
            if i < n and _key(words[i]) in CALL_TAIL:
                grp.append(words[i]); i += 1
        units.append(grp)
    # 后处理：固定词组 Flight**Level**、holding**point** 之类的前缀并到下一个单元
    glued = []
    for u in units:
        if glued and _key(u[0]) in PREFIX_GLUE:
            glued[-1].extend(u)
        else:
            glued.append(u)
    return glued


def _pack(words, soft):
    """按语义单元贪心打包，切点只落在单元边界。"""
    blocks, cur, cnt = [], [], 0
    for u in build_units(words):
        if len(u) > CHUNK_HARD:                 # 单元过长（超长呼号）时兜底按词拆
            step = max(soft, 1)
            for s in range(0, len(u), step):
                blocks.append(cur + u[s:s + step]); cur = []
            cnt = 0
            continue
        if cur and cnt + len(u) > soft:
            blocks.append(cur); cur, cnt = [], 0
        cur.extend(u); cnt += len(u)
    if cur:
        blocks.append(cur)
    return [" ".join(b) for b in blocks if b]


def split_chunks(text, maxw=None):
    """语义感知分块。

    1) 句号/问号/叹号 = 句子级边界，**无条件断开**（实测：跨句后标签必衰减，
       第 219 行 "…due performance. Request…" 在合成为一块时末段 HNR 漂移 +9.1 dB，
       用户直接听出来第二个 Request 开始变本音了）
    2) 单个 neue 句子 ≤NO_SPLIT_WORDS 词 → 不切（实测 14~16 词漂移仍 ≤3.6 dB）
    3) 更长的句子才按逗号等软标点断，必要时再按「语义单元」贪心打包。

    注：默认参数不能写成 maxw=CHUNK_WORDS —— 那是定义时绑定，运行时改常量不生效。
    """
    if maxw is None:
        maxw = CHUNK_WORDS
    words = text.split()
    if maxw <= 0:
        return [text]

    # 1) 句号/问号/叹号：句子级边界，无条件断开
    segs, cur = [], []
    for w in words:
        cur.append(w)
        if w.rstrip().endswith(_SENT_END):
            segs.append(cur); cur = []
    if cur:
        segs.append(cur)

    def soft_split(seg):
        """句内再按逗号等软标点断；超过 maxw 词的段才按语义单元打包。"""
        subs, c2 = [], []
        for w in seg:
            c2.append(w)
            if w.rstrip().endswith(_SOFT_END):
                subs.append(c2); c2 = []
        if c2:
            subs.append(c2)
        # 碎块并入相邻段（能往前并就往前，第一块太短则往后并）
        merged, i = [], 0
        while i < len(subs):
            sb = subs[i]
            if (len(sb) < CHUNK_MIN_WORDS and len(subs) > 1
                    and i < len(subs) - 1):
                if merged:
                    merged[-1].extend(sb)
                else:
                    subs[i + 1] = sb + subs[i + 1]
                i += 1
                continue
            merged.append(sb)
            i += 1
        out = []
        for sb in merged:
            out.extend(_pack(sb, maxw) if len(sb) > maxw else [" ".join(sb)])
        return out

    result = []
    for seg in segs:
        if len(seg) <= NO_SPLIT_WORDS and not any(
                w.rstrip().endswith(_SOFT_END) for w in seg[:-1]):
            result.append(" ".join(seg))       # 短且无逗号：整句一次合成
        else:
            result.extend(soft_split(seg))
    return result or [text]


_BASE_SPLIT = split_chunks      # 返工用的"真身"，避免 split_chunks_fine 自我递归


# ------------------------------------------------------------------ 音频拼装工具
# 为什么不用 ffmpeg 的 silenceremove+concat：
#   silenceremove 靠阈值判定静音，气声本来就轻，尾音（Juliett 的 /t/ 爆破）整体低于阈值
#   → 被当成静音整段裁掉，实测就是用户听到的「Juliett 这个音被吞了」。
#   这里改成 numpy 手动处理：保守裁边（-62 dB + 留 25 ms 余量）+ 交叉淡化拼接。
TRIM_THRESH_DB = -62.0     # 低于此电平认为该段是静音（比 -55 保守得多）
TRIM_PAD_SEC   = 0.025     # 裁完后保留的一点点余量，防止咬掉弱辅音
LEVEL_MATCH_DB = 3.0       # 相邻两块过渡处的音量自动对齐上限（±dB）


def _rolling_rms(x, sr, win=0.02):
    w = max(1, int(win * sr))
    pad = (-len(x)) % w
    if pad:
        x = np.concatenate([x, np.zeros(pad, dtype=x.dtype)])
    blocks = x[:len(x) // w * w].reshape(-1, w)
    rms = np.sqrt((blocks.astype(np.float64) ** 2).mean(axis=1) + 1e-20)
    return rms, w


def _trim_edges(x, sr):
    """只裁掉明确为静音的部分，并留 25 ms 余量 —— 绝不咬到尾音。"""
    thr = 10 ** (TRIM_THRESH_DB / 20.0)
    pad = int(TRIM_PAD_SEC * sr)
    rms, w = _rolling_rms(x, sr)
    if not len(rms):
        return x
    idx = np.nonzero(rms > thr)[0]
    if not len(idx):                      # 整段都极轻（极端情况）：原样返回
        return x
    a = max(0, int(idx[0]) * w - pad)
    b = min(len(x), int(idx[-1] + 1) * w + pad)
    return x[a:b]


def _rms_db(x):
    if not len(x):
        return -120.0
    return 10.0 * math.log10(float((x.astype(np.float64) ** 2).mean()) + 1e-20)


def _join_crossfade(prev, cur, sr, xfade, gap):
    """把 cur 接到 prev 后面：音量对齐 → 交叉淡化。返回拼接后的 float32 数组。"""
    prev = _trim_edges(prev, sr) if TRIM_EDGES else prev
    cur = _trim_edges(cur, sr) if TRIM_EDGES else cur

    # 1) 音量对齐（气声每次生成的响度有 ±几 dB 抖动，不处理会在衔接处听出一跳）
    win = min(len(prev), len(cur), int(0.6 * sr))
    if win > sr // 10:
        d_db = _rms_db(prev[-win:]) - _rms_db(cur[:win])
        clamp = LEVEL_MATCH_DB
        if abs(d_db) > 0.3:
            g = 10 ** (max(-clamp, min(clamp, d_db)) / 20.0)
            cur = (cur.astype(np.float32) * np.float32(g))

    # 2) 交叉淡化
    if gap > 0:
        sil = np.zeros(int(gap * sr), dtype=np.float32)
        return np.concatenate([prev, sil, cur]).astype(np.float32)
    n = int(xfade * sr)
    n = max(0, min(n, len(prev), len(cur)))
    if n <= 0:
        return np.concatenate([prev, cur]).astype(np.float32)
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    down = np.sqrt(1.0 - t)          # 等功率淡出，响度不塌陷
    up = np.sqrt(t)
    out = prev.copy()
    out[-n:] = prev[-n:] * down + cur[:n] * up
    return np.concatenate([out, cur[n:]]).astype(np.float32)


def _resample_linear(x, sr_in, sr_out):
    """极简线性重采样（只在 ElevenLabs 返回采样率不一致时兜底）"""
    n = int(round(len(x) * sr_out / float(sr_in)))
    src_pos = np.linspace(0.0, len(x) - 1, n, dtype=np.float64)
    idx = np.floor(src_pos).astype(np.int64)
    frac = src_pos - idx
    idx = np.clip(idx, 0, len(x) - 2)
    return (x[idx] * (1.0 - frac) + x[idx + 1] * frac).astype(np.float32)


def _decode_f32(path):
    """mp3 → float32 单声道，返回 (采样率, 数组)。中间文件落在项目 .cache 下。"""
    sr = 44100
    p = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                       capture_output=True)
    x = np.frombuffer(p.stdout, dtype=np.float32)
    return sr, x


def _encode_f32(x, sr, out_mp3):
    """numpy → mp3。**走 stdin 管道，不落盘**。

    以前是先写一个临时 raw 再让 ffmpeg 读，但有两个坑：
      ① 用固定路径时多线程会互相覆盖（曾导致全量随机丢 47 句）；
      ② 改成带线程号的文件名后又撞上 `os.remove` 被批量删除保护拦
         （累计几十次就要求确认，整个 post 直接崩，`try/except` 挡不住）。
    走管道既没有临时文件，也彻底解决了并发覆盖。
    """
    p = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                          "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
                          "-c:a", "libmp3lame", "-b:a", "192k", out_mp3],
                         stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    err = p.communicate(np.clip(x, -1.0, 1.0).astype(np.float32).tobytes())[1]
    if p.returncode != 0:
        raise RuntimeError("_encode_f32 失败：%s"
                           % err.decode("utf-8", "replace")[-300:])


# ------------------------------------------------------------------ 质检与返工
# 为什么必须有这道工序：标签衰减有随机性（同长度的句子有的 OK 有的掉），
# 实测 20 句「无标点 9~16 词」里仍有 3 句（15%）漂移超标，最差 +5.3 dB。
# 所以不能只靠切分规则猜，**必须逐句量化验收，不合格的自动重录**。
DRIFT_THRESH = 2.5      # 末段相对首段的 HNR 漂移超过这么多 dB 就判定"后半句变本音"
FINE_WORDS = 6          # 返工时按这个软预算重新做语义打包（比常规更细）

# ---- 兜底质检：只抓「长段非气声 + 音量偏大」----
# 用户明确说条件可以宽松 —— 目的不是逐句挑刺，而是防止某一段突然变成正常说话、
# 音量窜上来把人吵醒。所以三个条件必须**同时**满足才算问题：
#   ① 成片连续（不是个别字）  ② 明显不像气声  ③ 明显比本句常态响
# 全程气声但整体偏响的句子不在此列（那是 loudnorm 该管的事）。
LOUD_WIN_SEC    = 1.0   # 滑窗长度（秒）
LOUD_HOP_SEC    = 0.5   # 滑窗步长（秒）
LOUD_SPAN_SEC   = 2.5   # 「长段」门槛：连续成片达到这么多秒才判问题
LOUD_GAP_TOL    = 1     # 允许中间漏掉几个窗仍算同一片（呼吸停顿很正常）
LOUD_HNR_ABS = 2.0      # 绝对门槛：窗内 HNR 超过它就肯定不是气声了。
                        #   实测标定：合格气声素材全窗最高才 -0.4 dB（v13 样音 15 句），
                        #   而正常发声素材是 +7 dB 上下 —— 中间空着 8 dB，完全不会误伤。
LOUD_EXCESS_DB  = 3.0   # 「偏响」门槛：比本句常态（或比全批常态）高这么多 dB 才算吵

# ---- 超标句的降噪兜底（零额度，纯 numpy）----
# 重录一次仍吵的句子，直接按短时包络做平滑压制：把冒出来的段落压回常态。
DUCK_HEADROOM  = 1.0    # 压到「本句中位响度 + 1 dB」为止（保留一点起伏，别压成一条直线）
DUCK_MAX_DB    = 20.0   # 安全上限，正常用不到这么深
DUCK_SMOOTH_MS = 220    # 增益曲线平滑窗口（毫秒），太短会产生抽水音效


def clip_drift(path):
    """单句 clip 的 HNR 漂移（末段 − 首段）。返回 None 表示无法测量。"""
    if np is None or not os.path.exists(path):
        return None
    sr, x = _decode_f32(path)
    if len(x) < sr:
        return None
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import whisper_hold as wh
    except Exception:                     # noqa
        return None
    # 顺序很重要：**先**从整句提取有声帧，再三等分。反过来的话，
    # 三段各自 voiced 得到的有声帧数不同，同一句会测出不同结果（实测差 2 dB 以上）。
    v = wh.voiced(x, sr)
    if len(v) < sr // 5:
        return None
    n = len(v) // 3
    vals = [wh.hnr_and_rms(v[j * n:(j + 1) * n], sr)[0] for j in range(3)]
    return vals[-1] - vals[0], vals


# ------------------------------------------------- 兜底质检：长段非气声且音量偏大
def frames_stats(x, sr, frame_sec=0.040, hop_sec=0.020):
    """一次性算出全句每帧的 (中点时刻, HNR dB, RMS)。

    原版 whisper_hold.hnr_and_rms 是逐帧 Python 循环 + np.correlate（O(n²)），
    扫 900 句要跑几个小时。这里改用 FFT 自相关并一次性矩阵化，快两个数量级。
    """
    frame, hop = int(sr * frame_sec), int(sr * hop_sec)
    m = (len(x) - frame) // hop + 1
    if m < 4:
        return None
    n = 1
    while n < frame * 2:
        n <<= 1
    idx = np.arange(frame)[None, :] + hop * np.arange(m)[:, None]
    fr = x[idx].astype(np.float64)
    fr -= fr.mean(axis=1, keepdims=True)
    fr *= np.hanning(frame)[None, :]
    F = np.fft.rfft(fr, n=n, axis=1)
    ac = np.fft.irfft(np.abs(F) ** 2, n=n, axis=1)[:, :frame]
    ac /= ac[:, :1] + 1e-12
    lo, hi = max(1, int(sr / 500)), min(frame - 1, int(sr / 70))
    r = np.clip(ac[:, lo:hi + 1].max(axis=1), 0.05, 0.995)
    return ((np.arange(m) * hop + frame / 2.0) / float(sr),
            10 * np.log10(r / (1.0 - r)),
            fr.std(axis=1))


def clip_profile(path):
    """解码一句，做窗口级测量。返回 dict，窗口数据留着给后面的判定复用。"""
    if np is None or not os.path.exists(path):
        return None
    sr, x = _decode_f32(path)
    st = frames_stats(x, sr)
    if st is None:
        return None
    tmid, hnr, env = st
    if env.max() <= 1e-6:
        return None
    sound = env > env.max() * 0.03            # 粗略有声 mask，挡掉句间/句中停顿
    ts, hs, es = [], [], []
    for s in np.arange(0.0, max(float(tmid[-1]) - LOUD_WIN_SEC, 0.0) + 1e-9,
                       LOUD_HOP_SEC):
        sel = (tmid >= s) & (tmid < s + LOUD_WIN_SEC)
        vs = sel & sound
        if sel.sum() < 3 or vs.sum() < 3:
            continue
        e = float(np.sqrt((env[vs] ** 2).mean()))
        ts.append(float(s))
        hs.append(float(np.median(hnr[vs])))
        es.append(20 * np.log10(e + 1e-12))
    if len(ts) < 3:
        return None
    return {"t": np.array(ts), "hnr": np.array(hs), "rms": np.array(es),
            "hnr_med": float(np.median(hnr[sound])),
            "rms_med": float(np.median(es))}


def loud_scan(path, ref=None):
    """单句判定：有没有「长段非气声 + 音量偏大」。ref 是全批中位响度（用于整句判据）。"""
    p = clip_profile(path)
    if p is None:
        return None
    return judge_profile(p, p["rms_med"] if ref is None else ref)


def judge_profile(p, ref):
    """两级判据，命中任一即算问题（都在「非气声」和「偏响」上双重确认）：

    P1 句中掉气声  成片 ≥LOUD_SPAN_SEC 的窗：HNR > LOUD_HNR_ABS 且比本句常态响 ≥LOUD_EXCESS_DB
    P2 整句没进去  整句 HNR 中位 > LOUD_HNR_ABS 且整句比全批中位还响 ≥LOUD_EXCESS_DB
       —— P2 专治「标签压根没生效」：这种句子句内很平坦，只看句内相对量会漏掉。
    """
    h, e, ss = p["hnr"], p["rms"], p["t"]
    out = {"span": 0.0, "excess": 0.0, "peak": 0.0, "why": "", "win": len(ss),
           "extra": 0.0}
    d_sent = p["rms_med"] - ref
    if p["hnr_med"] > LOUD_HNR_ABS and d_sent >= LOUD_EXCESS_DB:
        # P2 的句子句内是平的，光压包络没用 —— 得整句衰减回全批水位
        out.update(span=float(ss[-1] - ss[0] + LOUD_WIN_SEC), excess=d_sent,
                   peak=float(e.max() - p["rms_med"]), why="整句不是气声",
                   extra=min(DUCK_MAX_DB, max(0.0, d_sent - DUCK_HEADROOM)))
        return out
    flag = (h > LOUD_HNR_ABS) & (e > p["rms_med"] + LOUD_EXCESS_DB)
    if not flag.any():
        return out
    best = (0.0, 0.0)
    i = 0
    while i < len(flag):
        if not flag[i]:
            i += 1
            continue
        j, gap = i, 0
        while j + 1 < len(flag) and (flag[j + 1] or gap < LOUD_GAP_TOL):
            gap = 0 if flag[j + 1] else gap + 1
            j += 1
        span = float(ss[j] - ss[i] + LOUD_WIN_SEC)
        excess = float(e[i:j + 1].max() - p["rms_med"])
        if span > best[0]:
            best = (span, excess)
        i = j + 1
    if best[0] > 0:
        out.update(span=best[0], excess=best[1],
                   peak=float(e.max() - p["rms_med"]), why="中途变本音")
    return out


def scan_pass(idxs, workers=8):
    """第一遍：并行解码，返回 (missing, {行号: profile})"""
    from concurrent.futures import ThreadPoolExecutor
    missing, profs = [], {}

    def one(i):
        return i, clip_profile(os.path.join(CLIPS, "%04d.mp3" % i))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, p in ex.map(one, idxs):
            if p is None:
                missing.append(i)
            else:
                profs[i] = p
    return missing, profs


def batch_ref(profs):
    """全批中位响度：整句判据 P2 用的参照。"""
    return float(np.median([p["rms_med"] for p in profs.values()]))


def find_hits(profs, ref, thr_span=None):
    """第二遍：纯计算，不碰磁盘"""
    thr = LOUD_SPAN_SEC if thr_span is None else thr_span
    hits = []
    for i, p in profs.items():
        if p is None:
            continue
        r = judge_profile(p, ref)
        if r["span"] >= thr:
            hits.append((i, r))
    return sorted(hits, key=lambda kv: -kv[1]["excess"])


def scan_clips(idxs, workers=8):
    """一步到位的检测入口：返回 (missing, hits, ref)"""
    missing, profs = scan_pass(idxs, workers=workers)
    ref = batch_ref(profs) if profs else 0.0
    return missing, find_hits(profs, ref), ref


def duck_clip(src_path, out_path, extra_db=0.0):
    """把一句话里冒出来的响段压回常态。**零额度**的兜底手段。

    不按闸值硬削（会有抽水音效），而是：算短时包络 → 目标 = 本句中位 +DUCK_HEADROOM
    → 只压不抬 → 限深 → hanning 平滑 → 插值成逐样本增益曲线。
    extra_db 用于「整句本来就比同批响」的情形（P2）：整句再整体衰减这么多。
    """
    sr, x = _decode_f32(src_path)
    frame, hop = int(sr * 0.050), int(sr * 0.010)
    m = (len(x) - frame) // hop + 1
    if m < 4:
        return 0.0
    idx = np.arange(frame)[None, :] + hop * np.arange(m)[:, None]
    env = x[idx].astype(np.float64).std(axis=1)
    env_db = 20 * np.log10(env + 1e-9)
    ref = float(np.median(env_db))
    g = np.minimum(0.0, (ref + DUCK_HEADROOM) - env_db)   # 只压不抬
    g = np.clip(g - extra_db, -DUCK_MAX_DB, 0.0)
    win = max(1, int(DUCK_SMOOTH_MS / 1000.0 * sr / hop))
    if win > 1:
        k = np.hanning(win)
        k /= k.sum()
        g = np.convolve(g, k, mode="same")
    gain = np.interp(np.arange(len(x)), np.arange(m) * hop + frame / 2.0, g,
                     left=g[0], right=g[-1])
    y = x.astype(np.float64) * (10 ** (gain / 20.0))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    _encode_f32(y.astype(np.float32), sr, out_path)
    return float(min(DUCK_MAX_DB,
                     max(0.0, float(env_db.max()) - (ref + DUCK_HEADROOM)) + extra_db))


def duck_dir():
    """降噪兜底后的 clip 覆盖目录：整合时最后套用，避免被 rebuild 冲掉"""
    return CLIPS + "_duck"


def apply_fixes():
    """把 *_duck 里的修正版覆盖回 CLIPS（必须在 rebuild_clips 之后调用）。

    幂等：已经覆盖过就不再动。否则每次 post 都会刷新这 3 个 clip 的 mtime，
    连带让 cat → prep → Stage A 的缓存链全部失效，白跑 20~30 秒。
    """
    d = duck_dir()
    if not os.path.isdir(d):
        return 0
    n = 0
    for f in sorted(os.listdir(d)):
        if not f.endswith(".mp3"):
            continue
        src, dst = os.path.join(d, f), os.path.join(CLIPS, f)
        if os.path.exists(dst) and \
           os.path.getsize(dst) == os.path.getsize(src) and \
           os.path.getmtime(dst) >= os.path.getmtime(src):
            n += 1                              # 已经应用过了
            continue
        shutil.copyfile(src, dst)
        n += 1
    return n


def scan_clips(idxs, workers=8):
    """并行扫描，返回 (missing, hits)；hits 是 [(行号, info)] 按超出量降序"""
    from concurrent.futures import ThreadPoolExecutor
    missing, res = [], []

    def one(i):
        return i, loud_scan(os.path.join(CLIPS, "%04d.mp3" % i))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, r in ex.map(one, idxs):
            if r is None:
                missing.append(i)
            elif r["span"] >= LOUD_SPAN_SEC:
                res.append((i, r))
    return missing, sorted(res, key=lambda kv: -kv[1]["excess"])


def split_chunks_fine(text, maxw=None):
    """返工用：比常规切得更细（每块 ≤FINE_WORDS 词），保证每块标签都新鲜。

    注意这里必须走 _BASE_SPLIT（定义时捕获的真身）：返工时全局 split_chunks
    会被临时替换成本函数，直接调用全局会无限递归。
    """
    out = []
    for s in _BASE_SPLIT(text, maxw):
        ws = s.split()
        out.extend(_pack(ws, FINE_WORDS) if len(ws) > FINE_WORDS else [s])
    return out


def check_and_refix(idxs, key=None, voice=None, thresh=DRIFT_THRESH, rounds=2):
    """逐句测 HNR 漂移，不合格的按更细的粒度重录。

    返回 (bad_before, still_bad)。key 为 None 时只检测不返工。
    """
    missing, bad = [], []
    for i in idxs:
        r = clip_drift(os.path.join(CLIPS, "%04d.mp3" % i))
        if r is None:
            missing.append(i)
            continue
        d, _ = r
        if d >= thresh:
            bad.append((i, d))
    return missing, bad


def refix_sentences(bad, src, key, voice, tries=3):
    """把不合格的句子按 ≤FINE_WORDS 词重录。返回 [(行号, 旧漂移, 新漂移, 信息)]"""
    orig = globals()["split_chunks"]
    globals()["split_chunks"] = split_chunks_fine
    out = []
    try:
        for i, d0 in bad:
            out_path = os.path.join(CLIPS, "%04d.mp3" % i)
            ok, info = synth_one_chunks(i, src[i - 1], out_path, key, voice,
                                        MODEL_ID, tries)
            if not ok:
                out.append((i, d0, None, info))
                continue
            r = clip_drift(out_path)
            out.append((i, d0, None if r is None else r[0], "ok"))
    finally:
        globals()["split_chunks"] = orig
    return out


def parts_dir():
    """原始分块（重贴标签前的干声）存档目录，名字跟 CLIPS 走"""
    return CLIPS + "_parts"


def manifest_path():
    return os.path.join(parts_dir(), "_manifest.json")


def load_manifest():
    """每句由哪几个 part 拼成的清单 {"0408": ["0408_00.mp3", ...]}。

    存**文件名列表**而不是块数：返工时块数会变（切得更细），
    旧块（文件名仍在目录里）不能跟着混进来。键必须是 %04d，与文件名前缀一致 ——
    早期版本用 str(idx) 当键，键名对不上等于没有清单。
    """
    try:
        with open(manifest_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                       # noqa
        return {}


def save_manifest(man):
    try:
        os.makedirs(parts_dir(), exist_ok=True)
        tmp = manifest_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(man, f)
        os.replace(tmp, manifest_path())
    except Exception:                       # noqa
        pass


def set_parts(idx, names):
    """记录第 idx 句最终由哪几个 part 拼成；不足 2 块表示整句一次合成，不参与重拼。"""
    man = load_manifest()
    key = "%04d" % int(idx)
    if len(names) > 1:
        man[key] = list(names)
    else:
        man.pop(key, None)
    save_manifest(man)


def rebuild_clips(xfade, gap, skip_up_to_date=True):
    """用新的交叉淡化参数重做所有多块句子的 clip。

    **纯后处理、零额度**：素材来自 parts_dir() 里每块的原始 mp3。
    所以听完觉得衔接怪，只要改 --xfade 再跑一次 post 就行，不必重新合成。
    块数以 manifest 为准：返工时块数会变（返工切得更细），没有清单就会
    把上一次的旧块一起拼进来。

    skip_up_to_date=True 时，若某句的 clip 比它所有 parts 都新，说明这次没换算得上，直接跳过。
    """
    pd = parts_dir()
    if not os.path.isdir(pd):
        return 0, False
    man = load_manifest()
    groups = {}
    for f in sorted(os.listdir(pd)):
        if not f.endswith(".mp3") or "_" not in f:
            continue
        idx, rest = f.split("_", 1)
        try:
            order = int(rest[:2])
        except ValueError:
            continue
        groups.setdefault(idx, []).append((order, os.path.join(pd, f)))

    used = {}
    for k, names in man.items():
        fs = [os.path.join(pd, nm) for nm in names]
        if len(fs) >= 2 and all(os.path.exists(p) for p in fs):
            used[k] = [(0, p) for p in fs]
    for k, items in groups.items():          # 没清单的旧素材：退回整个目录
        used.setdefault(k, sorted(items))

    # 已经拼好且比所有 parts 都新 → 这次的参数没变，不用重拼（省 5~6 分钟）。
    # 判断很轻：534 次 stat，比真的重拼便宜三个数量级。
    def up_to_date(idx, items):
        out = os.path.join(CLIPS, "%04d.mp3" % int(idx))
        if not skip_up_to_date or not os.path.exists(out):
            return False
        t_out = os.path.getmtime(out)
        return all(t_out > os.path.getmtime(p) for _o, p in items)

    n = 0
    for idx, items in sorted(used.items()):
        if len(items) < 2 or up_to_date(idx, items):
            continue
        sr = None
        x = None
        for _, p in sorted(items):
            s, seg = _decode_f32(p)
            if x is None:
                sr, x = s, seg
            else:
                if s != sr:
                    seg = _resample_linear(seg, s, sr)
                x = _join_crossfade(x, seg, sr, xfade, gap)
        os.makedirs(CLIPS, exist_ok=True)
        _encode_f32(x, sr, os.path.join(CLIPS, "%04d.mp3" % int(idx)))
        n += 1
    return n, True


def synth_one_chunks(idx, text, out, key, voice_id, model_id, tries):
    """把一句（可能分块）合成到 out。返回 (bool, info)"""
    url = "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=%s" % (
        voice_id, OUTPUT_FORMAT)

    def fetch(one):
        body = {"text": STYLE_TAG + one, "model_id": model_id,
                "voice_settings": VOICE_SETTINGS}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
        req.add_header("xi-api-key", key)
        req.add_header("Content-Type", "application/json")
        req.add_header("accept", "audio/mpeg")
        last = ""
        for n in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                if len(data) < 500:
                    raise RuntimeError("返回音频过小: %d bytes" % len(data))
                return data, "ok"
            except urllib.error.HTTPError as e:
                last = "HTTP %s %s" % (e.code, e.read()[:200].decode(errors="replace"))
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** n * 3)
                    continue
                break
            except Exception as e:                      # noqa
                last = str(e)
                time.sleep(2 ** n * 2)
        return None, last

    chunks = split_chunks(text)
    if len(chunks) == 1:
        data, info = fetch(chunks[0])
        if data is None:
            return False, info
        with open(out, "wb") as f:
            f.write(data)
        set_parts(idx, [])      # 之前可能是多块，返工后变整句 → 撤掉旧清单
        return True, info

    # 直接写进 parts 存档目录，省掉一次拷贝，
    # 也省掉 shutil.rmtree —— 那个在受限环境下会被批量删除保护拦住。
    pd = parts_dir()
    os.makedirs(pd, exist_ok=True)
    raws, names = [], []
    for i, c in enumerate(chunks):
        data, info = fetch(c)
        if data is None:
            return False, "chunk#%d: %s" % (i, info)
        p = os.path.join(pd, "%04d_%02d.mp3" % (idx, i))
        with open(p, "wb") as f:
            f.write(data)
        names.append(os.path.basename(p))
        s, seg = _decode_f32(p)
        raws.append((s, seg))

    sr = raws[0][0]
    x = raws[0][1]
    for s, seg in raws[1:]:
        if s != sr:
            seg = _resample_linear(seg, s, sr)
        x = _join_crossfade(x, seg, sr, CHUNK_XFADE, CHUNK_GAP)
    _encode_f32(x, sr, out)
    set_parts(idx, names)
    return True, "ok(%d 块)" % len(chunks)


def synth(idx, text, key, voice_id, model_id=MODEL_ID, tries=4):
    """单句合成；成功返回 True。已存在则跳过（断点续传）"""
    out = os.path.join(CLIPS, "%04d.mp3" % idx)
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return idx, True, "cached"
    good, info = synth_one_chunks(idx, text, out, key, voice_id, model_id, tries)
    return idx, good, info


def run_batch(idxs, texts, key, voice_id, workers=4):
    ok, fail = 0, []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(synth, i, texts[i - 1], key, voice_id) for i in idxs]
        done = 0
        for fu in as_completed(futs):
            i, good, info = fu.result()
            done += 1
            if good:
                ok += 1
            else:
                fail.append((i, info))
            if done % 50 == 0 or done == len(futs):
                print("  ...%d/%d  成功 %d  失败 %d" % (done, len(futs), ok, len(fail)),
                      flush=True)
    if fail:
        print("\n失败清单（重跑会自动续传）：")
        for i, info in fail[:30]:
            print("  %04d  %s" % (i, info))
    return ok, fail


# ------------------------------------------------------------------ 拼接 + 后处理
def ff(*a):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"] + list(a)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 失败:\n%s\n%s" % (" ".join(a), r.stderr[-2000:]))
    return r


def make_silence(sec, path):
    """幂等：gap 没变就不重建。否则每次 post 都会刷新它的 mtime，
    把下游 cat → prep → Stage A 的缓存链整条打断。"""
    lock = path + ".sec"
    if os.path.exists(path) and os.path.exists(lock):
        try:
            if abs(float(open(lock, encoding="utf-8").read().strip()) - sec) < 1e-9:
                return
        except Exception:                       # noqa
            pass
    ff("-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(sec),
       "-c:a", "libmp3lame", "-b:a", "192k", path)
    open(lock, "w", encoding="utf-8").write(repr(sec))


def concat_clips(idxs, out_wav, gap=GAP_SEC):
    """把各句中间插静音拼成一条。**幂等**：产物比所有输入都新就直接返回。

    不做这一步的话，每次 post 都会重写一遍 cat → 它的 mtime 变化会让下游
    Stage A / loudnorm 的缓存全部失效（白跑 20~30 秒）。
    """
    silence = os.path.join(CACHE, "silence.mp3")
    make_silence(gap, silence)
    if os.path.exists(out_wav):
        try:
            t_out = os.path.getmtime(out_wav)
            newest = max([os.path.getmtime(os.path.join(CLIPS, "%04d.mp3" % i))
                          for i in idxs] + [os.path.getmtime(silence)])
            if newest < t_out:
                return False                     # 已经是最新，跳过
        except OSError:                          # noqa
            pass
    lst = os.path.join(CACHE, "concat_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for i in idxs:
            f.write("file '%s'\n" % os.path.join(CLIPS, "%04d.mp3" % i))
            f.write("file '%s'\n" % silence)
    ff("-f", "concat", "-safe", "0", "-i", lst, "-c:a", "copy", out_wav)
    return True


def pos_amplitude(balance=PAN_BALANCE):
    """把「一边 90%、一边 10%」这种声道配比，换算成声像角幅度 pos∈[0,1]。

    等功率声像法则下 L=cos(a)、R=sin(a)，a=π/4 时居中。
    配比 b:(1-b) 意味着 L/R = b/(1-b) = cot(a) → a = atan((1-b)/b)。
    pos 的定义是 a = π/4 + pos·π/4，于是 pos = 1 - 4a/π。
    b=0.90 → a=atan(1/9)=0.1107 rad → pos=0.859 → 两耳差 20·log10(9) ≈ 19.1 dB
    """
    a = math.atan((1.0 - balance) / balance)
    return 1.0 - 4.0 * a / math.pi


def swap_saturation(period=PAN_PERIOD, swap_sec=PAN_SWAP_SEC):
    """由「换边耗时」反推梯形波的过驱倍数。

    削平正弦 clamp(k·sin(2πt/T)) 从 -1 爬到 +1 用时 Δt = T·asin(1/k)/π，
    反解得 k = 1 / sin(π·Δt/T)。k 越大 → 两端停留越久、中间过渡越陡。
    T=180s、Δt=5s → k≈11.5（旧版固定 k=1.6 对应 Δt≈39s，所以听起来慢吞吞）。
    """
    x = math.pi * swap_sec / period
    if x <= 0 or x >= math.pi:
        raise ValueError("PAN_SWAP_SEC 必须大于 0 且小于半个周期")
    return 1.0 / math.sin(x)


def pan_exprs(period=PAN_PERIOD, balance=PAN_BALANCE, swap_sec=PAN_SWAP_SEC):
    """返回 (左声道增益表达式, 右声道增益表达式)，都是关于时间 t 的函数。

    等功率声像法则：L=cos(a), R=sin(a)，保证 L²+R²=1 恒定，游走时音量不会忽大忽小。
    a = π/4 + pos·π/4   →  pos=-1 全左、0 居中、+1 全右
    pos = amp · clamp(sat·sin(2πt/period), -1, 1)
          削平正弦 → 两端长时间停留，中间按 PAN_SWAP_SEC 快速换边
    """
    amp = pos_amplitude(balance)
    sat = swap_saturation(period, swap_sec)
    wave = "%g*sin(2*PI*t/%g)" % (sat, period)
    pos = "%g*(if(gt(%s,1),1,if(lt(%s,-1),-1,%s)))" % (amp, wave, wave, wave)
    return "cos(PI/4+PI/4*(%s))" % pos, "sin(PI/4+PI/4*(%s))" % pos


def dist_expr(period=DIST_PERIOD, depth=DIST_DEPTH):
    """（旧版）远近感。现已并入 build_pan_track()，保留备用。"""
    return "1-%g*(0.5+0.5*sin(2*PI*t/%g))" % (depth, period)


# ------------------------------------------------------------------ 声像控制曲线
def build_pan_track(total_sec, path):
    """算出整条声像 + 远近控制曲线，写成 2 声道 f32le 原始文件。

    为什么不用 ffmpeg 表达式了：用户要求「单侧停留 20~30 秒随机」，
    而 ffmpeg 的 random() 只能按整数索引取值，没法表达"每段随机时长"。
    直接离线算曲线 = 完全可控，也能保证带随机种子时的可复现性。

    返回 (L 数组, R 数组) 的采样时间点数组，便于自测。
    """
    import numpy as np
    amp = pos_amplitude()
    n = int((total_sec + PAN_SWAP_SEC + 5) * CTL_RATE)
    t = np.arange(n) / float(CTL_RATE)
    a = np.full(n, math.pi / 4, dtype=np.float64)      # 角度数组，π/4 = 居中

    # --- 步骤 1：生成 piecewise 事件的"拐点"（时刻, 目标角度）---
    rng = np.random.default_rng(PAN_SEED)
    knots = [(0.0, math.pi / 4)]
    side = 1.0 if rng.random() < 0.5 else -1.0
    cur = 0.0
    while cur < total_sec + PAN_SWAP_SEC:
        target = math.pi / 4 + side * amp * math.pi / 4
        cur += PAN_SWAP_SEC                     # 用 PAN_SWAP_SEC 完成一次换边
        knots.append((cur, target))
        hold = rng.uniform(PAN_HOLD_MIN, PAN_HOLD_MAX)   # ← 随机停留 20~30 秒
        cur += hold
        knots.append((cur, target))             # 停留结束
        side = -side                            # 下一轮换到另一侧
    knots.append((cur + PAN_SWAP_SEC, knots[-1][1]))

    # --- 步骤 2：相邻拐点之间用余弦缓动插值（比线性更顺，不会有换挡感）---
    for (t0, v0), (t1, v1) in zip(knots[:-1], knots[1:]):
        if t1 <= t0:
            continue
        sel = (t >= t0) & (t < t1)
        if not sel.any():
            continue
        u = (t[sel] - t0) / (t1 - t0)
        w = 0.5 - 0.5 * np.cos(math.pi * u)     # cosine ease-in-out
        a[sel] = v0 + (v1 - v0) * w

    # --- 步骤 3：远近感。随机 knots + 余弦插值，保证平滑且极值可控在 [1-depth, 1] ---
    step = 45.0
    kn = np.arange(0, t[-1] + step, step)
    vals = rng.uniform(0.0, 1.0, size=len(kn))
    dns = 1.0 - DIST_DEPTH * np.interp(t, kn, vals)
    # 再做一次短时平滑，去掉插值留下的折角
    win = int(4 * CTL_RATE)
    if win > 1:
        k = np.hanning(win)
        k /= k.sum()
        dns = np.convolve(dns, k, mode="same")
        dns = np.clip(dns, 1.0 - DIST_DEPTH, 1.0)

    L = np.cos(a) * dns
    R = np.sin(a) * dns

    # --- 步骤 4：换边下压（补偿双耳响度求和）---
    # x = 归一化的双耳声级差 |ILD|/ILDmax：0=完全居中，1=完全偏到一侧。
    # 等功率参数化下 pos = 1-4a/π 且 |pos| ≤ amp，所以 x = |pos|/amp。
    # dip 权重用余弦钟形，两端（停留区 x=1 与正中间 x=0）导数都是 0，不会有折角。
    if PAN_DIP > 0:
        x = np.abs(a - math.pi / 4) / (amp * math.pi / 4)
        x = np.clip(x, 0.0, 1.0)
        w = 0.5 * (1.0 + np.cos(math.pi * x))
        if PAN_DIP_SHAPE != 1.0:
            w = np.power(w, PAN_DIP_SHAPE)
        g = 1.0 - PAN_DIP * w
        L = L * g
        R = R * g

    inter = np.empty(L.size * 2, dtype=np.float32)
    inter[0::2] = L
    inter[1::2] = R
    inter.tofile(path)
    return t, L, R


def asmr_chain(mono_src, out_mp3, bitrate="256k", ctl_path=None):
    """单声道 → 真立体声 ASMR：

    Haas 展宽 + 左右声道差异化 EQ + 柔和房间感
      + 深度声场漂移（随机 20~30 秒换一次边，5 秒内完成，极限配比 90:10）
      + 极轻微远近起伏（≤10%）
      + 响度归一

    声像不再用 ffmpeg 表达式，而是乘上 build_pan_track() 预生成的控制信号
    （具体而言 = 一条 2 声道 f32le 曲线，200 Hz，进 ffmpeg 时插值到 48 kHz）。
    """
    ffprobe = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")
    dur = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                          "format=duration", "-of", "default=nw=1:nk=1", mono_src],
                         capture_output=True, text=True)
    src_dur = float(dur.stdout.strip() or 0)
    ctl_path = ctl_path or os.path.join(CACHE, "pan_ctl.raw")
    build_pan_track(src_dur / TEMPO, ctl_path)

    af = (
        "aresample=48000,"
        "atempo=%g,"         # 确定性变速，保持音高
        "highpass=f=55,"
        "lowpass=f=10500,"
        "bass=g=1.8:f=110:w=0.7,"
        "aecho=0.86:0.9:32|57:0.20|0.11,"
        "asplit=2[l][r];"
        "[l]adelay=11,lowpass=f=8800,volume=%g,"
        "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[L];"
        "[r]highpass=f=95,lowpass=f=11000,volume=0.965,"
        "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[R];"
        "[L][R]amerge=inputs=2[st];"
        "[1:a]aresample=48000,"   # 200 Hz 控制信号插值到 48 kHz（默认 swr  sinc 插值）
        "aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000,"
        "channelsplit=channel_layout=stereo[cL][cR];"
        "[st]extrastereo=m=1.6,channelsplit=channel_layout=stereo[cl][cr];"
        "[cl][cL]amultiply[pl];"
        "[cr][cR]amultiply[pr];"
        "[pl][pr]amerge=inputs=2,"
        "loudnorm=I=-18:TP=-2:LRA=11"
    ) % (TEMPO, L_BRANCH_GAIN)
    ff("-i", mono_src, "-f", "f32le", "-ar", str(CTL_RATE), "-ac", "2", "-i", ctl_path,
       "-filter_complex", af,
       "-ac", "2", "-ar", "48000", "-c:a", "libmp3lame", "-b:a", bitrate, out_mp3)


# ------------------------------------------------------------------------------
# 分段并行渲染
#
# 实测（600 秒片段 → 折算 106 分钟全片）：
#   mp3 解码 0.5s ｜ aresample 0.0s ｜ atempo 0.3s ｜ 滤波器组 3.0s ｜ aecho 0.5s
#   左右分路/EQ/delay 3.7s ｜ extrastereo+控制曲线 0.5s ｜ **loudnorm 14.4s** ｜ mp3 编码 2.5s
#   ⇒ 整条链全片只要 4 分钟，**loudnorm 一家占 63%**。
#
# 所以真正的提速思路不是"换更快的滤镜"，而是两点：
#   ① Stage A（变速/EQ/回声/分路/extrastereo）与声像完全无关 → 切成 N 段并行，结果可长期缓存
#   ② loudnorm 只需 measure 一次拿到整体增益 → 换成静态 volume + 限幅，
#      改声像参数时连 measure 都不用重跑
# 结果：首次 ~2 分钟，之后改 dip/balance 只跑 Stage B ≈ 1 分钟。
# ------------------------------------------------------------------------------
N_PIECES    = 8       # Stage A 并行段数（20 逻辑核心，8 段已经能吃满且开销可控）
PIECE_PAD   = 0.60    # 每段前后多喂这么多秒素材，处理完再裁掉。
                      # 用来吸收 aecho(57ms)+adelay(11ms)+各 FIR 群延迟，
                      # 保证接缝处与「一口气处理」逐样本一致。
LOUD_JSON   = None    # loudnorm 实测增益的缓存路径，由 loud_cache_path() 派生


def write_index(idxs, gap, path, tempo=1.0):
    """生成 900 句时间戳目录（便于回听定位）。tempo 为该批次实际做的变速倍率"""
    durs = clip_durations(idxs)
    t = 0.0
    lines = ["# 句\t开始时间\t原文"]
    src = [l.rstrip("\n") for l in open(TXT, encoding="utf-8") if l.strip()]
    for i in idxs:
        lines.append("%d\t%02d:%02d:%02d\t%s" % (
            i, int(t // 3600), int(t % 3600 // 60), int(t % 60), src[i - 1]))
        t += durs[i] / tempo + gap
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return t


# ------------------------------------------------------------------ 分段并行渲染
def dur_cache_path():
    return os.path.join(CACHE, "durations_%s.json" % os.path.basename(CLIPS))


def clip_durations(idxs, rebuild=False):
    """每句的秒数，带 json 缓存。

    write_index 每次 post 都要对 900 个 clip 串行走一遍 ffprobe（实测约 2 分钟），
    而 clip 一旦生成就不会再变 —— 缓存一次即可。
    """
    p = dur_cache_path()
    key = str(len(idxs))
    if not rebuild and os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            if key in d:
                return {int(k): v for k, v in d[key].items()}
        except Exception:                       # noqa
            pass
    ffprobe = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")

    def probe(i):
        r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1",
                            os.path.join(CLIPS, "%04d.mp3" % i)],
                           capture_output=True, text=True)
        return i, float(r.stdout.strip() or 0)

    out = {}
    with ThreadPoolExecutor(max_workers=16) as ex:      # ffprobe 是 IO 密集，16 路很安全
        for i, v in ex.map(probe, idxs):
            out[i] = v
    cache = {}
    if os.path.exists(p):
        try:
            cache = json.load(open(p, encoding="utf-8"))
        except Exception:                       # noqa
            cache = {}
    cache[key] = out
    json.dump(cache, open(p, "w", encoding="utf-8"))
    return out


def _stage_a_chain():
    """与声像无关、且没有「帧粒度量化」问题的那一半链路。产物可以长期缓存。

    前置前置做掉了 aresample + atempo，所以这里只剩 FIR/IIR/delay/gain，
    可以在任意位置切开而不产生相位错位。
    """
    return (
        "highpass=f=55,lowpass=f=10500,bass=g=1.8:f=110:w=0.7,"
        "aecho=0.86:0.9:32|57:0.20|0.11,"
        "asplit=2[l][r];"
        "[l]adelay=11,lowpass=f=8800,volume=%g,"
        "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[L];"
        "[r]highpass=f=95,lowpass=f=11000,volume=0.965,"
        "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000[R];"
        "[L][R]amerge=inputs=2,extrastereo=m=1.6"
    ) % (L_BRANCH_GAIN,)


def prepared_cuts(durations, idxs, gap_raw, pieces):
    """在句间静音的正中间下刀，返回**成品时间轴**（已变速）上的切点。

    为什么挑静音中点：句子之间本来就插了 gap_raw 秒静音，在那里分段，
    处理完拼回去不会有任何瞬态；同时每段前后多喂 PIECE_PAD 秒再裁掉，
    用来吸收 aecho(57ms)+adelay(11ms)+FIR 群延迟。
    """
    if pieces <= 1:
        return None
    marks, t = [], 0.0
    for i in idxs:
        t += durations[i]
        marks.append((t + gap_raw * 0.5) / TEMPO)
        t += gap_raw
    total = t / TEMPO
    cuts = [0.0]
    for k in range(1, pieces):
        want = total * k / float(pieces)
        cuts.append(min(marks, key=lambda m: abs(m - want)))
    cuts.append(total)
    return sorted(set(cuts))


def stage_paths(tag):
    """Stage A 产物的目录 / 清单 / 合并后文件"""
    base = os.path.join(CACHE, "stage_a_%s" % tag)
    return base, os.path.join(base, "meta.json"), base + ".wav"


def ensure_prepared_src(mono_src, tag):
    """mp3 → PCM(48k) → atempo → prepared.wav。**必须整段做一次**，返回它的路径。

    实测教训：atempo 会把内部处理窗口对齐到 4096/2048 采样这种 2 的幂次边界，
    所以一旦分段跑 atempo，每个接缝就会错位 40~85 ms —— 听得见的"咔"。
    而整段跑一次 atempo 全片只要约 3 秒，非常划算。

    做完这一步后，时间轴就是「成品时间轴」（素材已按 TEMPO 压缩过），
    剩下的滤镜全是 FIR/IIR/delay/gain，没有帧粒度量化问题，可以放心分段。
    """
    prep = os.path.join(CACHE, "prep_%s.wav" % tag)
    want = "%s|%d|%.3f|%g" % (os.path.basename(mono_src), os.path.getsize(mono_src),
                              os.path.getmtime(mono_src), TEMPO)
    lock = prep + ".src"
    if os.path.exists(prep) and os.path.exists(lock):
        try:
            if open(lock, encoding="utf-8").read().strip() == want:
                return prep
        except Exception:                       # noqa
            pass
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-i", mono_src,
                    "-filter:a", "aresample=48000,atempo=%g" % TEMPO,
                    "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", prep],
                   check=True, capture_output=True, text=True)
    open(lock, "w", encoding="utf-8").write(want)
    return prep


def render_stage_a(mono_src, tag, cuts, workers=N_PIECES, pad=PIECE_PAD, force=False):
    """并行渲染与声像无关的那一半。

    切成 len(cuts)-1 段，各段多喂 pad 秒再裁掉，并行跑同一条 filter chain，
    最后按顺序拼成一个 stereo wav。每段再用 -frames:a 强制到采样级精确长度，
    杜绝 round 误差逐段累积。
    返回 (耗时秒, 是否真的重算了)。
    """
    t0 = time.time()
    base, meta_p, merged = stage_paths(tag)
    os.makedirs(base, exist_ok=True)
    prep_path = ensure_prepared_src(mono_src, tag)
    stamp = {"src": os.path.basename(mono_src),
             "mtime": round(os.path.getmtime(mono_src), 3),
             "size": os.path.getsize(mono_src),
             "tempo": TEMPO, "pad": pad, "n": len(cuts) - 1}
    if not force and os.path.exists(meta_p) and os.path.exists(merged):
        try:
            old = json.load(open(meta_p, encoding="utf-8"))
            if old == stamp:
                return time.time() - t0, False
        except Exception:                       # noqa
            pass

    n = len(cuts) - 1
    sr_out = 48000
    spans = [(cuts[k], cuts[k + 1]) for k in range(n)]
    # 每段目标输出采样数：理论值算精确后，把「整体算」和「分段累加」的余数补到末段
    frames = [int(round((b - a) * sr_out)) for a, b in spans]
    frames[-1] += int(round(sum(b - a for a, b in spans) * sr_out)) - sum(frames)

    base_chain = _stage_a_chain()

    def one(k):
        a, b = spans[k]
        ss = max(0.0, a - pad)
        # 段本身 (b-a)，再算上为了吸收滤镜延迟而多喂的 pad：首段没有前导，末段没有后继
        keep0 = 0.0 if k == 0 else pad          # atrim 起点：裁掉前一段垫进来的部分
        extra = pad * ((0 if k == 0 else 1) + (0 if k == n - 1 else 1))
        chain = base_chain + ",atrim=start=%.9f:end=%.9f,asetpts=N/SR/TB" \
                             % (keep0, keep0 + (b - a))
        out = os.path.join(base, "p%02d.wav" % k)
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-accurate_seek",
                        "-ss", "%.9f" % ss, "-t", "%.9f" % ((b - a) + extra),
                        "-i", prep_path, "-filter_complex", chain,
                        "-ac", "2", "-ar", str(sr_out), "-c:a", "pcm_s16le",
                        "-frames:a", str(frames[k]), "-y", out],
                       check=True, capture_output=True, text=True)
        return out

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(one, range(n)))

    lst = os.path.join(base, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for k in range(n):
            f.write("file '%s'\n" % os.path.join(base, "p%02d.wav" % k))
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", lst,
                    "-c:a", "pcm_s16le", merged], check=True, capture_output=True, text=True)
    json.dump(stamp, open(meta_p, "w", encoding="utf-8"))
    return time.time() - t0, True


def loud_cache_path(tag):
    return os.path.join(CACHE, "loud_%s.json" % tag)


def measure_loudnorm(path, tag, force=False):
    """loudnorm 第一遍：只测量，把结果存成 json。

    第二遍把这些数值喂给 loudnorm，它就跳过测量直接套用——这才是官方推荐的两遍流程。
    改声像参数不影响整体响度（2.5 秒 × 2 dB 的凹陷只占总时长 0.04%），
    所以调 dip / balance 时可以直接复用这份测量值，不必重新測。
    """
    p = loud_cache_path(tag)
    if not force and os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            if abs(d.get("size", -1) - os.path.getsize(path)) < 1024:
                return d
        except Exception:                       # noqa
            pass
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", path,
                        "-filter:a", "loudnorm=I=-18:TP=-2:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    txt = r.stderr
    i, j = txt.rfind("{"), txt.rfind("}")
    if i < 0 or j < 0:
        raise RuntimeError("loudnorm 测量失败：%s" % txt[-300:])
    info = json.loads(txt[i:j + 1])
    info["size"] = os.path.getsize(path)
    json.dump(info, open(p, "w", encoding="utf-8"))
    return info


def render_stage_b(pre_wav, out_mp3, ctl_path, tag, bitrate="256k", remeasure=False,
                   use_loudnorm=True):
    """套声像 + 响度归一 + 编码。改 pan/dip 时只跑这一段。

    用不用 `--fast-norm`：跳过 loudnorm 的第二遍，改用 `volume` 静态增益 + `alimiter`。
    实测 300 秒片段：渲染 8.19 s → 0.55 s（**快 15 倍**），但**整片加上 mp3 编码后只差几秒**
    （真实瓶颈是 1.2 GB 中间 wav 的读写 + lame 编码），而且静态版的 True Peak 保护是靠
    手动留余量换来的，不如 loudnorm 自带的 4 倍过采样 TP 限幅稳。**所以默认不上**。
    """
    t0 = time.time()
    info = measure_loudnorm(pre_wav, tag, force=remeasure)
    if use_loudnorm:
        norm = "loudnorm=I=-18:TP=-2:LRA=11" + (
            ":measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s"
            ":offset=%.3f:linear=true:print_format=summary"
            % (info["input_i"], info["input_tp"], info["input_lra"],
               info["input_thresh"], float(info.get("target_offset", 0.0))))
    else:
        gain = -18.0 - float(info["input_i"]) + float(info.get("target_offset", 0.0))
        gain = max(-12.0, min(12.0, gain))      # 失常时兜个底，别把整条片子推爆
        # alimiter 限的是**采样峰值**，而响度标准管的是 True Peak（4 倍过采样，通常高 1~2 dB）。
        # 目标 -2 dBTP，所以这里要压到 -3.5 dBFS 才够。实测全片 TP 落在 -2.2 dBTP。
        norm = ("volume=%.3fdB,"
                "alimiter=level_in=1:level_out=1:limit=-3.5dB:attack=7:release=60"
                % gain)
    af = (
        "channelsplit=channel_layout=stereo[cl][cr];"
        "[1:a]aresample=48000,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000,"
        "channelsplit=channel_layout=stereo[cL][cR];"
        "[cl][cL]amultiply[pl];"
        "[cr][cR]amultiply[pr];"
        "[pl][pr]amerge=inputs=2,%s" % norm
    )
    ff("-i", pre_wav, "-f", "f32le", "-ar", str(CTL_RATE), "-ac", "2", "-i", ctl_path,
       "-filter_complex", af,
       "-ac", "2", "-ar", "48000", "-c:a", "libmp3lame", "-b:a", bitrate, out_mp3)
    return time.time() - t0


def render_fast(mono_src, out_mp3, idxs, gap_raw, ctl_path=None, tag="asmr",
                workers=N_PIECES, force=False, remeasure=False, quiet=False,
                use_loudnorm=False):
    """分段并行的完整链路 = Stage A（可缓存、并行）+ Stage B（只跟声像有关）。

    单了一大坨：只有 stage A 需要跑重滤镜，而它与 PAN_* 参数无关，
    所以改 dip / balance 时它会被完全跳过。
    """
    ctl_path = ctl_path or os.path.join(CACHE, "pan_ctl.raw")
    durs = clip_durations(idxs)
    cuts = prepared_cuts(durs, idxs, gap_raw, workers if workers > 1 else 1)
    total = sum(durs[i] + gap_raw for i in idxs) / TEMPO
    build_pan_track(total, ctl_path)
    if cuts is None:
        raise ValueError("N_PIECES 必须 > 1 才能分段并行")
    dt_a, did = render_stage_a(mono_src, tag, cuts, workers=workers, force=force)
    _b, _meta, merged = stage_paths(tag)
    dt_b = render_stage_b(merged, out_mp3, ctl_path, tag, remeasure=remeasure,
                          use_loudnorm=use_loudnorm)
    if not quiet:
        print("Stage A（EQ/回声/分路，%d 段并行）：%s  %.0f s"
              % (workers, "重算" if did else "命中缓存（跳过）", dt_a))
        print("Stage B（声像 %s ±%.1f dB、中心下压 %.0f%% + 响度归一 + mp3）：%.0f s"
              % (PAN_BALANCE, 20 * math.log10(PAN_BALANCE / (1 - PAN_BALANCE)),
                 PAN_DIP * 100, dt_b))
    return dt_a + dt_b


# ------------------------------------------------------------------ 自检
def selftest():
    """无 Key 也能验证后处理链路：用 ffmpeg 合成 5 段测试音"""
    os.makedirs(CLIPS, exist_ok=True)
    for i in range(1, 6):
        p = os.path.join(CACHE, "st%04d.mp3" % i)
        ff("-f", "lavfi", "-i", "sine=f=%d:d=3:sample_rate=44100" % (220 + i * 40),
           "-c:a", "libmp3lame", "-b:a", "192k", p)
    silence = os.path.join(CACHE, "silence.mp3")
    make_silence(1.0, silence)
    lst = os.path.join(CACHE, "st_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for i in range(1, 6):
            f.write("file '%s'\n" % os.path.join(CACHE, "st%04d.mp3" % i))
            f.write("file '%s'\n" % silence)
    tmp = os.path.join(CACHE, "st_cat.mp3")
    ff("-f", "concat", "-safe", "0", "-i", lst, "-c:a", "copy", tmp)
    out = os.path.join(CACHE, "st_out.mp3")
    asmr_chain(tmp, out)
    r = subprocess.run([FFMPEG.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error",
                        "-show_entries", "stream=channels,sample_rate:format=duration",
                        "-of", "default=nw=1:nk=1", out],
                       capture_output=True, text=True)
    parts = r.stdout.split()
    print("自检输出：采样率=%s 声道=%s 时长=%.1fs" % (
        parts[0], parts[1], float(parts[2]) if len(parts) > 2 else -1))
    print("链路 OK（立体声）" if len(parts) > 1 and parts[1] == "2" else "链路异常")


# ------------------------------------------------------------------ main
def main():
    global CLIPS, STYLE_TAG, TEMPO, CHUNK_GAP, CHUNK_WORDS, CHUNK_XFADE, NO_SPLIT_WORDS
    global PAN_BALANCE, PAN_SWAP_SEC, PAN_DIP, PAN_DIP_SHAPE, LOUD_SPAN_SEC, LOUD_EXCESS_DB
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["voices", "sample", "all", "post", "selftest",
                                     "check"])
    ap.add_argument("--key", default=None)
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--gap", type=float, default=GAP_SEC)
    ap.add_argument("--workers", type=int, default=4)
    # 多版本共存：耳语版用 --tag "[whispers] " --clips clips_whisper --name whisper
    ap.add_argument("--tag", default=STYLE_TAG,
                    help='音频标签，如 "[whispers] " / "[soft-spoken] "')
    ap.add_argument("--clips", default=None,
                    help="clip 子目录名（相对 .cache），默认 clips")
    ap.add_argument("--name", default=None,
                    help="成品后缀名，默认 ICAO900_ASMR.mp3")
    ap.add_argument("--tempo", type=float, default=TEMPO)
    ap.add_argument("--chunk-gap", type=float, default=CHUNK_GAP,
                    help="分块拼接间隙（秒）；0 = 用交叉淡化过渡")
    ap.add_argument("--chunk-words", type=int, default=CHUNK_WORDS,
                    help="语义单元贪心打包的软预算（词）")
    ap.add_argument("--no-split-words", type=int, default=NO_SPLIT_WORDS,
                    help="整句词数 <= 此值时完全不切（连贯性最好）")
    ap.add_argument("--xfade", type=float, default=CHUNK_XFADE,
                    help="分块交叉淡化时长（秒）")
    ap.add_argument("--thresh", type=float, default=DRIFT_THRESH,
                    help="气声漂移阈值 dB，超过判定为后半句变本音（配合 --drift）")
    ap.add_argument("--refix", action="store_true",
                    help="check 模式下自动重录不合格句，仍超标的做降噪兜底（需要 --key）")
    ap.add_argument("--drift", action="store_true",
                    help="check 模式下额外跑一遍「首末段漂移」旧检查（更严，可选）")
    ap.add_argument("--scan-span", type=float, default=LOUD_SPAN_SEC,
                    help="判定「长段」的连续秒数门槛")
    ap.add_argument("--scan-excess", type=float, default=LOUD_EXCESS_DB,
                    help="判定「偏响」的超出 dB 门槛")
    ap.add_argument("--pan-balance", type=float, default=PAN_BALANCE,
                    help="极限声道配比 0.5~1.0；0.99 = 99:1 (±39.9 dB)")
    ap.add_argument("--pan-swap", type=float, default=PAN_SWAP_SEC,
                    help="左右换边耗时（秒）")
    ap.add_argument("--pan-dip", type=float, default=PAN_DIP,
                    help="居中时总音量下压比例 0~1（补偿双耳响度求和）；"
                         "文献推算合理区间 0.17~0.33，0.20=1.94 dB")
    ap.add_argument("--pan-dip-shape", type=float, default=PAN_DIP_SHAPE,
                    help="下压曲线锐度，1=余弦钟形（推荐），>1 更尖")
    ap.add_argument("--pieces", type=int, default=N_PIECES,
                    help="Stage A 并行段数；1 = 退回旧的单进程整条链路")
    ap.add_argument("--force-stage-a", action="store_true",
                    help="无视 Stage A 缓存强制重算（改了 EQ/回声/变速才需要）")
    ap.add_argument("--remeasure", action="store_true",
                    help="强制重跑 loudnorm 测量（默认直接复用缓存的实测值）")
    ap.add_argument("--fast-norm", action="store_true",
                    help="Stage B 用静态增益代替 loudnorm 第二遍（详见 render_stage_b 的说明）")
    ap.add_argument("--auto-check", action="store_true",
                    help="all 模式合成完后自动跑一遍质检（有不合格句会列出并提示补录命令）")
    args = ap.parse_args()

    if args.tag:
        STYLE_TAG = args.tag
    if args.tempo:
        TEMPO = args.tempo
    CHUNK_GAP = args.chunk_gap
    CHUNK_WORDS = args.chunk_words
    CHUNK_XFADE = args.xfade
    NO_SPLIT_WORDS = args.no_split_words
    PAN_BALANCE = args.pan_balance
    PAN_SWAP_SEC = args.pan_swap
    PAN_DIP = args.pan_dip
    PAN_DIP_SHAPE = args.pan_dip_shape
    LOUD_SPAN_SEC = args.scan_span
    LOUD_EXCESS_DB = args.scan_excess
    if args.clips:
        CLIPS = args.clips if os.path.isabs(args.clips) else os.path.join(CACHE, args.clips)
    ensure_dirs()
    suffix = args.name or "ASMR"
    out_name = "ICAO900_%s.mp3" % suffix
    idx_name = args.name and ("05_timestamps_%s.txt" % suffix) or "04_timestamps.txt"

    print("风格标签=%r  clip目录=%s  成品=%s  tempo=%g"
          % (STYLE_TAG, os.path.basename(CLIPS), out_name, TEMPO))
    print("分块：语义感知（≤%d 词整句不切 / 数字串·呼号·跑道号不拆），"
          "过渡=%s"
          % (NO_SPLIT_WORDS,
             ("%gs 交叉淡化" % CHUNK_XFADE) if CHUNK_GAP <= 0 else ("%gs 间隙" % CHUNK_GAP)))

    if args.mode == "selftest":
        selftest()
        return

    if args.mode == "voices":
        k = api_key(args)
        v = http_json("https://api.elevenlabs.io/v1/voices", k)
        for it in v.get("voices", []):
            lab = it.get("labels") or {}
            print("%-28s %s  [%s/%s]" % (it["voice_id"], it["name"],
                                         lab.get("accent", "?"), lab.get("gender", "?")))
        return

    src = [l.rstrip("\n") for l in open(TXT, encoding="utf-8") if l.strip()]
    idxs = SAMPLE_IDX if args.mode == "sample" else list(range(1, len(src) + 1))
    fail = []                     # post 模式不会经过合成分支，这里先兜个底

    if args.mode == "check":
        missing, profs = scan_pass(idxs, workers=args.workers)
        ref = batch_ref(profs) if profs else 0.0
        hits = find_hits(profs, ref)
        print("实际检测 %d 句（缺 clip %d 句）　全批中位响度 %.1f dB"
              % (len(profs), len(missing), ref))
        print("门槛：HNR > %+.1f dB（正常发声的绝对区）+ 音量高出 ≥%.1f dB + 成片 ≥%gs"
              % (LOUD_HNR_ABS, LOUD_EXCESS_DB, LOUD_SPAN_SEC))
        print("命中 %d 句" % len(hits))
        for i, r in hits[:40]:
            print("  第 %4d 行  %-6s 成片 %4.1fs  超出 +%.1f dB │ %s"
                  % (i, r["why"], r["span"], r["excess"], src[i - 1][:56]))
        if args.drift:
            _m2, bad2 = check_and_refix(idxs, thresh=args.thresh)
            print("\n附带首末段漂移检查（≥%g dB）：%d 句" % (args.thresh, len(bad2)))
            for i, d in sorted(bad2, key=lambda x: -x[1])[:20]:
                print("  第 %4d 行  %+.1f dB │ %s" % (i, d, src[i - 1][:58]))
            have = set(i for i, _ in hits)
            for i, d in bad2:
                if i not in have:
                    hits.append((i, {"span": 0.0, "excess": d, "peak": d,
                                     "why": "漂移", "win": 0}))
            hits.sort(key=lambda kv: -kv[1]["excess"])
            print("合并后共 %d 句待返工" % len(hits))
        if hits and args.refix:
            k = api_key(args)
            print("\n[1/2] 按 ≤%d 词重新切块并重录 %d 句…" % (FINE_WORDS, len(hits)))
            res = refix_sentences([(i, r["excess"]) for i, r in hits], src,
                                  k, args.voice)
            fails = [i for i, _d0, d1, info in res if d1 is None]
            if fails:
                print("  合成失败 %d 句：%s" % (len(fails), fails[:20]))
            print("\n[2/2] 用同一把尺子复检，仍超标的做增益压制兜底（纯本地，零额度）…")
            for i, _r in hits:                # 重录后 profile 要重算
                profs[i] = clip_profile(os.path.join(CLIPS, "%04d.mp3" % i))
            again = find_hits(profs, ref)
            again = [(i, r) for i, r in again
                     if i in set(j for j, _ in hits)]
            cut = []
            for i, r in again:
                d = duck_clip(os.path.join(CLIPS, "%04d.mp3" % i),
                              os.path.join(duck_dir(), "%04d.mp3" % i),
                              extra_db=r.get("extra", 0.0))
                cut.append((i, r["excess"], d, r["why"]))
            print("  其中 %d 句复检仍超标 → 已压制并存入 %s"
                  % (len(cut), os.path.basename(duck_dir())))
            for i, e1, d, why in cut[:20]:
                print("    第 %4d 行  %-6s 超出 +%.1f dB → 压制 %.1f dB │ %s"
                      % (i, why, e1, d, src[i - 1][:46]))
            n_ok = len(hits) - len(cut) - len(fails)
            print("\n返工总结：重录后已合格 %d 句 / 压制兜底 %d 句 / 合成失败 %d 句"
                  % (n_ok, len(cut), len(fails)))
            print("\n整合时会自动套用这些压制结果：post --clips %s --xfade %g --name %s"
                  % (os.path.basename(CLIPS), CHUNK_XFADE, suffix))
        elif hits:
            print("\n返工命令：check --refix --key <KEY> --clips %s --tag %r"
                  % (os.path.basename(CLIPS), args.tag))
        return

    if args.mode in ("sample", "all"):
        k = api_key(args)
        print("合成 %d 句  voice=%s  model=%s" % (len(idxs), args.voice, MODEL_ID))
        ok, fail = run_batch(idxs, src, k, args.voice, args.workers)
        print("完成：成功 %d / %d" % (ok, len(idxs)))
    # 交叉淡化是纯后处理：素材取自 *_parts 存档，改 --xfade 重跑即可，不消耗额度
    reb, has_parts = rebuild_clips(CHUNK_XFADE, CHUNK_GAP)
    if has_parts:
        print("交叉淡化：重做了 %d 个多块句，xfade=%gs gap=%gs（改参数无需重新合成）"
              % (reb, CHUNK_XFADE, CHUNK_GAP))
    nfix = apply_fixes()
    if nfix:
        print("套用降噪兜底：%d 句使用了压制后的版本（来自 %s）"
              % (nfix, os.path.basename(duck_dir())))

    if args.mode == "sample":
        out = os.path.join(AUDIO, "sample_%s.mp3" % suffix)
        # 插入的静音先按 tempo 放大，变速后正好回落成 args.gap
        concat_clips(idxs, os.path.join(CACHE, "sample_cat.mp3"), args.gap * TEMPO)
        asmr_chain(os.path.join(CACHE, "sample_cat.mp3"), out)
        print("样音：", out)
        return
    if fail:
        print("有失败句，先重跑补漏；或直接 post 用现有 clip 拼接")

    if args.mode in ("all", "post"):
        if args.mode == "all" and args.auto_check:
            missing, profs = scan_pass(idxs, workers=args.workers)
            ref = batch_ref(profs) if profs else 0.0
            bad = find_hits(profs, ref)
            if bad:
                print("\n⚠️ 自动质检：%d 句疑似「长段非气声 + 音量偏大」" % len(bad))
                for i, r in bad[:20]:
                    print("  第 %d 行 %s +%.1f dB │ %s"
                          % (i, r["why"], r["excess"], src[i - 1][:54]))
                print("  返工：check --refix --key <KEY> --clips %s --tag %r"
                      % (os.path.basename(CLIPS), args.tag))
            else:
                print("自动质检：%d 句全部过关 ✓（判据 HNR>%+.1f dB 且音量高出 ≥%.1f dB 且成片 ≥%gs）"
                      % (len(profs) - len(missing), LOUD_HNR_ABS,
                         LOUD_EXCESS_DB, LOUD_SPAN_SEC))
        cat = os.path.join(CACHE, "full_cat_%s.mp3" % suffix)
        concat_clips(list(range(1, len(src) + 1)), cat, args.gap * TEMPO)
        out = os.path.join(AUDIO, out_name)
        if args.pieces > 1:
            render_fast(cat, out, list(range(1, len(src) + 1)), args.gap * TEMPO,
                        tag=suffix, workers=args.pieces, force=args.force_stage_a,
                        remeasure=args.remeasure, use_loudnorm=not args.fast_norm)
        else:
            asmr_chain(cat, out)
        total = write_index(list(range(1, len(src) + 1)), args.gap,
                            os.path.join(ROOT, idx_name), tempo=TEMPO)
        print("成品：%s   总时长约 %.0f 分钟" % (out, total / 60))


if __name__ == "__main__":
    main()
