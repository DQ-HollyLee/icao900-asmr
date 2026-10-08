# ICAO 900 句 → ASMR 磨耳朵音频

把民航学员 / 飞行员用来背记的 **ICAO 900 句陆空通话** 转成 **清晰、温柔、双声道的英文 ASMR 音频**，用于睡前磨耳朵。

## 目录约定

```
icao900-asmr/
├── PROJECT.md                  本文件：规范、进度、待办
├── docs/
│   └── TASK_ARCHIVE.md         ★ 完整技术档案（面向研究报告/论文撰写）
├── 01_sentences_clean.txt      清洗后纯英文（去序号、修粘词），900 行    ← 交付
├── 02_tts_icao.txt             ICAO 发音规范化后的 TTS 输入脚本，900 行   ← 交付
├── 03_review_diff.md           规范化核查报告（规则命中、可疑 token）
├── scripts/
│   ├── normalize.py            文本清洗 + ICAO 发音规范化（唯一数据源脚本）
│   └── tts_generate.py         逐句调云端 TTS + 拼接 + 双声道 ASMR 后处理
├── audio/                      最终音频（.mp3 / .flac）
└── .cache/                     中间产物：逐句 clip、ffmpeg 二进制等，非交付物
```

> 规则：最终交付物只在根目录 `audio/`；所有中间文件一律进 `.cache/`。

## 文本处理规范

### stage 1：清洗（去噪）
1. **编码**：源文件是 **GB18030**（不是 UTF-8），含 1 个全角问号，需先转半角标点。
2. **去序号**：行首 `^\s*\d{1,4}\.\s*`。
3. **修 PDF 抽取粘连**（共修复 30+ 处）：
   - 标点后缺空格 `published,expect` → `published, expect`
   - 小写接大写 `maneuver.Request` → `maneuver. Request`
   - **句点后缺空格** `route.Request` → `route. Request`（11 处，最隐蔽）
   - 数字接字母 `10,000feet` / `Runway15` / `initialaltitude` / `climbto`（手工表）
   - 反向修复：`(?<=\d)(?=[A-Za-z])` 会把 `36R` 拆成 `36 R`，需把跑道号、`HZ-01D`、`QNH1003` 拼回去。

### stage 2：ICAO 无线电通话发音规范化（本项目核心）

ICAO 数字读法：`0=zero 1=one 2=two 3=tree 5=fife 6=six 7=seven 8=ait 9=niner`，
小数整点读作 `decimal`。
**例外：`4` 读 `four`**（ICAO 标准拼写是 FOW-er，但用户听感刻意，已改回普通 `four`）。

| 类别 | 原文写法 | 改成 TTS 可读写法 |
|---|---|---|
| 跑道号 | `Runway 36R` | `Runway tree six right` |
| 飞行高度层 | `FL310` / `cruising level 330` | `Flight Level tree one zero` / `cruising level tree tree zero` |
| 航向/航迹/径向 | `heading 070` / `inbound track 270` | `heading zero seven zero` / `inbound track two seven zero` |
| 应答机码/编码 | `squawk 0722` | `squawk zero seven two two` |
| 频率 | `118.050` | `one one eight decimal zero five zero` |
| 气压 QNH/QFE | `QNH1005` / `29.91` | `QNH one zero zero fife` / `QNH two niner decimal niner one` |
| 马赫数 | `Mach point 84` | `Mach decimal ait fower` |
| 时间（分/时） | `cross CK at 35` | `cross CK at tree fife` |
| 坐标 | `42N 165E` | `fower two North one six fife East` |
| 航路/离场代号 | `B213` / `HZ-01D` / `BK-1A` / `D03` | `Bravo two one tree` / `HZ zero one Delta` / `BK one Alfa` / `Delta zero tree` |
| 航空器型号 | `B747` / `Airbus320` | `Boeing seven forty seven` / `Airbus three twenty` |
| 等级 | `CAT II` / `CAT IIIB` | `Category two` / `Category three Bravo` |
| 缩略语 | `ADS-B` `CPDLC` `TCAS` `GPWS` `PAPI` `RNAV` `GNSS` `ETOPS` | `A D S B` `C P D L C` `TEE-cas` `G P W S` `P A P I` `R N A V` `G N S S` `E TOPS` |
| **高度 / 云高 / 能见度 / RVR**（ICAO 2.8.1.2） | `3000 feet` / `10500 feet` / `2500 feet` / `350 meters` / `196 feet` | `tree tou-sand feet` / `one zero tou-sand fife hundred feet` / `two tou-sand fife hundred feet` / `tree hundred fife zero meters` / `one hundred niner six feet` |
| 单位/航线设施 | `15NM` / `AC BUS` | `15 nautical miles` / `A C bus` |
| 钟点方位 | `at 12 o'clock` | `at twelve o'clock` |

**高度读法规则（ICAO 2.8.1.2，逐位 + 千/百）**：千位、百位上的数字各自单独读，后面跟 `THOUSAND` / `HUNDRED`，
不足百的余数再逐位读。共命中 64 处高度 + 6 处能见度/RVR（54 句含千位）。
注意：**飞行高度层 FL 仍逐位**（ICAO 2.8.1.3），不适用本规则。

`THOUSAND` 的拼写（`normalize.py::THOUSAND`，当前 `"tousand"`）：
- `thousand` → TTS 读 /ˈθaʊzənd/，咬舌，不对；
- `tou-sand`（ICAO 官方拼法）→ **连字符会让 TTS 把音拖长**，用户否决；
- **`tousand`（无连字符）→ /ˈtaʊzənd/，干脆**，为当前选择。备选见 `audio/thousand_probe.mp3`。

**刻意保留自然语言读数的**：距离（`100 miles` / `5 miles`）、速度（`250 knots`）、
时间长度（`30 minutes`）、长度（`30 meters` 跑道宽度）、重量。

规则命中统计：flightlevel 99、runway 59、freq 20、squawk 14、bearing 30、time 29、coord 8、airway 20、sid-star 11、mach 9、aircraft 8、CAT 4、clock 6 ……

### stage 3：航路点 / 程序代号读音（2026-10-08 补）

| 类别 | 规则 | 例 |
|---|---|---|
| **5 字母命名航路点（5LNC）** | 按单词读（首字母大写） | `DAPRO`→`Dapro`、`KODAP`→`Kodap`、`JEMMY`→`Jemmy`、`OBLIK`→`Oblik`、`FUPAD`→`Fupad` |
| **1~4 字母定位点** | 逐个拼 ICAO 字母表 | `WXJ`→`Whiskey X-ray Juliett`、`JO`→`Juliett Oscar`、`ST`→`Sierra Tango`、`LX`→`Lima X-ray`、`EFFG`(SELCAL)→`Echo Foxtrot Foxtrot Golf` |
| **离场/进场程序代号** | 字母按上面规则 + 数字逐位 | `BK-02 RNAV`→`Bravo Kilo zero two R Nav`、`HZ-01D`→`Hotel Zulu zero one Delta`、`KODAP-01`→`Kodap zero one`、`BK-1A`→`Bravo Kilo one Alfa` |
| **单字母** | 只在其明确语境下拼读 | `W VOR`→`Whiskey V O R`、`Information X`→`Information X-ray`、`taxiway A`→`taxiway Alfa`、`holding point C`→`holding point Charlie` |
| **导航设施/机载缩略语** | 一律逐字母，防被读成单词 | `ILS`→`I L S`、`VOR`→`V O R`、`DME`→`D M E`、`NDB`→`N D B`、`APU`→`A P U`、`EGT`、`FMS`、`CDU`、`ATC`、`VHF`、`HF`、`GPS`、`ELT`、`RA` |
| **本身就读单词的** | 保留原样 | `RNAV`→`R Nav`（读 are-nav）、`TCAS`→`TEE-cas`、`RAIM`→`raym`、`ETOPS`→`E TOPS`、`Selcal`、`NOTAM`、`SIGMET`、`CODE`→`code`、`NOT`→`not` |
| **易误判的缩写** | 逐字母 | `FOD`（Foreign Object Debris）→`F O D` |
| **SID / STAR** | 逐字母，**不读成单词** | `SID`→`S I D`、`STAR`→`S T A R` |

规则命中：waypoint-spell 83、waypoint-5lnc 7、ident-1letter 9、desig-tight 1。

### 已知取舍
- `danger area 113`（危险区编号）按自然数读，不作逐位处理。
- **滑行道/等待点/ATIS 代码**已按 ICAO 字母解释法拼读（`taxiway Alfa`、`Information Papa`）。
  若你更习惯听 `taxiway A`，在 `normalize.py` 的 `IDENT_CTX` 里删掉对应三条即可。
- 3 字母航路点按用户要求一律拼读（实际通话里部分可拼读的 3 字母点也会按单词读，如 PER）。

## 音频工艺

选型结论（2026-10）：**ElevenLabs `eleven_v3`**，音色 Bella（`EXAVITQu4vr4xnSDxMaL`，美式女声）。
账户为 **Creator 套餐：131,000 字符/月**（重置日 2026-11-05），全文 66,118 字符 ≈ 占额度 50%，**不额外花钱**。
音色参数：`stability 0.68 / similarity 0.78 / style 0.12 / speed 1.05`。
语速沿革：0.85（初版）→ 0.95（用户嫌慢）→ **1.05**（用户再要求加快）。改 `VOICE_SETTINGS["speed"]`。

**数字 8 的拼写**：ICAO 官方写作 `AIT`，但 eleven_v3 对这个非词形状不稳定，**部分片段会念成 A-I-T 三个字母**。
已弃用官方拼写，直接用 `eight`（同一读音，机器 100% 稳定）。改 `normalize.py::EIGHT` 一个常量即可，
候选见 `scripts/eight_probe.py` → `audio/eight_probe.mp3`（7 种拼法 × 4 种语境对照）。

**气声选项**：`eleven_v3` 支持音频标签，在 `tts_generate.py::STYLE_TAG` 里改即可——
`""` 原音 / `"[soft-spoken] "` 轻柔软语 / `"[whispers] "` 耳边气声。
`scripts/voice_compare.py` 可一次性出 5 种配置对比（`audio/voice_compare.mp3`）。

1. **逐句合成**：一句一个 mp3（`.cache/clips/0001.mp3`），便于断点续传与单句重录；4 并发 + 429 退避重试。
2. **拼接**：句间插 2.5 s 静音，ffmpeg concat 拼成一条。
3. **后处理 → 真立体声 ASMR**（`scripts/tts_generate.py::asmr_chain`）：
   ```
   aresample=48000 → highpass 55Hz → lowpass 10.5kHz → bass +1.8dB@110Hz
   → aecho（柔和房间感）
   → asplit：左路 adelay 11ms + lowpass 8.8k / 右路 highpass 95Hz + 音量 0.965
   → amerge（Haas 立体声展宽）→ extrastereo m=1.6
   → 声场漂移 LFO → loudnorm I=-18 TP=-2 LRA=11
   ```
   输出 48 kHz / 立体声 / 256 kbps mp3。自检已验证：声道=2、48 kHz、-18 LUFS。

### 声场漂移（2026-10-08 最终版）

整条音轨的左右平衡会**来回换边**，不是一动不动的固定声像。

**实现方式的演变**：早期用 ffmpeg 表达式做 LFO；但用户要求「单侧停留 20~30 秒**随机**」后，
`random()` 无法表达"每段随机时长"，改为**离线用 numpy 算出整条声像控制曲线**，
写成 2 声道 f32le 文件（200 Hz），再用 `amultiply` 乘到音频上（`scripts/tts_generate.py::build_pan_track`）。

```
等功率声像法则：  L = cos(a)·d     R = sin(a)·d
a = π/4 + pos·(π/4)     ← pos=±amp 是极限位置，π/4 是居中
d ∈ [1-DIST_DEPTH, 1]   ← 远近因子，最大降幅 DIST_DEPTH
```
因为 L²+R² = d² 恒定，所以**换边时总音量不动**，只有远近因子 d 会让音量轻微起伏。
[pos_amplitude()] 负责把「一边 90%、一边 10%」这种配比换算成 pos 幅度：b=0.90 → pos=0.859 → ±19.1 dB。
相邻事件之间用**余弦缓动**插值（比线性更顺，没有换挡感）。

| 参数 | 值 | 含义 |
|---|---|---|
| `PAN_BALANCE` | **0.90** | 极限声道配比 **90:10**，即双耳差 **±19.1 dB**（曾试过 99:1 / ±39.9 dB，用户听后认为太极端，回退） |
| `PAN_SWAP_SEC` | **2.5 s** | 完全换到另一侧所需时间，用户要求 <3 s（穿越中间 ±20 dB 区实测 **1.73 s**） |
| `PAN_DIP` | **0.20** | 换边时中心下压比例，补偿**双耳响度求和**。见下方说明，实测落差 **-2.04 dB** |
| `PAN_DIP_SHAPE` | 1.0 | 下压曲线锐度：`w = (0.5·(1+cos(π·x)))^shape`，x=‖ILD‖/ILDmax。1=余弦钟形，两端导数为 0 |
| `PAN_HOLD_MIN/MAX` | 20 / 30 s | 单侧停留时长随机区间，实测 21~31 s |
| `PAN_SEED` | 20261008 | 固定随机种子，保证每次后处理结果可复现 |
| `DIST_DEPTH` | 0.10 | 远近起伏最大降幅，实测 **-0.92 dB = 10.0%** |
| `CTL_RATE` | 200 Hz | 控制信号采样率（曲线变化极慢，200 Hz 够用，一小时几十 MB） |
| `L_BRANCH_GAIN` | 0.9589 | 校平左右两路 EQ 带来的固有能量差（拿 600 秒真实语音实测得出，别拍脑袋改） |

> 踩过的坑：
> - `pan` 滤镜只支持标量增益，**不支持表达式**，所以声道随时间变化必须靠外部控制信号或 `volume:eval=frame`。
> - `volume` 表达式里有逗号（如 `if(gt(a,1),1,0)`）必须写成 `volume='expr':eval=frame`，用单引号包起来。
> - `aresample` 没有 `resampler=linear` 这个选项（有效值只有 swr / soxr），写了会直接报错。
> - **测量方法论**：别用粉红噪声的 50 ms 窗 max-min 判断音量稳定性——噪声自身就有 9.7 dB 抖动。
>   正确做法是同一段素材分别渲染"恒定居中"与"随机声像"两版，**逐窗相减**隔离出净调制，
>   同时剔除近静音窗口（沉默处的 dB 比值会炸出 -10 dB 之类的假值）。
> - **`pos_amplitude()` 的换算别手改**：等功率法则下配比 b:(1-b) → `pos = 1 - 4·atan((1-b)/b)/π`。
>   b=0.99 时 pos=0.9871，两耳差 39.9 dB，但**总能量 L²+R² 恒定**，所以再极端也不会让音量忽大忽小。

### 换边时的「中心下压」：补偿双耳响度求和

**现象**：同一个声音同时给两只耳朵听（居中），比只给一只耳朵听（完全偏一侧）更响。
这是听觉中枢的求和效应，等功率法则只能配平**物理能量**，配不平**听感**。

> **核验状态（2026-10-09 已逐条联网核对）**，完整出处含 DOI/PMID 见 `docs/TASK_ARCHIVE.md` 附录 B：
> ① Zwicker & Zwicker 1991, JASA 89(2):756–764, DOI 10.1121/1.1894635, PMID 2016430
> ② "Interaural correlation and loudness", JASA 119(5 Pt.2):3235 (2006，会议摘要；正式论文见 Edmonds & Culling 2009, JASA 125:3865–3870)
> ③ Moore, Gibbs, Onions & Glasberg 2014, JASA 136(2):736–747, DOI 10.1121/1.4889868, PMID 25096108
> ④ Schlittenlacher, Ellermeier & Arseneau 2014, *Attention, Perception, & Psychophysics*, DOI 10.3758/s13414-014-0651-1, PMID 24806401
>
> ⚠️ 注意：上面 6.5 dB 对应的是 **100–900 Hz** 中宽带，不是 100–5000 Hz（后者是 5.5 dB）。区间上下界不变。

**文献实测**（等响匹配 / 反应时法，宽带噪声与语音频段）：

| 来源 | 结论 |
|---|---|
| Zwicker & Zwicker 1991, JASA 89 | 双耳比单耳响约 **1.5 倍**，且随 ILD 增大而衰减；还测了「在两耳间来回切换」，切换变快时响度再涨约 20% |
| Interaural correlation and loudness, JASA 2006 | diotic 要匹配 monotic，monotic 需高 **4.6 dB**(窄带 460–540 Hz) / **5.5 dB**(宽带 100–5000 Hz) |
| JASA 2014 (PMID 25096108) | LDEL ≈ **5.6 dB** @500 Hz、4.2 dB @3–4 kHz |
| Schlittenlacher 2014 (反应时法) | ≈ **5 dB** @1 kHz |

**换算到本项目的取值**：等功率法则在居中时每耳已各降 3 dB（这是它的本分），
真正剩下的净差 = 求和量 4.6~6.5 dB − 3 dB + 极限位置主导耳本就有的 0.05 dB ≈ **1.6 ~ 3.5 dB**（中位 2.5 dB）。
对应 `PAN_DIP`：**17% / 25% / 33%**。用户凭感觉猜的 **20%（-1.94 dB）正好落在区间内偏保守一端**，
所以直接采用，不必推翻。实测曲线：停留期 -0.47 dB → 穿越中心谷底 -2.51 dB，**落差 2.04 dB**。

下压权重不用时间窗，而是跟着瞬时 ILD 走（`x = |ILD|/ILDmax`，余弦钟形）：
停留期 w≡0 完全不动，只在真正穿越时出现凹陷，两端导数都是 0，没有任何折角或泵感。

### 分段并行渲染（Stage A / Stage B）

| 阶段 | 耗时计数 |
|---|---|
| Stage A（变速/EQ/回声/分路/extrastereo） | 与声像**完全无关** → 切成 8 段并行，产物长期缓存 |
| Stage B（声像 + 中心下压 + 响度归一 + mp3） | 约 1 分钟 |

loudnorm 用官方**两遍流程**：第一遍 `print_format=json` 只测量，结果缓存成 json；
第二遍把 `measured_*` 喂回去跳过测量。改 `PAN_DIP` 只影响总时长的 0.04%，连测量都不用重跑。

**实测迭代成本**（同一批 clip，只改 `--pan-dip`）：

| | 首次 | 之后（全部缓存命中） |
|---|---|---|
| rebuild_clips 534 句 | ~6 min | 0（比 parts 新就跳过） |
| Stage A（8 段并行） | 24 s | **0（缓存命中）** |
| Stage B | 175 s | 175 s |
| **合计** | **10 min 51 s** | **3 分 20 秒（3.3x）** |

> Stage B 的 175 s 里 loudnorm 占大头，但**换静态 `volume` 并没有明显收益**：
> 300 秒片段测是 8.19 s → 0.55 s（15 倍），可一旦接上「1.2 GB 中间 wav 的读写 + lame 编码」，
> 整片只差几秒（183 s vs 174 s，反而抖动更大）。而且静态版的 True Peak 保护要靠手动留余量，
> 不如 loudnorm 自带 4 倍过采样 TP 限幅稳。**结论：默认保留 loudnorm**（`--fast-norm` 可切，但不推荐）。

> **踩坑：`atempo` 不能分段跑。** 它会把内部处理窗口对齐到 4096/2048 采样这种 2 的幂次边界，
> 一旦分段，每个接缝就错位 40~85 ms（听得见的"咔"）。解决办法是把 `aresample + atempo`
> 提到公共前置段（`ensure_prepared_src()`）**整段做一次**（全片约 3 秒），
> 之后时间轴就是成品时间轴，剩下的 FIR/IIR/delay/gain 可以任意切开。
> 实测 4 段验证：各窗口在最佳对齐处差异 **0.00000**，仅个别 section 有 1 采样（20 µs）偏移 —— 工程等价。
>
> 另一个坑：对 **mp3** 做 `-ss` 即使加 `-accurate_seek` 也会漂几十采样，所以前置段必须先把源转成 PCM。

## 本轮踩的坑（2026-10-08 v13x12 全量时）

| 坑 | 现象 | 修法 |
|---|---|---|
| **`_encode_f32` 用固定路径临时文件** | 4 并发互相覆盖同一个 raw → 首轮全量**随机丢 47 句**（全是多块句），且每次丢的不一样 | 临时文件名带上 `pid + 线程号` |
| **part 清单键名不一致** | `set_part_count` 存 `"408"`，文件名是 `0408_00.mp3`，键名对不上 = 清单失效 → 返工后的旧块会被拼回来 | 改成**文件名清单**（不是块数），键统一 `%04d` |
| **`post` 模式 `fail` 未定义** | 单独跑 `post` 时 2 秒就退出（`fail` 只在 sample/all 分支赋值） | main 里先 `fail = []` 兜底 |
| **`shutil.rmtree` 被批量删除保护拦住** | 每句都弹 `[safe-delete]` 告警，累计还会 timeout | 不删了：直接写 parts 目录，省掉 tmp + copy |
| **Windows 下 bash 的 `rm` 不可靠** | 批量删 `.cache` 的文件会被 shim 拦截 | 一律用 Python `shutil.rmtree`，且能不删就不删 |
4. 附带 `04_timestamps.txt`：900 句的时间戳目录，方便回听定位。

## 进度

- [x] 文本清洗（去序号 + 修粘词）
- [x] ICAO 发音规范化 + 抽样校验（337/900 句被改写）
- [x] ffmpeg 工具链（9.0.2，`.cache/ffmpeg.exe`）+ 后处理链路自检通过
- [x] 取得 ElevenLabs API Key（Creator 套餐 131k 字符/月）
- [x] 航路点 / 程序代号读音规范化（5LNC 读单词、1~4 字母拼读）
- [x] 样音：`audio/sample_asmr.mp3`（15 句，2:32，48k 立体声）
      + `audio/probe_waypoints.mp3`（17 组读音 A/B 探针，1:25）
      + `audio/voice_compare.mp3`（5 种音色/气声对比）
      + `audio/thousand_probe.mp3`（thousand 拼写 5 选 1）
- [x] 音色定稿：**Bella 原音（无音频标签）+ speed 0.95**
- [x] 全量 900 句合成（成功 900/900，耗时 23 分钟，实际计费 31k 字符）
- [x] 拼接 + 双声道 ASMR 后处理
- [x] 交付 `audio/ICAO900_ASMR.mp3` + `04_timestamps.txt`

## 成品（2026-10-08 最终版）

> 下面三行是 **2026-10-09 对最终成品文件的 ffprobe + ebur128 实测值**（此前记的 −18.7/−2.6/12.0 是中间版本或编码前的测量，以本表为准）。

| 文件 | 时长 | 参数 | 说明 |
|---|---|---|---|
| `audio/ICAO900_ASMR.mp3` | 1:42:13（6133 s） | 48 kHz / 2.0 / 256 kbps / 187 MB | **清晰版**：正常发声，适合清醒时练听力 |
| `audio/ICAO900_whisper_v13x12.mp3` | **1:46:00.892**（6360.892 s） | 48 kHz / 2.0 / 256 kbps CBR / 203,550,764 B（194 MiB） | **气声悄悄话最终版 v13x12**（900 句完整版，见下方「尾部截断事故」） |
| `audio/ICAO900_raw_mono.mp3` | 1:57:33 | 44.1 kHz / 单声道 / 192 kbps | 纯干声（未做任何后期），原速 |
| `audio/ICAO900_raw_mono_fast.mp3` | 1:42:13 | 44.1 kHz / 单声道 / 192 kbps | 仅变速的干声，与成品逐帧对齐，用于 A/B |

> **版本命名**：`whisper_v13x12` = 第 13 版切分方案 + **0.12 s 交叉淡化**。
> 同一批素材想试更短的过渡，改 `--xfade` 再 `post` 即可，**零额度**：素材都在 `.cache/clips_v13x12_parts/`。

### ⚠️ 尾部截断事故（2026-10-09 发现并修复）

**症状**：用户把成品导入 Premiere Pro 后发现「字幕对不上」，进一步对比发现**音频少了约 10 句半**。

**实测证据链**：

| 环节 | 时长 | 判定 |
|---|---|---|
| `full_cat_whisper_v13x12.mp3`（拼接干声） | 7315.045 s | 完整 |
| `prep_whisper_v13x12.wav`（变速后 PCM） | **6360.892 s** | 完整（7315.045 ÷ 1.15 ✓） |
| Stage A 8 段合并 | 6290.808 s | ❌ **少 70.087 s** |
| 成品 mp3 | 6290.805 s | ❌ 少 70.087 s（≈ 第 890~900 句） |

模板匹配（`scripts/verify_tail.py`）逐句验证：第 881~889 句匹配分 0.61~0.92 且落点单调递增；
**第 890~900 句分数仅 0.35~0.68、落点散乱无单调性 → 确实不在音频里**。

**根因**：`prepared_cuts()` 用「clip 时长 + 标称 gap」**累加估算**总长（得 6290.805 s），
而真实素材是 6360.892 s（差 1.1%）。最后一段渲染到 `cuts[-1]` 就收尾，
于是**末尾 70 s 被整段丢弃，且全程不报错**。
（10-08 23:24 的 1:99 备份是**加速改造之前**的产物，所以完整——用户正是拿它对出来的。）

**修复**（`scripts/tts_generate.py`）：
1. `prepared_cuts(..., total_real=...)`：一律以真实素材长度为准，估算值只用来定位切点
2. `render_stage_a()`：拿 `_probe_sec(prep_path)` 等比缩放切点并钉死末点
3. **新增输出长度校验**：素材与分段结果不等长直接 `SystemExit`，杜绝静默截断复发
4. `render_fast()`：声像控制曲线也改用真实总长（否则末段没有声像）

**修复后**：6360.892 s / 高置信句间边界 **900 个** / 末尾句逐句回归且与备份位置吻合
（6324.22 / 6330.47 / 6335.18 / 6340.02 / 6346.27 / 6355.66 s）。
响度 -18.4 LUFS、TP -1.3 dBFS、LRA 10.3 LU，与修复前一致。

**教训**：**任何"切段并行再拼回"的链路，都必须拿真实素材长度钉死末点，并做输入/输出长度校验。**
靠累加估算总长 = 把误差全堆在末尾，且不会有任何报错。

### v13x12 气声悄悄话版（2026-10-08 定稿）

音色 **Emmaline `nDJIICjR9zfJExIFeSCN`**（英音小女孩，公共库）× **eleven_v4**（促销期扣 0.28x 额度）
× 音频标签 `[whispers] `，人格参数 `stability .35 / similarity .65 / style .30`，`TEMPO=1.15`。

流程：`all` 合成 900 句 → 质检（下节）→ 问题句返工 → `post` 套用压制结果并统一 0.12 s 交叉淡化 → 声场后处理。

素材档位：
- `.cache/clips_v13x12/` 900 个整句
- `.cache/clips_v13x12_parts/` 多块句的原始分块（534 句），改 xfade 全靠它
- `.cache/clips_v13x12_parts/_manifest.json` 每句由哪几个 part 拼成（**文件名清单**，键是 `%04d`）
- `.cache/clips_v13x12_duck/` 被本地压制过的句子（第 408/434/723 行），`post` 时最后套用

## 气声质检与返工（2026-10-08）

`mode=check`。核心指标是**谐噪比 HNR**：周期性越强（正常发声）HNR 越高，气声几乎无周期 → HNR 低。
实测标定：**合格气声素材全窗 HNR 最高只有 -0.4 dB，正常发声素材是 +7 dB**，中间空着 8 dB，
所以阈值可以定死在 `LOUD_HNR_ABS = +2.0 dB`，不需要逐句调。

两级判据（都要再叠加「音量高出 ≥3 dB」，**宁可漏不可滥**）：

| 判据 | 条件 | 治的是 |
|---|---|---|
| **P1 中途变本音** | 连续 ≥2.5 s 的窗：HNR > +2 dB **且** 比本句常态响 ≥3 dB | 标签续航不足，后半句退回正常发声 |
| **P2 整句不是气声** | 整句 HNR 中位 > +2 dB **且** 整句比全批中位响 ≥3 dB | 标签压根没生效（句内很平，只看句内相对量会漏掉） |

- 全批中位响度由 `batch_ref()` 现算（这批实测 **-34.9 dB**），一把尺子量到底，返工前后用同一个 ref 复检。
- 30 句滑窗不足的短句（2~4 词、≤2 s）单独用整句判据复核，实测全部合格。
- 返工顺序：**先按 ≤6 词重切重录**（每块各带一次标签）→ 复检仍超标才上 `duck_clip()`
  （按短时包络做平滑增益压制，纯 numpy、**零额度**；P2 的句子句内是平的，要额外整句衰减）。

> 教训：**返工不是万能的**。重录确实能让 P1 句变合格，但代价是长句被切成 10 段
> （还切出 `"at"`、`"North"` 这种单块词），拼接感远大于那点音量差。
> **最终选择「常规切分保连贯 + 本地压制保音量」**，全局只对第 408/434/723 三句生效。

- 清晰版：响度 -17.9 LUFS、真峰值 -3.6 dBTP、静音块 916 个 ≥ 900 句 → 无丢句无串行
- 耳语版（**2026-10-09 成品实测**）：响度 **-18.4 LUFS**、真峰值 **-1.3 dBFS**、**LRA 10.3 LU**
  （旧的 -18.7 / -2.6 / 12.0 是编码前的测量值；-1.3 比 loudnorm 目标 -2 dBTP 高，来自 mp3 编码过冲）
- 时间戳目录：`04_timestamps.txt`（清晰版）/ `05_timestamps_whisper.txt`（耳语版），各 900 行

### 干声版（未经任何后期处理）

想对比「加了 ASMR 后期 vs 原始 TTS」时用这两份，**时间戳与成品完全对齐**（03:10 处就是同一句），可同时拖进播放器 A/B。

| 文件 | 说明 | 时长 | 参数 |
|---|---|---|---|
| `audio/ICAO900_raw_mono.mp3` | **纯干声**：900 句 ElevenLabs 原声 + 句间静音直接拼接，原速，无变速/无立体声/无 EQ/无混响/无响度归一 | 1:57:33 | 44.1 kHz 单声道 192 kbps |
| `audio/ICAO900_raw_mono_fast.mp3` | **同速干声**：只加了 `atempo 1.15`，其余一律不处理 → 与成品逐帧对齐 | 1:42:13 | 44.1 kHz 单声道 192 kbps |

中间产物同源：`.cache/full_cat.mp3`（干声拼接源头）与 `.cache/clips/*.mp3`（900 个单句原始文件）。

### 多版本共存（2026-10-08 起）

`tts_generate.py` 支持参数化，可平行产出多个版本互不覆盖：

```bash
# 清晰版（默认）
python scripts/tts_generate.py all

# 耳语版：气声标签 + 独立 clip 目录 + 独立成品名
python scripts/tts_generate.py all --tag "[whispers] " --clips clips_whisper --name whisper
```

| 参数 | 作用 |
|---|---|
| `--tag` | 写入每句前的音频标签：`""` / `"[whispers] "` / `"[soft-spoken] "` |
| `--clips` | clip 子目录，默认 `clips`；换目录即换版本，断点续传互不干扰 |
| `--name` | 成品后缀 → `ICAO900_<name>.mp3`，时间戳写 `05_timestamps_<name>.txt` |
| `--tempo` | 变速倍率，覆盖全局 TEMPO |
| `--voice` | voice_id |

### 音频标签实测结论（重要）

以「>3 kHz 高频占比」作为气声强度指标，对 Bella 做对照：

| 标签 | 高频占比 | 结论 |
|---|---|---|
| （无） | 1.7% | 基准 |
| **`[whispers]`** | **6.5%** | ✅ **唯一显著生效**，气声约 4 倍 |
| `[whispering]` | 1.3% | ❌ 无效 |
| `[soft-spoken]` | 1.3% | ❌ 无效 |
| `[whispers][close-mic]` | 1.4% | ❌ 叠加第二个标签会**覆盖掉**前者，反而失效 |

**但逐句气声强弱无法保证一致**：同一句、同一参数重复合成 3 次，高频占比在 0.9%~6.1% 之间跳（近 6 倍），
这个随机抖动**远超标签本身带来的差异**。所以批量结果里有的句子气声重、有的偏正常，是 eleven_v3 的固有特性，
不是标签没传。（教训：别拿单次合成的频谱指标判定标签是否生效。）

### 语速控制（重要教训）

**不要用 ElevenLabs 的 `voice_settings.speed` 调语速。** 实测该参数在 `eleven_v3` 上不可靠：

同一句分别按 0.95 / 1.05 合成，时长几乎相同（第 6 句两次都是 4.32 s，第 300 句 0.95 版反而更短）。
单次生成本身有 ±10% 抖动，完全盖过了 ±10% 的语速差。
（历史教训：0.95 那一版总时长只比之前短 21 秒，等于没改。）

**改用 ffmpeg `atempo`（`tts_generate.py::TEMPO`），确定性变速、保持音高，改完只需 `post` 重跑约 8 分钟，零额度消耗。**
当前 `TEMPO = 1.15`（快 15%）。

> 配套细节：句间静音在拼接时先按 `GAP_SEC * TEMPO` 插入，变速后正好回落成 2.5 s；
> `write_index()` 会把 clip 时长除以 tempo 再累加，保证时间戳目录与实际成品对齐。

## 额度核算（重要）

最初按 67k 字符估「占 51% 额度」，**实际 ElevenLabs 只计 31k**
（全文录入时才 32,177/131,000，重置日 2026-11-05）。
→ **剩余 98,823 字符，够完整重跑约 2 次**。
所以临时改读音 / 换音色 / 调语速都不必心疼，直接 `python scripts/tts_generate.py all` 重来即可
（脚本会跳过 `.cache/clips/` 里已存在的句子，只补录改动过的）。
