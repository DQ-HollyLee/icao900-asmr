# -*- coding: utf-8 -*-
"""
ICAO 900 句 -> 适合 TTS 合成 ASMR 音频的英文文本

处理阶段：
  stage1 去行首序号、修 PDF 抽取粘词
  stage2 ICAO 无线电通话发音规范化（数字逐位、字母/缩写、型号、单位）
输出：
  01_sentences_clean.txt   纯英文、去序号、修好粘连
  02_tts_icao.txt          ICAO 发音规范化，直接喂给 TTS
  03_review_diff.md        逐句对照 + 可疑 token 报告，便于人工抽查
"""
import re
import os
import sys
import collections

SRC = r"E:\BaiduNetdiskDownload\PCPEP900.txt"
OUT = r"E:\Program Files\WorkBuddyProjects\icao900-asmr"

# ---------------------------------------------------------------- 基础工具
# 数字 8：ICAO 标准拼法写作 AIT（押 eight 的韵）。
# 但 eleven_v3 遇到 "ait" 这个非词形状不稳定，部分片段会念成 "A I T" 三个字母。
# 想换写法只改这一个常量；读音对照探针见 scripts/eight_probe.py。
#   候选： "eight"（100% 读 [eɪt]，但与 ICAO 拼写不同）
#          "ate"   （同为 [eɪt]）
#          "ait"   （ICAO 官方拼写，有被读成字母的风险）
EIGHT = "eight"

DIGIT = {"0": "zero", "1": "one", "2": "two", "3": "tree", "4": "four",
         "5": "fife", "6": "six", "7": "seven", "8": EIGHT, "9": "niner"}

PHONETIC = {
    "A": "Alfa", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo",
    "F": "Foxtrot", "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliett",
    "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November", "O": "Oscar",
    "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango",
    "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "X-ray", "Y": "Yankee",
    "Z": "Zulu",
}

BOX = []


def box(val):
    """把已处理好的片段装箱，避免后续规则二次命中"""
    BOX.append(val)
    return "\x01%d\x01" % (len(BOX) - 1)


def unbox(text):
    def rep(m):
        return BOX[int(m.group(1))]
    for _ in range(5):
        text = re.sub(r"\x01(\d+)\x01", rep, text)
    return text


def digits(s):
    """逐位读出：310 -> tree one zero"""
    return " ".join(DIGIT[c] for c in s)


# ---------------------------------------------------------------- stage 1：清洗
MANUAL_GLUE = {
    "initialaltitude": "initial altitude",
    "Initialaltitude": "Initial altitude",
    "Cruisinglevel": "Cruising level",
    "cruisinglevel": "cruising level",
    "outboundtime": "outbound time",
    "outbounddistance": "outbound distance",
    "ourdescent": "our descent",
    "otherairplanes": "other airplanes",
    "Departurefrequency": "Departure frequency",
    "departurefrequency": "departure frequency",
    "climbto": "climb to",
    "descendto": "descend to",
    "climbTo": "climb to",
    "Runway15": "Runway 15",
    "Gate15": "Gate 15",
    "Bay24": "Bay 24",
    "bay15": "bay 15",
    "stand15": "stand 15",
    "on121.5": "on 121.5",
}

GLUE_RE = [
    (r"(?<=[,\);:])(?=[A-Za-z])", " "),   # published,expect  staff,standby
    (r"(?<=[a-z])(?=[A-Z][a-z])", " "),   # maneuver.Request
    (r"(?<=\.)(?=[A-Z])", " "),           # flight.Request  route.Request（丢句号空格）
    (r"(?<=\d)(?=[A-Za-z])", " "),        # 10,000feet  5hours  5000feet  15NM
]


def strip_index(line):
    return re.sub(r"^\s*\d{1,4}\.\s*", "", line).strip()


def stage1(line):
    for rx, rpl in GLUE_RE:
        line = re.sub(rx, rpl, line)
    for k, v in MANUAL_GLUE.items():
        line = line.replace(k, v)
    line = re.sub(r"(\d)\s*,\s*(\d)", r"\1,\2", line)      # 14, 000 -> 14,000
    # 粘词修复会误伤的设计符：把被拆开的跑道号、离场代号拼回去
    line = re.sub(r"\b([Rr]unway) (\d{1,2}) ([LRCT])\b", r"\1 \2\3", line)
    line = re.sub(r"\b([A-Z]{2,5})-(\d{1,2}) ([A-Z])\b", r"\1-\2\3", line)
    line = re.sub(r"\b(QNH|QFE)(\d{3,4})\b", r"\1 \2", line)
    line = re.sub(r"\s{2,}", " ", line)
    line = line.replace("\u3000", " ")
    return line.strip()


# ---------------------------------------------------------------- stage 2：ICAO 发音
# 缩略语：改成 TTS 一定读得对的写法
ACRONYM = [
    # (匹配串, 替换串)  —— 一律改写成 TTS 100% 不会读错的写法
    (r"\bADS-B\b", "A D S B"),
    (r"\bADS-B", "A D S B"),
    (r"\bCPDLC\b", "C P D L C"),
    (r"\bTCAS\b", "TEE-cas"),
    (r"\bRAIM\b", "raym"),
    (r"\bSELCAL\b", "Selcal"),
    (r"\bETOPS\b", "E TOPS"),
    (r"\bGPWS\b", "G P W S"),
    (r"\bPAPI\b", "P A P I"),
    # R Nav：RNAV 在陆空通话里读 "are-nav"，不是逐字母
    (r"\bRNAV\b", "R Nav"),
    # 导航设施 / 机载设备缩写：一律逐字母，避免被读成单词（ILS->ills, VOR->vor）
    (r"\bVOR\b", "V O R"),
    (r"\bDME\b", "D M E"),
    (r"\bNDB\b", "N D B"),
    (r"\bILS\b", "I L S"),
    (r"\bAPU\b", "A P U"),
    (r"\bEGT\b", "E G T"),
    (r"\bFMS\b", "F M S"),
    (r"\bCDU\b", "C D U"),
    (r"\bATC\b", "A T C"),
    (r"\bVHF\b", "V H F"),
    (r"\bHF\b", "H F"),
    (r"\bGPS\b", "G P S"),
    (r"\bELT\b", "E L T"),
    (r"\bRA\b", "R A"),          # TCAS RA（决断咨询）
    (r"\bSID\b", "S I D"),         # 标准仪表离场：逐字母读，不读成 sid
    (r"\bFOD\b", "F O D"),         # Foreign Object Debris：逐字母
    (r"\bSTAR\b", "S T A R"),
    (r"\bCODE\b", "code"),       # Selcal code EFFG
    (r"\bNOT\b", "not"),
    (r"\bLDA\b", "L D A"),
    (r"\bGNSS\b", "G N S S"),
    (r"\bRVR\b", "R V R"),
    (r"\bVMC\b", "V M C"),
    (r"\bIMC\b", "I M C"),
    (r"\bRVSM\b", "R V S M"),
    (r"\bRNP\b", "R N P"),
    (r"\bMEA\b", "M E A"),
    (r"\bMOCA\b", "M O C A"),
    (r"\bETA\b", "E T A"),
    (r"\bTORA\b", "T O R A"),
    (r"\bASDA\b", "A S D A"),
    (r"\bTODA\b", "T O D A"),
    (r"\bCPR\b", "C P R"),
    (r"\bTOGA\b", "TOE-gah"),
    (r"\bNM\b", "nautical miles"),
    (r"\bft\b", "feet"),
    (r"\bFT\b", "feet"),
    (r"\bkts\b", "knots"),
    (r"\bkt\b", "knots"),
    (r"\bAC BUS\b", "A C bus"),
    (r"\bDC BUS\b", "D C bus"),
    (r"\bAC bus\b", "A C bus"),
    (r"\bDC bus\b", "D C bus"),
]

# 航空器型号写法 -> 口语读音
AIRCRAFT = [
    (r"\bAirbus\s?320\b", "Airbus three twenty"),
    (r"\b[Aa]irbus\s?320\b", "Airbus three twenty"),
    (r"\bAirbus\s?330\b", "Airbus three thirty"),
    (r"\b[Aa]irbus\s?330\b", "Airbus three thirty"),
    (r"\bAirbus\s?340\b", "Airbus three forty"),
    (r"\bBoeing\s?747\b", "Boeing seven forty seven"),
    (r"\bB747\b", "Boeing seven forty seven"),
    (r"\bBoeing\s?737\b", "Boeing seven thirty seven"),
    (r"\bB737\b", "Boeing seven thirty seven"),
    (r"\bBoeing\s?777\b", "Boeing seven seventy seven"),
    (r"\bB777\b", "Boeing seven seventy seven"),
]

# ---------------------------------------------------------------- 航路点 / 程序代号
# ICAO 规则：
#   5 字母命名航路点（5LNC）  -> 按单词读      DAPRO -> "Dapro"
#   1~4 字母定位点 / 航路点   -> 逐个拼读字母   WXJ   -> "Whiskey X-ray Juliett"
# 程序代号（离场/进场）沿用同一规则：
#   BK-02 RNAV  -> "Bravo Kilo zero two R Nav"
#   KODAP-01    -> "Kodap zero one"
WAYPOINT_5LNC = ["DAPRO", "KODAP", "JEMMY", "OBLIK", "FUPAD"]
WAYPOINT_SPELL = [
    # 三字母
    "BKM", "AMS", "CGO", "HRB", "HUR", "JFK", "JMU", "LHR", "LLK", "LMN",
    "LKO", "MLT", "MQR", "NLD", "PER", "PLT", "POU", "SHA", "WHA", "WUH",
    "WXA", "WXI", "WXJ", "ZAM", "ZHO",
    # 两字母
    "AK", "AU", "BK", "CK", "DA", "DG", "IP", "JO", "LN", "LV", "LX", "ML", "ST",
    "SY", "TB", "YU", "YV", "ZF", "HZ",
    # 四字母（SELCAL 代码）
    "EFFG",
]

STATS = collections.Counter()


def sub_count(name, rx, rpl, text):
    n = len(re.findall(rx, text))
    if n:
        STATS[name] += n
    return re.sub(rx, rpl, text)


THOUSAND = "tousand"      # 不要写成 tou-sand：连字符会让 TTS 把音拖长


def altitude_words(n):
    """ICAO 2.8.1.2：高度 / 云高 / 能见度 / RVR
    整千、整百用 THOUSAND(TOU-SAND)、HUNDRED，其余部分仍逐位。
      3000  -> tree tou-sand
      10500 -> one zero tou-sand fife hundred
      2700  -> two tou-sand seven hundred
      350   -> tree hundred fife zero
      196   -> one niner six
    """
    if n < 100:
        return digits(str(n))
    th, rem = divmod(n, 1000)
    hu, rest = divmod(rem, 100)
    out = []
    if th:
        out.append("%s %s" % (digits(str(th)), THOUSAND))
    if hu:
        out.append("%s hundred" % DIGIT[str(hu)])
    if rest:
        out.append(digits("%02d" % rest))
    return " ".join(out)


def apply_rules(text):
    # ---- 0) 高度 / 能见度：按「千 / 百」读（必须最先做，且结果里不再含数字）
    def alt_phrase(m):
        return "%s %s" % (altitude_words(int(m.group(1).replace(",", ""))), m.group(2))
    # 高度 / 升降率：一律千、百读法
    text = sub_count("altitude", r"\b(\d[\d,]*)\s+(feet|ft)\b", alt_phrase, text)
    # 能见度 / RVR：同样规则；但 "跑道宽度 30 meters" 是长度，不在此列
    if re.search(r"\bRVR\b|visibility", text):
        text = sub_count("visibility", r"\b(\d[\d,]*)\s+(meters|metres)\b",
                         alt_phrase, text)

    # ---- 1) 教科书注释（(North)/(East)/(ten-ninety) 等）去掉
    text = re.sub(r"\s*\((?:North|South|East|West|north|south|east|west|"
                  r"ten-ninety)\)\s*", " ", text)

    # ---- 2) 类别等级 CAT II / CAT IIIB / CAT IIIC
    text = sub_count("CAT", r"\bCAT\s+(I{1,3}[BC]?)\b",
                     lambda m: {"I": "Category one", "II": "Category two",
                                "IIIB": "Category three Bravo",
                                "IIIC": "Category three Charlie",
                                "IIIA": "Category three Alfa"}.get(
                         m.group(1), "Category " + m.group(1)),
                     text)

    # ---- 3) 机型
    for rx, rpl in AIRCRAFT:
        text = sub_count("aircraft", rx, rpl, text)

    # ---- 4) 马赫数：Mach decimal 76 -> seven six（统一 point -> decimal）
    text = sub_count("mach-word", r"\b(Mach|mach)( number)? point\b",
                     lambda m: "%s decimal" % m.group(1), text)
    text = sub_count("mach", r"\b([Mm]ach)( number)? decimal\s+(\d{2})\b",
                     lambda m: "%s decimal %s" % (m.group(1), digits(m.group(3))), text)

    # ---- 5) 频率 1xx.xxx  -> one one eight decimal niner
    def freq(m):
        whole, frac = m.group(1), m.group(2)
        return "%s decimal %s" % (digits(whole), digits(frac))
    text = sub_count("freq", r"\b(1\d{2})\.(\d{1,3})\b", freq, text)

    # ---- 6) 气压设定 QNH/QFE/Altimeter(+setting)
    def alt_setting(m):
        val = m.group(3)
        if "." in val:
            w, f = val.split(".")
            spoken = "%s decimal %s" % (digits(w), digits(f))
        else:
            spoken = digits(val)
        return "%s%s %s" % (m.group(1), m.group(2) or "", spoken)
    text = sub_count("alt-setting",
                     r"\b(QNH|QFE|Altimeter|altimeter)( setting)?\s+([\d.]+)\b",
                     alt_setting, text)

    # ---- 6) 高度层 FLxxx
    text = sub_count("flightlevel", r"\bFL\s?(\d{2,3})\b",
                     lambda m: "Flight Level %s" % digits(m.group(1)), text)

    # ---- 7) 跑道号 Runway 36R -> Runway tree six right
    side = {"L": "left", "R": "right", "C": "center", "T": "tango"}
    def runway(m):
        num, sfx = m.group(1), m.group(2)
        tail = side.get(sfx.upper(), "") if sfx else ""
        out = "Runway %s" % digits(num)
        if tail:
            out += " " + tail
        return out
    text = sub_count("runway", r"\b[Rr]unway\s+(\d{1,2})([LRCT]?)\b", runway, text)

    # ---- 9) 巡航高度层（不带 FL 前缀的写法也要逐位）
    text = sub_count("cruise-level", r"\b([Cc]ruising level)\s+(\d{2,3})\b",
                     lambda m: "%s %s" % (m.group(1), digits(m.group(2))), text)

    # ---- 10) 应答机 / 编码 / 四位时间 / HF 频率：全部逐位
    text = sub_count("squawk", r"\b([Ss]quawk(?:ing)?(?:\s+code)?|code)\s+(\d{4,5})\b",
                     lambda m: "%s %s" % (m.group(1), digits(m.group(2))), text)
    text = sub_count("other-4digit", r"\b(\d{4,5})\b", lambda m: digits(m.group(1)), text)

    # ---- 9) 航向 / 航迹 / 径向线：逐位
    for key in (r"heading", r"Heading", r"track", r"Track", r"radial", r"bearing"):
        text = sub_count("bearing", r"\b%s\s+(?:of\s+)?(\d{2,3})\b" % key,
                         lambda m, k=key: "%s %s" % (k, digits(m.group(1))), text)
    text = sub_count("bearing-2", r"\b(\d{3})\s+radial\b",
                     lambda m: "%s radial" % digits(m.group(1)), text)
    # 航向更正：Heading one two zero, correction, 140
    text = sub_count("bearing-3", r"(?i)\bcorrection,?\s+(\d{2,3})\b",
                     lambda m: "correction, %s" % digits(m.group(1)), text)

    # ---- 12) 报告点/位置 坐标  42N 165E
    def coord(m):
        n, c = m.group(1), m.group(2)
        return "%s %s" % (digits(n), {"N": "North", "S": "South",
                                      "E": "East", "W": "West"}[c.upper()])
    text = sub_count("coord", r"\b(\d{2,3})\s?([NSEW])\b", coord, text)

    # ---- 13) 时间（时/分）语境：一律逐位
    UNIT_AHEAD = r"(?![\s,]*(?:DME|NM|miles|minute|minutes|feet|foot|knots|meters|" \
                 r"metres|degrees|hours|hour|kilograms|radial|o'clock|nautical))"
    TIME_CTX = [
        r"\bat time\s+(\d{2})\b",
        r"\btime (?:at|is|of)\s+(\d{2})\b",
        r"\bcross(?:ing)?\s+[A-Za-z]+ at\s+(\d{2})\b",
        r"\blevel at\s+(\d{2})\b",
        r"\bby\s+(\d{2})(?=[\s.,])",
        r"\bat\s+(\d{2})\s+(?:or later|or earlier|or before|or after)\b",
        r"\bat or (?:before|after|later|earlier)\s+(\d{2})\b",
        r"(?i)\b(?:start(?: |-)?up|departure|pushback|startup)\s+at\s+(\d{2})\b",
        r"\b[Ee]xpect(?:ed)?\s+(?:[Ff]urther\s+|[Aa]pproach\s+)?[Cc]learance at\s+(\d{2})\b",
        r"\b[Aa]pproach time\s+(\d{2})\b",
        r"\b[Ss]lot time at\s+(\d{2})\b",
        r"\b(?:VOR|NDB|DME)\s+at\s+(\d{2})\b",
        r"\b[A-Z]{2,5}\s+at\s+(\d{2})\b" + UNIT_AHEAD,
        r"\b[A-Z]{2,5}\s+(\d{2})\b" + UNIT_AHEAD,
    ]
    def read_time(m):
        return re.sub(r"\d{2}", lambda x: digits(x.group(0)), m.group(0))
    for rx in TIME_CTX:
        text = sub_count("time", rx, read_time, text)

    # ---- 15) 航路/离场代号 字母+数字 -> 字母+逐位数字
    def hyphen_desig(m):
        tail = (" " + PHONETIC.get(m.group(3), m.group(3))) if m.group(3) else ""
        return "%s %s%s" % (m.group(1), digits(m.group(2)), tail)
    text = sub_count("sid-star", r"\b([A-Z]{1,5})-(\d{1,2})([A-Z])?\b", hyphen_desig, text)
    def air_desig(m):
        return "%s %s" % (PHONETIC.get(m.group(1), m.group(1)), digits(m.group(2)))
    text = sub_count("airway", r"\b([A-Z])(\d{1,3})\b", air_desig, text)

    # ---- 15b) 前导零数字 03 -> zero tree（须在代号之后，避免打断 LMN-02）
    text = sub_count("leading-zero", r"\b0(\d)\b", lambda m: "zero " + DIGIT[m.group(1)], text)

    # ---- 16) 钟点方位 XX o'clock -> two o'clock
    CLOCK = {str(i): w for i, w in zip(range(1, 13), [
        "one", "two", "tree", "four", "fife", "six", "seven", EIGHT, "niner",
        "ten", "eleven", "twelve"])}
    text = sub_count("clock", r"\b(\d{1,2}) o'clock\b",
                     lambda m: "%s o'clock" % CLOCK.get(m.group(1), m.group(1)), text)

    # ---- 17) 缩略语 / 单位
    for rx, rpl in ACRONYM:
        text = sub_count("acronym", rx, rpl, text)

    # ---- 18) 航路点 / 程序代号（放在最后，避免干扰前面的数字规则）
    text = apply_identifiers(text)

    return text


# ---------------------------------------------------------------- 代号读音
IDENT_CTX = [
    # 单字母：只在明确的航空语境里才拼读，避免误伤 "I" 等人称代词
    (r"\bW(?=\s+(?:V O R|N D B|D M E|VOR|NDB|DME)\b)", "Whiskey"),
    (r"(?i)\b(information)\s+([A-Z])\b",
     lambda m: "%s %s" % (m.group(1), PHONETIC.get(m.group(2), m.group(2)))),
    (r"(?i)\b(taxiway)\s+([A-Z])\b",
     lambda m: "%s %s" % (m.group(1), PHONETIC.get(m.group(2), m.group(2)))),
    (r"(?i)\b(holding point)\s+([A-Z])\b",
     lambda m: "%s %s" % (m.group(1), PHONETIC.get(m.group(2), m.group(2)))),
    (r"(?i)\b(stand|gate|bay)\s+([A-Z])\b",
     lambda m: "%s %s" % (m.group(1), PHONETIC.get(m.group(2), m.group(2)))),
]


def apply_identifiers(text):
    # 连写代号 BK02 -> BK zero two（随后 BK 再拼读成 Bravo Kilo）
    text = sub_count("desig-tight", r"\b([A-Z]{2,5})(\d{2})\b",
                     lambda m: "%s %s" % (m.group(1), digits(m.group(2))), text)

    # 单字母语境（ATIS 代码、滑行道、等待点、单字母航路点）
    for rx, rpl in IDENT_CTX:
        text = sub_count("ident-1letter", rx, rpl, text)

    # 5 字母命名航路点：按单词读（首字母大写，其余小写）
    for w in WAYPOINT_5LNC:
        text = sub_count("waypoint-5lnc", r"\b%s\b" % w, w.capitalize(), text)

    # 1~4 字母：逐个拼读 ICAO 字母表（先长后短，避免子串误伤）
    for w in sorted(WAYPOINT_SPELL, key=len, reverse=True):
        spoken = " ".join(PHONETIC[c] for c in w)
        text = sub_count("waypoint-spell", r"\b%s\b" % w, spoken, text)

    return text


def normalize(line):
    t = apply_rules(line)
    t = unbox(t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    if t and t[-1] not in ".!?":
        t += "."
    return t.strip()


# ---------------------------------------------------------------- 可疑 token 检查
def build_lexicon():
    try:
        from english_words import get_english_words_set
        base = get_english_words_set(["web2"], lower=True, alpha=True)
    except Exception:
        base = set()
    extra = """airplanes aircraft approach clearance approach touchdown climb descent
    squawk squawking holding outbound initial cruising level maintaining frequency
    departure vector vectors reporting procedures transmissionorporation radar ident
    transponder captain controller emergency evacuation passengers oxygen pressure
    hydraulic avionics ventilation equipment procedure""".split()
    base |= set(extra)
    return base


def check_words(texts, lex):
    bad = collections.Counter()
    for t in texts:
        for tok in re.findall(r"[A-Za-z][A-Za-z'-]*", t):
            low = tok.lower()
            if low in lex:
                continue
            core = low
            for suf in ("s", "es", "ed", "d", "ing", "ly", "s's"):
                if low.endswith(suf) and len(low) > len(suf) + 2:
                    core = low[: -len(suf)]
                    break
            if core in lex or core + "e" in lex:
                continue
            bad[tok] += 1
    return bad


# ---------------------------------------------------------------- main
def main():
    with open(SRC, "rb") as f:
        raw = f.read().decode("gb18030", errors="replace").replace("\uFFFD", "?")
    # 全角标点 -> 半角
    raw = raw.translate(str.maketrans(
        "\uff1f\uff0c\u3001\u3002\uff1b\uff1a\uff01\uff08\uff09\u201c\u201d\u2018\u2019\uff0d",
        "?,,.;:!()\"\"''-"))

    lines = raw.splitlines()
    clean, tts, pairs = [], [], []
    for ln in lines:
        if not ln.strip():
            continue
        c = stage1(strip_index(ln))
        if not c:
            continue
        clean.append(c)
        tts.append(normalize(c))
        pairs.append((c, tts[-1]))

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "01_sentences_clean.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(clean) + "\n")
    with open(os.path.join(OUT, "02_tts_icao.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(tts) + "\n")

    # 报告
    changed = [(i, c, t) for i, (c, t) in enumerate(pairs, 1) if c != t]
    rep = ["# ICAO 900 句 规范化核查报告\n",
           "- 输入句数：%d，其中被改写：%d 句（%.0f%%）"
           % (len(clean), len(changed), 100.0 * len(changed) / len(clean)),
           "- 规则命中统计：" + "、".join("%s %d" % (k, v) for k, v in STATS.most_common()),
           "- 全量逐句对照见 `.cache/pair_diff.txt`\n",
           "## 改动样例（每类各取数条）\n"]
    seen = collections.Counter()
    for i, c, t in changed:
        key = "".join(re.findall(r"[a-z]+", t))[:24]
        seen[key] += 1
        if seen[key] == 1:
            rep.append("**第 %d 句**\n" % i)
            rep.append("- 清洗后：`%s`" % c)
            rep.append("- TTS 稿：`%s`\n" % t)
        if len(rep) > 300:
            break
    rep.append("## 仍以自然数朗读的残留数字（属正常）\n")
    nums = collections.Counter()
    for t in tts:
        for m in re.findall(r"\b\d[\d.,]*\b", t):
            nums[m] += 1
    rep.append(" ".join("`%s`×%d" % (k, v) for k, v in nums.most_common()))
    rep.append("\n> 这些是距离/速度/时长/高度/重量等，ICAO 本就按自然数朗读，无需逐位。")
    with open(os.path.join(OUT, "03_review_diff.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")
    # 对照
    with open(os.path.join(OUT, ".cache", "pair_diff.txt"), "w", encoding="utf-8") as f:
        for i, (c, t) in enumerate(pairs, 1):
            f.write("%d\nCLEAN: %s\nTTS  : %s\n\n" % (i, c, t))
    print("sentences:", len(clean))
    print("rules:", dict(STATS))


if __name__ == "__main__":
    main()
