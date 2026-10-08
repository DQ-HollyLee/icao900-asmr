# ICAO 900 句 → Sleep ASMR 音频：完整技术档案

> **存档目的**：把 2026-10-08 ~ 2026-10-09 这一轮完整任务（文本规范化 → 气声语音合成 → 质检返工 → 空间声场后处理 → 成品）固化成一份可检索、可复用的工程档案，供日后整理为**技术研究报告**或**描述性论文**时直接取用。
>
> **数据可信度标注**：本文每个数字都带来源标签——
> `[实测]` 有脚本输出 / 日志佐证；`[会话]` 当时测量过但产物（中间文件）未必保留；`[待补]` 尚未做过、写论文前必须补。
>
> **建档日期**：2026-10-09 ｜ **项目根**：`E:\Program Files\WorkBuddyProjects\icao900-asmr`
> **成品**：`audio/ICAO900_whisper_v13x12.mp3`（见 §6 客观指标）

---

## §0 摘要草稿

> 一段可直接改写成论文 Abstract 的中文底稿（英文版待写）。

本研究以国际民航组织（ICAO）陆空通话英语 900 句为基础语料，构建了一条端到端的**睡眠期听觉磨耳 content production pipeline**，用于飞行学员在无意识状态下进行语料熟悉度训练。流水线包含四个层次：(1) **文本层**——针对 ICAO 无线电通话特有读数规则（逐位数字、`THOUSAND`/`HUNDRED` 分节、呼号与航路点拼读）编写发音规范化算法，904 行文本中 337 句被改写；(2) **语音层**——在神经 TTS 上通过表演指令标签合成气声（whispered）声道，并通过**语义感知分块**缓解标签在长句上的续航衰减；(3) **质检层**——以**谐噪比（HNR）**为客观判据自动筛查非气声片段，两级判据共命中 4 句并返工；(4) **空间层**——采用等功率声像法则生成随机时长的双侧漂移立体声场，并引入**双耳响度求和补偿**（binaural loudness summation compensation），在声道切换穿越中心时对总增益施加余弦钟形下压，使单侧偏听与中心定位之间的主观响度保持一致。最终成品 1:46:00.892（6360.892 s），48 kHz / 立体声 / 256 kbps / −18.4 LUFS / TP −1.3 dBFS。本文同时记录了若干 ffmpeg 工程陷阱（atempo 分段错位、mp3 seek 漂移等）及其解决方案。

---

## §1 任务定义

| 项 | 内容 |
|---|---|
| **目标用户** | 民航飞行学员 / 现役飞行员，需要背诵 ICAO 900 句陆空通话英语（PEPEC 考试语料） |
| **使用场景** | 睡前播放，被动"磨耳朵"；要求**不吵醒**、**不疲劳**、**可长时间聆听** |
| **核心矛盾** | 学习材料要求语音清晰可读 vs 睡眠助听要求低唤起度（low arousal）→ 落在"气声耳边低语"这个交集上 |
| **输入** | `PCPEP900.txt`（GB18030 编码的 PDF 抽取文本，含序号与粘连错误） |
| **输出** | 一条连续音频 + 逐句时间戳目录，用户可跳到任意一句回听 |
| **硬约束** | ElevenLabs Creator 套餐 131,000 字符/月，不额外付费；单人在本地 Windows 机器上完成 |

**需求方**（即用户）全程以**听觉主观反馈**驱动迭代，而非给定客观指标。这是本项目最重要的特征：整个 pipeline 的参数空间搜索由一个人类听者的 15 轮偏好反馈完成（见 §2）。

---

## §2 需求演变时间线（15 轮迭代）

> 这是把本项目写成"描述性论文 / design study"最有价值的素材——它完整记录了**评价函数不在算法内、而在人身上**时，一条 audio pipeline 是如何收敛的。

| 轮次 | 用户原话（要点） | 技术响应 | 结论 |
|---|---|---|---|
| 1 | 把 900 句做成 ASMR 睡前磨耳音频 | 文本清洗 + ElevenLabs 合成 + 拼接 | 时长 1:42，清晰版 |
| 2 | "希望在耳边说的感觉" | 加入 Haas 展宽 + 房间回声 | 空间感建立 |
| 3 | "ALT/OUT.. alt 发音不对" | **ICAO 发音规范化**（§4.1） | 337/900 句被改写 |
| 4 | "高度 3000 feet 应该读 tree tousand" | ICAO 2.8.1.2 千/百位规则 | 命中 64 处高度 |
| 5 | "数字 8 念成 A-I-T" | `AIT` → `eight`（机器稳定性 > 惯例拼写） | 7 种拼法探针后选定 |
| 6 | "太慢了" | speed 0.85→0.95→1.05 | ⚠️ **后来证明此路不通**（§4.6） |
| 7 | 个别词（如 `Certainly`）读音走样，逐句挑 | 逐句审阅 + 时间戳定位 | — |
| 8 | "耳语还是太远了" | 加 `[whispers]` 标签 + 近讲感处理 | ⚠️ 方向错误（§4.3） |
| 9 | "原来的音频感觉都是在**耳边喊**出来的" | 试 `[soft-spoken]`、降响度、压 2.2k/6.5k/11k 共振峰 | ⚠️ **方向再次错**（§4.3） |
| 10 | "要**气声**，不是轻声" | 关键概念纠正（§4.3） | 用户亲自录同一句作为参照 |
| 11 | "气声变成烟嗓了"、"还是太老" | 窄 bell 推 5.5k/8.5k → 失败；转**音色搜索** | 童声路线 |
| 12 | 用户挑选公共库音色 | Luna / Natasha / Lovejoy / Emmaline 对比 | 定 **Emmaline** |
| 13 | "每句话不流畅" | 分块过渡：gap 0 → **0.12 s 交叉淡化**（§4.5） | v13x12 |
| 14 | 换边 <3 s、放开到 1:99 | `PAN_SWAP_SEC=2.5`、`PAN_BALANCE=0.99` | ⚠️ 后回退 |
| 15 | "1:99 太极端了" + 询问双耳响度是否有研究 | 回退 **10:90** + 新增 `PAN_DIP=0.20`（§4.8） | **最终定稿** |

**收敛过程的三条模式**（适合写进论文的 Discussion）：

1. **用户的否定反馈常常指向错误的修复方向**。第 9、10 轮我们都误以为"不够近 = 音量太大"，于是压低 2.2k/6.5k/11k 并降低响度——而 §4.3 的频谱证据显示，这些频段正是气流噪声所在，压缩它们恰好抹掉了气声。
2. **凡是能用客观频谱检验的，就不要依赖用户形容词**。"年轻""远""烟嗓"这类词无法直接落到参数上，但 HNR、谱质心、F0 可以，且 diagnose 之后往往推翻直觉。
3. **可逆性决定了迭代速度**。语速、过渡、声像、响度这四件事全部做到了"改参数不重合成、不消耗 API 额度"，因此才有可能在最后一天连跑十几版。这是本项目工程侧最重要的一项设计取舍。

---

## §3 系统流水线总览

```
[文本层]  PCPEP900.txt (GB18030)
             │  normalize.py
             ├─ stage1 清洗：去序号、修 PDF 粘连、全角转半角
             ├─ stage2 ICAO 发音规范化（数字/呼号/跑道/频率/QNH/高度/缩略语）
             └─ stage3 航路点与程序代号读音（5LNC 读词、≤4 字母拼读）
             ▼
          01_sentences_clean.txt → 02_tts_icao.txt  （900 行，TTS 唯一输入）
             │
[语音层]  ├─ 语义感知分块 ≤16 词整句不切 / 超长句按语义单元贪心打包 ≤8 词
          ├─ 每块前缀注入表演指令 `[whispers] `
          ├─ ElevenLabs eleven_v4 · Emmaline · stability .35 / similarity .65 / style .30
          └─ 4 并发线程池 + 429 指数退避  → .cache/clips_v13x12/NNNN_00.mp3
             │
[质检层]  HNR 两级判据（P1 中段变本音 / P2 整句非气声）
          ├─ 命中 → ≤6 词重切重录（否决：破坏连贯性）
          └─ 命中 → duck_clip() 本地包络压制（采纳）→ clips_v13x12_duck/
             │
[整合层]  按语义感知 + 0.12 s 交叉淡化重建多块句 → 插入 2.5 s 句间静音 → 线性拼接
             │
[后处理]  Stage A（可缓存、可 8 段并行）
          │   aresample 48k → atempo 1.15（整段一次）
          │   → highpass 55 / lowpass 10.5k / bass +1.8dB@110
          │   → aecho → 左路 delay 11ms+lowpass 8.8k / 右路 highpass 95（×0.9589 校平）
          └─> amerge → extrastereo m=1.6
          Stage B
              build_pan_track() 离线算 2ch 控制信号（200 Hz f32）
              → channelsplit + amultiply（等功率声像 + 中心下压 + 远近起伏）
              → loudnorm I=-18 TP=-2 LRA=11（两遍，measure 缓存）
              → mp3 256 kbps
             │
[交付]    audio/ICAO900_whisper_v13x12.mp3 + 05_timestamps_whisper_v13x12.txt
```

**关键设计原则：三个分离**

| 分离 | 意义 |
|---|---|
| **合成 与 后处理分离** | 逐句落盘成独立 clip，任何后处理参数改动 = 零 API 额度重跑 |
| **整句 与 分块分离** | `parts/` 目录保留原始分块，交叉淡化时长可随时改 |
| **Stage A 与 Stage B 分离** | 与声像无关的部分长期缓存，声像迭代 10m51s → 3m20s（§4.13） |

---

## §4 关键技术决策与实验依据

> 每一节的写法：[背景] → [候选方案] → [确凿测量] → [决策] → [可复用的教训]

### 4.1 文本层：ICAO 发音规范化

**为什么必须做**：TTS 前端对航空英语一无所知。`FL310` 会被读成单词或 "flight level three ten"；`Runway 36R` 读作 "thirty-six are"；`3300 feet` 读作 "three thousand three hundred"（ICAO 要求逐位）。

**规则表**（完整版含实例见 `PROJECT.md`）：

| 类别 | 原文 | 规范化后 |
|---|---|---|
| 逐位数字（ICAO） | `0/1/2/3/5/6/7/9` | `zero/one/two/tree/fife/six/seven/niner` |
| ⚠️ 数字 4 | — | 保留 `four`（ICAO 官方 FOW-er，用户听感刻意，否决） |
| ⚠️ 数字 8 | — | 用 `eight` 而非官方 `AIT`（v3/v4 会把 AIT 念成三个字母） |
| 飞行高度层 | `FL310` | `Flight Level tree one zero` |
| 高度（2.8.1.2） | `3000 feet` | `tree tousand feet` |
| 跑道号 | `36R` | `tree six right` |
| 频率 | `118.050` | `one one eight decimal zero fife zero` |
| QNH | `QNH1005` | `QNH one zero zero fife` |
| 应答机 | `squawk 0722` | `squawk zero seven two two` |
| 航路点 5 字母 | `DAPRO` | `Dapro`（按词读） |
| 航路点 1~4 字母 | `WXJ` | `Whiskey X-ray Juliett`（拼读） |
| 离/进场代号 | `BK-02` | `Bravo Kilo zero two` |

**键的取舍案例（写论文好用）**：
- `THOUSAND` 拼写三选一：`thousand`（咬舌 /ˈθaʊzənd/）／`tou-sand`（官方写法，但**连字符会让 TTS 拖长音**）／`tousand`（无连字符，/ˈtaʊzənd/ 干脆）→ 选第三者。**教训：官方拼写不能被 TTS 直接消费，要做一轮"拼写—音形稳定度"实测。** 探针：`scripts/...probe.py` → `audio/thousand_probe.mp3`。
- 规则命中统计：`[会话]` flightlevel 99、runway 59、freq 20、squawk 14、bearing 30、time 29、coord 8、airway 20、sid-star 11、mach 9、aircraft 8、CAT 4、clock 6；共 **337/900 句**被改写。

---

### 4.2 音色层：为什么最终是"英音小女孩"

**约束**：账号自带 21 个音色**全是成年音色**，童声只能去公共库（`GET /v1/shared-voices?search=...&gender=female&language=en`，按 `usage_character_count_1y` 排序）。

**测量**：用自相关估中位 F0 作为"年龄感"代理指标 `[会话]`——童声 250~400 Hz，成年女 165~255 Hz，成年男 85~180 Hz。

| 音色 | voice_id | 实测 F0 |
|---|---|---|
| **Emmaline** ✅ | `nDJIICjR9zfJExIFeSCN` | 242 Hz（英音年轻） |
| Lulu Lolipop | `ocZQ262SsZb9RIxcQBOj` | 390 Hz（最童，但未选中） |
| Candy | `Nggzl2QAXh3OijoXD116` | 338 Hz |
| Mini | `hO2yZ8lxM3axUxL8OeKX` | 270 Hz |
| Sarah / Bella | `EXAVI...` / `hpp4J...` | 成人（前 12 轮用） |

> ⚠️ **命名陷阱**：本账号里 `EXAVITQu4vr4xnSDxMaL` 的名字是 **Sarah 而不是 Bella**，Bella 是另一个 id。前两版成品实际都是 Sarah。API 返回的 `name` 与社区页面显示名不总一致，务必以列表接口为准。

**失败的路线（重要教训）**：试图用后处理改变年龄感——`rubberband=pitch=N` 默认 `formant=0` → 花栗鼠效应；补 `formant=1` 后用户仍不能接受。
> **结论：音色年龄只能在音色选择阶段解决，不能靠信号处理补救。**

---

### 4.3 ★ 气声 vs 轻声：本项目最关键的一次概念纠偏

**用户需求原话**：「我要的不是音量小（轻声），而是在耳边用**气声**说话。你只是一直把声音变小、语气放柔，那不是我要的——那样听起来像中年妇女。」

**测量方法**：用户提供自己的**真人对照录音**（同一句"正常发声 vs 气声"，`D:\33748\Documents\录音\`），用 `scripts/analyze_breath.py` 提取：

| 指标 | 正常发声 | 气声 | 变化 |
|---|---|---|---|
| HNR（谐噪比） | +1.8 dB | **−4.3 dB** | 周期性消失 |
| 谱质心 | 581 Hz | **2052 Hz** | 能量从低频搬到高频 |
| 频段能量 | <300 Hz **−7 dB**、>2 kHz **+9 dB** | | |

**那么'>2 kHz 推>㉹️ 会怎样'**：这直接推翻了第 9、10 轮的做法（压低 2.2k/6.5k/11k + 降响度）——**那几个频段正是气流的噪声所在，压它就等于抹掉气声**。

**⚠️ 逆直觉发现：`[whispers]` 标签的走向与真人气声相反。**
以无标签版本为基准做差分：

| 标签 | 100~200 Hz | >2 kHz |
|---|---|---|
| `[whispers]` | **+7~13 dB** | **−7 dB** |

也就是说 ElevenLabs 的 whisper 是靠"压低变厚"实现低语，听感上更接近**成熟、距离远**——而用户要的是相反方向。（这条已被 `whisper_breath.py` 反复验证。）
不过在所有候选标签里，`[whispers]` 仍是**唯一显著生效**的：以 >3 kHz 高频占比为指标，无标签 1.7% → `[whispers]` **6.5%**（约 4 倍）；而 `[whispering]` 1.3%、`[soft-spoken]` 1.3%、`[whispers][close-mic]` 1.4%（叠加第二个标签会**覆盖**前者，反而失效）。

**另一条重要限制**：同一句同参数重复合成 3 次，高频占比在 **0.9% ~ 6.1%** 之间跳（近 6 倍），这个固有抖动**远超标签带来的差异**。
> **教训：别拿单次合成的频谱指标判定标签是否生效**；批量结果里有的句子气声重、有的偏正常，是模型固有随机性，不是参数没传。这正是 §4.11 质检层存在的理由。

---

### 4.4 表演指令续航衰减 与 语义感知分块

**问题**：`eleven_v3/v4` 的表演指令**续航有限**。实测 43 词长句单次注入 `[whispers]`，末段 HNR 从 **−3.7 dB 涨到 +2.9 dB**（退回本音）`[会话]`。

**解法**：把长句切成小块，**每块各带一次标签**。但"怎么切"经历了三代：

| 版本 | 策略 | 问题 |
|---|---|---|
| v1 | 每 8 词硬切 | 切点落在词组中间，出现 `X-ray | Juliett`、`tree six | right` 的莫名停顿 |
| v2 | 只在标点处切 | 修复了带逗号长句，但**无标点超预算句**仍被按词硬切 |
| **v3（采用）** | **语义感知**：先粘成不可拆语义单元（数字串、呼号、跑道号），切点只能落在单元边界；且整句 ≤16 词**完全不切** | — |

**参数**：`NO_SPLIT_WORDS=16`、`CHUNK_WORDS=8`（软预算）、`CHUNK_HARD=16`（单元内兜底）、`TRIM_EDGES=True`（裁块首尾静音，阈值保守以免吞弱辅音尾）。
**效果**：三句 40+ 词长句的 HNR 漂移从 **+6.6 dB 降到 +0.5 dB**，`[会话]`

---

### 4.5 拼接过渡：为什么最终是 0.12 s 交叉淡化

用户对'不流畅'的投诉指向两个方面：

| 方案 | 用户反馈 | 客观问题 |
|---|---|---|
| 硬拼接（gap 0） | — | 咬字尾音被截断，块边界有台阶 |
| 插入静音 gap | "吞掉 Juliett"（切点落在需要连贯发音的位置） | 节奏被打散 |
| **交叉淡化 0.12 s（采用）** | 用户确认此版 | 优于 0.06 s（过渡太短仍有台阶） |

> 名字由来：成品 `whisper_v13x12` = 第 13 版切分 + **0.12 s 交叉淡化**。改成别的时长不用重新合成（`--xfade` + `post`，零额度）。

---

### 4.6 语速：不要用 TTS 的 speed 参数

**实测**（`[会话]`）同一句按 0.95 / 1.05 各合成一次，时长几乎相同（第 6 句两次都是 4.32 s；第 300 句 0.95 版反而更短）。原因是单次生成本身有 **±10% 抖动**，完全盖过了 ±10% 的语速差。历史教训：0.95 那一版总时长只比之前短 21 秒≈没改。

**解法：ffmpeg `atempo` 后处理**（`TEMPO = 1.15`）。确定性、保持音高、改完只重跑 post。
配套：句间静音先按 `GAP_SEC × TEMPO` 插入，变速后正好回落 2.5 s；`write_index()` 把 clip 时长除以 tempo 再累加，保证时间戳目录与成品对齐。

---

### 4.7 空间声场：等功率声像 + 随机停留

**需求**（用户）：左右差别要大、换边要干脆（<3 s）、单侧停留 20~30 s **随机**、叠一层轻微远近感、总音量不能有可闻起伏。

**法则**：等功率（equal-power / constant-power）声像
```
L = cos(a)·d,  R = sin(a)·d,  a = π/4 + pos·(π/4)
L² + R² = d² 恒定  →  换边时总能量不动
```
配比换算（**别手改**）：`pos = 1 - 4·atan((1-b)/b)/π`；b=0.90 → pos=0.859 → ±19.1 dB。

**为什么 control signal 要离线算**：用户要求"每段随机时长"，而 ffmpeg 表达式里的 `random()` 无法表达分段随机 → 改由 numpy 离线生成整条控制曲线，写成 2ch f32le（200 Hz），再用 `amultiply` 乘上去（`build_pan_track()`）。相邻事件之间用余弦缓动插值。`PAN_SEED=20261008` 固定种子保证可复现。

**失败了的两个极端**：
- b=0.99（±39.9 dB）用户听后认为**太极端** → 回退 0.90。
- `pan` 滤镜**不支持表达式**，只能标量增益；时间相关声道控制必须走外部控制信号或 `volume:eval=frame`（表达式含逗号时要用单引号包起来）。

---

### 4.8 ★★ 换边时的「中心下压」：补偿双耳响度求和

> 这是本项目最值得单独成文的一节：**用户凭感觉提出的一个 20%，事后在心理声学文献里找到了完整依据。**

**现象**：同一个声音同时给两只耳朵听（居中 / diotic），比只给一只耳朵听（完全偏一侧 / monotic）更响。等功率法则只能配平**物理能量**，配不平**主观响度**。

**文献实测**（四条，**均已核验**，见附录 B）：

| 研究 | 方法 | 结论 |
|---|---|---|
| Zwicker & Zwicker 1991, JASA 89(2):756–764 | 数量估计 | ΔL=0 时双耳响度约为单耳的 **1.5 倍**，随 ILD 增大而衰减；在两耳间来回切换，切换变快时响度再涨约 **20%** |
| "Interaural correlation and loudness", JASA 119(5 Pt.2):3235 (2006) | 自适应匹配 | monotic 需比 diotic 高 **4.6 dB**（460–540 Hz 窄带）/ **6.5 dB**（100–900 Hz）/ **5.5 dB**（100–5000 Hz 宽带） |
| Moore, Gibbs, Onions & Glasberg 2014, JASA 136(2):736–747 | LDEL | **5.6 dB @500 Hz**、**4.2 dB @3–4 kHz**（听障被试；正常听力组同样约 5–6 dB） |
| Schlittenlacher, Ellermeier & Arseneau 2014, Atten Percept Psychophys | 简单反应时 | 1 kHz 纯音等反应时所需电平差 **≈ 5 dB** |

> ⚠️ **记录勘误**：早期笔记把 6.5 dB 归给了"宽带 100–5000 Hz"，实际摘要中 100–900 Hz 才是 6.5 dB，宽带 100–5000 Hz 是 **5.5 dB**。区间上下界不变，但引用时要标对。

**换算到本项目的取值**：
```
求和量        4.6 ~ 6.5 dB
− 等功率法则居中时每耳已降   3.0 dB
+ 极限位置主导耳本就有       0.05 dB
────────────────────────────
净需补偿                   1.6 ~ 3.5 dB   （中位 2.5 dB）
```
对应下压比例：`20·log10(1-PAN_DIP)` → **17% (−1.6 dB) / 25% (−2.5 dB) / 33% (−3.5 dB)**。
**用户凭听感猜的 20%（−1.94 dB）正好落在区间内偏保守的一端** → 直接采用，不推翻。

**实现方式**：下压权重 w 跟着**瞬时 ILD** 走，而不是跟着时间窗走。
```
x = |ILD(t)| / ILDmax ，  w = (0.5·(1 + cos(π·x)))^PAN_DIP_SHAPE
总增益 d_ctl = d_dist · (1 - PAN_DIP · w)
```
好处：停留期 |ILD| 恒为最大 → w ≡ 0，**完全不动**；只在真正穿越中心时出现凹陷；`shape=1` 时两端导数为 0，无折角无泵感。

**A/B 实测**（`[会话]`，dip=0 vs dip=0.20 同素材相除）：
| 位置 | Δ 增益 |
|---|---|
| 单侧停留区 | **+0.08 dB**（等于不动） |
| 穿越中心谷底 | **−1.87 dB**（理论 −1.94 dB） |
| 谷底宽度 | 约 1 s 平滑下压后恢复 |

> **方法论教训**：验证一个 0.68 s 的凹陷**不能用 1 s 窗**（会把它与两侧 ±19 dB 平均掉，永远测不到），必须用 0.1 s 窗。另外判断 dip 是否生效，最干净的做法是**两版直接相除**，且不要做"有声窗口"过滤——换边常常正好落在句间静音里，一过滤就被全滤掉。

---

### 4.9 左右支路增益校平

左路 EQ（婉）与右路 EQ（稍亮）本来就有能量差，导致"总音量"会随声场漂移周期性晃动。
`L_BRANCH_GAIN = 0.9589` 是拿 **600 秒真实语音实测**得出的校平值（左右差约 0.36 dB）。
> 换素材要重测，别沿用常量。

---

### 4.10 响度归一

官方 **loudnorm 两遍流程**：第一遍 `print_format=json` 只测量，结果缓存为 json；第二遍把 `measured_*` 喂回去跳过测量。目标 `I=-18 LUFS, TP=-2 dBTP, LRA=11`。
> **不推荐换成静态增益**（`--fast-norm`）：300 秒片段测是 8.19 s → 0.55 s（15 倍），但接上 1.2 GB 中间 wav 读写 + lame 编码后整片只差几秒（183 s vs 174 s，抖动反而更大），而静态版的 True Peak 保护要靠手动留余量，不如 loudnorm 自带 4× 过采样 TP 限幅稳。

---

### 4.11 自动质检：以 HNR 为判据

**标定**：合格气声素材全窗 HNR 最高 **−0.4 dB**；正常发声 **+7 dB**。中间空着 **8 dB**，因此阈值可以定死在 `LOUD_HNR_ABS = +2.0 dB`，无需逐句调。

**两级判据**（都要再叠加"音量高出 ≥3 dB"，**宁可漏不可滥**）：

| 判据 | 条件 | 治理目标 |
|---|---|---|
| **P1 中途变本音** | 连续 ≥2.5 s 的窗：HNR > +2 dB **且** 比本句常态响 ≥3 dB | 标签续航不足，后半句退回本音 |
| **P2 整句不是气声** | 整句 HNR 中位 > +2 dB **且** 整句比全批中位响 ≥3 dB | 标签压根没生效（句内很平，只看句内相对量会漏） |

- 全批中位响度由 `batch_ref()` 现算，这批实测 **−34.9 dB**；返工前后用同一把尺子复检。
- 870 句可用滑窗；30 句 ≤2 s 的短句（2~4 词）滑窗不足，单独用整句判据复核，实测全部合格。
- **结果**：命中 **4 句**（第 408 / 434 / 723 / 335 行），重录 + 压制后全部合格。

---

### 4.12 返工策略的实际取舍

原始设想：发现超标句就按 ≤6 词**重切重录**（每块各带一次标签）。
**实测否决**：第 434 行被切成 **10 块**，还切出 `"at"`、`"North"` 这类单词块——拼接感远大于那点音量差的收益。

**最终策略**：常规切分保连贯 + `duck_clip()` 本地包络压制保音量（纯 numpy，**零额度**）。全局只对 3 句生效。
> 这条是写明批判取舍"自动化返工未必优于最小干预"的好例子。

---

### 4.13 渲染加速：为什么 GPU 无效、以及如何从 10m51s 降到 3m20s

**用户问**：能否调用多核 / GPU 加速？
**结论**：**ffmpeg 音频滤镜全部没有 GPU 实现**。只有自写 numpy/CuPy 流水线才谈得上 GPU 加速，成本远超收益。

**profile 实测**（`scripts/profile_stage.py`，600 s 片段折算 106 min 全片）`[会话]`：
- 整条后处理链总耗时约 **4 分钟**
- 其中 **loudnorm 独占 63%**（14.4 s / 22.8 s）；atempo / EQ / aecho 都很便宜

**做法**：拆成两段
- **Stage A**（变速 / EQ / 回声 / 分路 / extrastereo）：与声像完全无关 → 切 **8 段并行**，产物长期缓存
- **Stage B**（声像 / 中心下压 / 响度归一 / mp3）：必须串行，约 **175~314 s**

| 环节 | 首次 | 之后（缓存命中） |
|---|---|---|
| rebuild_clips（534 句多块句） | ~6 min | 0（比 parts 新就跳过） |
| Stage A（8 段并行） | **24 s** | **0** |
| Stage B | 175 s | 175 s |
| **合计** | **10 min 51 s** | **3 min 20 s（3.3×）** |

配套：`write_index` 的 900 次串行 ffprobe 改成 json 缓存 + 16 路并行（原约 2 分钟）。
API 合成阶段已是 4 并发线程池，再提并发会被 ElevenLabs 429 限流卡住。

---

## §5 最终参数表（v13x12 定稿）

| 参数 | 值 | 含义 |
|---|---|---|
| `MODEL_ID` | `eleven_v4` | 促销期扣 0.28× 额度（v3 为 0.46×） |
| `DEFAULT_VOICE` | `nDJIICjR9zfJExIFeSCN` | Emmaline（英音年轻女声，公共库） |
| `STYLE_TAG` | `"[whispers] "` | 唯一显著生效的气声标签 |
| stability / similarity / style | 0.35 / 0.65 / 0.30 | 低 stab = 更像在演；低 sim = 让指令压过原音色 |
| `speed`（API） | 1.0（**不用它调速**） | 见 §4.6 |
| `TEMPO` | 1.15 | ffmpeg atempo，快 15% |
| `GAP_SEC` | 2.5 | 句间静音（成品实际值） |
| `NO_SPLIT_WORDS` / `CHUNK_WORDS` / `CHUNK_HARD` | 16 / 8 / 16 | 语义感知分块 |
| `CHUNK_XFADE` | 0.12 | 分块交叉淡化 |
| `PAN_BALANCE` | 0.90 | 极限配比 90:10 ≈ **±19.1 dB** |
| `PAN_SWAP_SEC` | 2.5 | 完全换边耗时（穿越中心 ±20 dB 区实测 1.73 s） |
| `PAN_HOLD_MIN/MAX` | 20 / 30 | 单侧停留随机区间 |
| `PAN_SEED` | 20261008 | 固定随机种子，保证可复现 |
| `PAN_DIP` / `PAN_DIP_SHAPE` | 0.20 / 1.0 | 中心下压（补偿双耳响度求和） |
| `DIST_DEPTH` | 0.10 | 远近起伏最大降幅 |
| `CTL_RATE` | 200 Hz | 控制信号采样率 |
| `L_BRANCH_GAIN` | 0.9589 | 左右支路校平（600 s 实测） |
| `LOUD_HNR_ABS` / `LOUD_EXCESS_DB` | +2.0 dB / +3.0 dB | 质检阈值 |
| loudnorm | I=−18 / TP=−2 / LRA=11 | 两遍流程 |

---

## §6 客观测量结果

**成品**（`audio/ICAO900_whisper_v13x12.mp3`）——以下数值均为 **2026-10-09 对最终成品文件的实测**，以 `ffprobe` + `ffmpeg ebur128=peak=true` 全曲测得：

| 指标 | 值 | 来源 |
|---|---|---|
| 时长 | **1:46:00.892**（6360.892 s，900 句完整） | `[实测]` ffprobe（2026-10-09 修复尾部截断后重测） |
| 声道 / 采样率 | **2.0 / 48 kHz** | `[实测]` |
| 编解码 / 码率 | mp3 / **256 kbps**（CBR） | `[实测]` |
| 体积 | 201,307,436 B ≈ **192 MiB / 201 MB** | `[实测]` |
| 综合响度 I | **−18.4 LUFS**（gating threshold −28.8 LUFS） | `[实测]` ebur128 |
| Loudness Range | **10.3 LU**（低 −27.3 / 高 −17.0 LUFS） | `[实测]` |
| True Peak | **−1.3 dBFS** | `[实测]` 4× 过采样 |

> ⚠️ 与早期记录的差异：会话笔记曾记为 −18.7 LUFS / −2.6 dBTP / LRA 12.0，那是中间版本或编码前的测量值。**论文应以本表的成品实测为准。**
> True Peak 目标设的是 −2 dBTP，成品实测 −1.3 dBFS——差值来自 **mp3 有损编码引入的样点重建过冲**，写 limitation 或讨论时值得提一句。

对照版本：

| 版本 | 时长 | 响度 / TP | 参数 |
|---|---|---|---|
| 清晰版 `ICAO900_ASMR.mp3` | 1:42:13 | −17.9 LUFS / −3.6 dBTP `[会话]` | Sarah 无标签 |
| 干声 `ICAO900_raw_mono.mp3` | 1:57:33 | 未处理 | 44.1 kHz 单声道，用于 A/B |
| 同速干声 `..._raw_mono_fast.mp3` | 1:42:13 | 仅 atempo 1.15 | 与成品**逐帧对齐**，可直接 A/B |

**声场验证**：
- 单侧停留 vs 穿越中心 A/B 差分：停留区 +0.08 dB、谷底 **−1.87 dB**（目标 −1.94 dB）
- 远近起伏实测 **−0.92 dB = 10.0%**（等于 `DIST_DEPTH`）
- 左/右分支增益差已校平至 0 dB

**完整性验证**：静音块计数 916 ≥ 900 句 → 无丢句、无串行 `[会话]`

---

## §7 工程陷阱清单（Lessons Learned）

> 这些是与"音频 ML pipeline 落地"高度相关的通用教训，适合作为论文附录或 engineering notes。

### 7.1 ffmpeg 专属

| # | 陷阱 | 现象 | 解法 |
|---|---|---|---|
| 1 | **`atempo` 不能分段跑** | 内部处理窗口对齐到 4096/2048 采样 → 每个接缝错位 **40~85 ms**（听得见的"咔"） | 把 `aresample + atempo` 提到公共前置段**整段做一次**（全片约 3 s），之后的时间轴即成品时间轴，剩下的 FIR/IIR/delay/gain 可任意切 |
| 2 | **`-ss` 落在 mp3 上** | 即使加 `-accurate_seek` 也漂几十采样 | 前置段先把源转成 PCM 再 seek，用 `-frames:a N` 做采样级精确截断 |
| 3 | **`equalizer` 的 `t=q` 时 `w` 是 Q 值不是 Hz** | 写错会变成极窄带，几乎无效果 | 明确区分 `t=h`（Hz）/ `t=q`（Q） |
| 4 | **`rubberband` 升调必须加 `formant=1`** | 默认 `formant=0` 时共振峰跟着抬 → 花栗鼠 | 补 `formant=1`；但仍然救不了"变年轻"（见 §4.2） |
| 5 | **`pan` 滤镜不支持表达式** | 只能标量增益 | 时间相关声道控制走外部控制信号 + `amultiply`，或 `volume:eval=frame` |
| 6 | `volume` 表达式含逗号 | 报错 | 写成 `volume='expr':eval=frame`，单引号包裹 |
| 7 | `aresample` 无 `resampler=linear` | 直接报错 | 有效值只有 `swr` / `soxr` |

### 7.2 Python / 并发 / 环境

| # | 陷阱 | 现象 | 解法 |
|---|---|---|---|
| 1 | **`_encode_f32` 用固定路径临时文件** | 4 并发互相覆盖同一个 raw → 首轮全量**随机丢 47 句**（全是多块句，每次丢的不一样） | 最终改为 **stdin 管道**（`-i pipe:0` + `communicate()`），彻底不用临时文件 |
| 2 | **`os.remove` 触发安全删除守卫** | 累计几十次后整个 post 崩溃，`try/except` 挡不住 | 同上：不产生临时文件 |
| 3 | **`shutil.rmtree` 被批量删除保护拦住** | 每句都弹 `[safe-delete]` 告警，累计还 timeout | 能不删就不删：直接写 parts 目录，省掉 tmp + copy |
| 4 | **bash 的 `rm` 不可靠** | `rm -f .cache/clips/*.mp3` 报 Argument list too long | 一律用 Python `shutil.rmtree` |
| 5 | **manifest 键名不一致** | `set_part_count` 存 `"408"`，文件名是 `0408_00.mp3` → 清单失效，返工后旧块被拼回来 | 改成**文件名清单**（键统一 `%04d`）+ 写入批次 mtime 重建防旧块串入 |
| 6 | **Windows 下 Python 与 Git Bash 看到的 `/tmp` 不是同一个** | ffmpeg 生成成功但 Python 读不到 | 中间文件一律落到项目自己的 `.cache/` 下并用绝对路径 |
| 7 | 源文件是 **GB18030** 不是 UTF-8 | 乱码 | normalize.py 首行即以 GB18030 读入 |
| 8 | `post` 模式 `fail` 未定义 | 单独跑 post 时 2 秒就退出（该变量只在 sample/all 分支赋值） | main 里先 `fail = []` 兜底 |

### 7.3 ElevenLabs API

| # | 事项 |
|---|---|
| 1 | **Voice Design**（`/v1/text-to-voice/create-previews`）在 Creator 计划 **403**；且样本文本需 ≥100 字符 → 不可用 |
| 2 | 添加公共音色：`POST /v1/voices/add/{public_owner_id}/{voice_id}`，body 必须是 JSON `{"new_name":...}`；用 query 参数会 411/422（411 = 网关要 Content-Length）。返回的 voice_id 与公共 ID 相同 |
| 3 | 社区克隆音色**可以直接跑 eleven_v3/v4**，无需降级 |
| 4 | 叠加两个表演标签会**覆盖**而非叠加（`[whispers][close-mic]` 反而失效） |
| 5 | `voice_settings.speed` 不可靠（§4.6） |
| 6 | 单句合成有 ±10% 时长抖动、气声强度抖动近 6 倍（§4.3） |

### 7.4 测量方法论（最容易得出错误结论的地方）

1. **别用粉噪的 50 ms 窗 max−min 判断音量稳定性**——噪声自身就有 **9.7 dB** 抖动。
   正确做法：同一素材分别渲染"恒定居中"与"随机声像"两版，**逐窗相减**隔离净调制，同时剔除近静音窗（沉默处 dB 比值会炸出 −10 dB 假值）。
2. 验证短时凹陷**窗口必须小于凹陷本身**（0.68 s 的凹陷要用 0.1 s 窗）。
3. A/B 差分比绝对值更可靠；差分时**不要做有声窗口过滤**。

---

## §8 复现手册

```bash
ROOT="E:/Program Files/WorkBuddyProjects/icao900-asmr"; cd "$ROOT"

# 0) 文本层（产出 01/02/03 三个文本，一般不重跑）
python scripts/normalize.py

# 1) 先出 8 句样音试听
python scripts/tts_generate.py sample --tag "[whispers] " --voice nDJIICjR9zfJExIFeSCN

# 2) 全量 900 句（4 并发，断点续传；约 23 分钟，消耗约 31k 字符）
python scripts/tts_generate.py all --tag "[whispers] " \
       --clips clips_v13x12 --name whisper_v13x12 --key <API_KEY>

# 3) 质检（宽松模式，宁可漏不可滥）
python scripts/tts_generate.py check --clips clips_v13x12

# 4) 返工命中的句子 → 压制 → 重录（脚本内部集成）
# 5) 整合 + 后处理
python scripts/tts_generate.py post --clips clips_v13x12 --name whisper_v13x12 \
       --xfade 0.12 --pan-balance 0.90 --pan-dip 0.20 --pan-swap 2.5 --pieces 8

# 6) 声场体检
python scripts/verify_pan.py
```

常用 CLI 开关：

| 开关 | 作用 |
|---|---|
| `--tag` | 表演指令，如 `"[whispers] "` |
| `--clips` / `--name` | 版本隔离：换目录即换版本，互不覆盖 |
| `--tempo` / `--voice` | 覆盖全局常量 |
| `--xfade` | 分块交叉淡化时长（改它不重合成） |
| `--pan-balance` / `--pan-swap` / `--pan-dip` / `--pan-dip-shape` | 声场参数 |
| `--pieces` | Stage A 并行段数（默认 8） |
| `--remeasure` / `--loudnorm` / `--fast-norm` | 响度归一控制 |
| `--force-stage-a` | 强制重算 Stage A |

**可复现性保证**：所有随机性（`PAN_SEED`）固定；中间产物带 meta json 缓存，命中即跳过；loudnorm 的 measure 结果落盘，第二遍直接复用。

---

## §9 若日后撰写论文：章节映射建议

| 论文章节 | 取用本文档 | 现有强度 | 需补什么 |
|---|---|---|---|
| Introduction（为何要做睡眠期听觉磨耳） | §1 | ⚠️ 弱 | **睡眠期学习的边界条件**需要文献支撑（见 §10） |
| Related Work：神经 TTS 的表演控制 | §4.3、4.4 | 中 | 补几篇 expressive TTS / audio tag steering 的正式论文 |
| Related Work：空间音频与响度 | §4.7、4.8 | **强**（四条文献已核验） | 可补 Loudness Model (Moore & Glasberg 2007) 原文 |
| Method：文本规范化 | §4.1 | 强 | 可附规则命中统计表 |
| Method：气声控制 | §4.3、4.4、4.11 | 强 | — |
| Method：空间后处理 | §4.7~4.10 | 强 | 画一张声场控制曲线图（已有数据） |
| Design Study：人机协同迭代 | **§2** | **强（最有特色）** | 把 15 轮反馈整理成正式表格 |
| Experiments | §6 | 中 | 缺主观听测（最大短板，见 §10） |
| Engineering Notes | §7 | 强 | 可直接作为附录 |
| Conclusion | §0 | — | 待写 |

**可立刻画的图**（数据在本文档里都有）：
1. 流水线框图（§3）
2. 15 轮迭代收敛图（x=轮次，y=用户满意度/否；标注每次的技术响应）
3. 真人气声 vs 正常发声的频谱差 + `[whispers]` 标签的频谱差（**两条曲线方向相反**）——这张图最有说服力
4. 声场控制曲线：L(t)/R(t) 增益 + 总增益（含中心下压凹陷）
5. HNR 分布直方图：合格气声 vs 正常发声，标出 +2.0 dB 阈值两侧的 8 dB 空档
6. Stage A/B 分段渲染耗时对比柱状图

---

## §10 已知缺陷与**写论文前必须补的实验**（诚实清单）

1. **🔴 没有任何正式主观评价实验。** 全部结论来自**单一被试（用户本人）的非受控听感反馈**，无 n、无盲听、无统计检验。
   → 若要写成研究论文，至少要做：n≥15 的偏好二选一（forced choice）或 MUSHRA；评价维度建议：① 气声真实度 ② 年轻感 ③ 空间自然度 ④ 换边是否可被察觉为"响度变化"（检验 PAN_DIP 效果）⑤ 长时间聆听疲劳度。
2. **🔴 没有做「双耳响度补偿是否真的有效」的听测。** `PAN_DIP=0.20` 目前只有**工程侧的差分证据（−1.87 dB）**，没有心理声学验证。这是 §4.8 最需要补的一环：做一个"在随机时刻切换声道，让被试在 dip=0 / 0.17 / 0.20 / 0.25 / 0.33 中选最平稳者"的自适应匹配实验，理论上应收敛到中位。
3. **🟡 §4.3 的真人录音分析结果（HNR 1.8→−4.3 dB、谱质心 581→2052 Hz）来自用户自己的一段录音（n=1）**，代表性有限。要发表需更多说话人。
4. **🟡 「睡眠学习效果」从未验证。** 本项目只验证了"做出符合条件刺激"（the stimulus is acceptable），**没有验证"睡着真的能学到东西"**。写论文时必须明确这项工作只是**素材制备**，不能暗示提升学习效率。
   → 若想扩展，需做：睡前暴露组 vs 对照组的事后回忆测试，且必须引用睡眠期学习（sleep-learning / targeted memory reactivation）的争议文献——该领域对"睡眠中能否形成新的陈述性记忆"尚无共识。
5. **🟡 ElevenLabs 是黑盒商业 API**：模型版本、训练数据、随机种子均不可控，且 §4.3 指出单次合成抖动达 6 倍。任何以它做的实验都应在 limitation 里明写复现性风险。
6. **🟡 iversion=段的 ICE 发音规则只覆盖了这个语料看到的模式**，未做穷尽性测试（`03_review_diff.md` 记录了可疑 token）。
7. **🟢 额度/成本数据**会过期（Creator 套餐、促销 0.28× 倍率都有期限），引用前需重新确认。

---

## 附录 A：产物与文件清单

**交付物（根目录）**

| 文件 | 说明 |
|---|---|
| `audio/ICAO900_whisper_v13x12.mp3` | **最终成品**（气声悄悄话版） |
| `audio/ICAO900_ASMR.mp3` | 清晰版（对照） |
| `audio/ICAO900_raw_mono.mp3` / `..._fast.mp3` | 干声 / 同速干声（用于 A/B，与成品逐帧对齐） |
| `05_timestamps_whisper_v13x12.txt` | 成品时间戳目录，900 行可定位 |
| `01_sentences_clean.txt` / `02_tts_icao.txt` | 清洗文本 / TTS 输入 |
| `03_review_diff.md` | 规范化核查报告 |
| `PROJECT.md` | 项目规范与进度 |
| **`docs/TASK_ARCHIVE.md`** | 本档案 |

**中间产物**（`.cache/`，非交付）

| 路径 | 内容 |
|---|---|
| `clips_v13x12/` | 900 个整句 clip |
| `clips_v13x12_parts/` | 多块句原始分块（534 句） + `_manifest.json`（文件名清单） |
| `clips_v13x12_duck/` | 被压制的句子（408/434/723） |
| `prepared.wav` | 整段 atempo 后的 PCM（成品时间轴） |
| `stage_a_<tag>.wav` | Stage A 产物（长期缓存） |
| `ffmpeg.exe` | ffmpeg 9.0.2 |

**探针 / 对比素材**（`audio/`，可作为论文图表素材）
`voice_compare.mp3`（5 种配置）· `thousand_probe.mp3` · `eight_probe.mp3` · `whisper_breath_AB.mp3` · `whisper_soft_AB.mp3` · `kid_compare.mp3` · `fav_compare.mp3` · `hold_s1_vs_s7.mp3` · `sample_s16x06.mp3` / `sample_s16x12.mp3` / `sample_v13x12.mp3`

**脚本**（`scripts/`）
`normalize.py`（文本）· `tts_generate.py`（主流水线）· `analyze_breath.py` / `match_breath.py`（气声分析）· `verify_pan.py`（声场体检）· `profile_stage.py`（滤镜基准）· 其余 `whisper_*` / `*probe*.py`（音色迭代对比）

---

## 附录 B：参考文献（**已逐条核验**，2026-10-09）

> ⚠️ 以下四条为写 §4.8 依据。若日后补 §10 的睡眠学习文献，**必须重新检索核验**，不得沿袭记忆。

1. **Zwicker, E., & Zwicker, U. T. (1991).** Dependence of binaural loudness summation on interaural level differences, spectral distribution, and temporal distribution. *Journal of the Acoustical Society of America*, 89(2), 756–764. DOI: **10.1121/1.1894635** ｜ PMID: **2016430**
   → 关键数据：ΔL=0 时双耳响度约为单耳的 1.5 倍，随 ΔL 增大而衰减，与频率/声级/频谱形状无关；实验三显示两耳间来回切换，切换频率提高时响度再涨约 20%。

2. **Interaural correlation and loudness (2006).** *Journal of the Acoustical Society of America*, 119(5, Pt. 2), 3235.（ASA 会议摘要）
   → 关键数据：自适应匹配下，diotic 与 monotic 等响所需电平差为 **4.6 dB**（460–540 Hz 窄带）/ **6.5 dB**（100–900 Hz）/ **5.5 dB**（100–5000 Hz 宽带）。
   → 相关正式论文：**Edmonds, B. A., & Culling, J. F. (2009).** Interaural correlation and the binaural summation of loudness. *JASA*, 125(6), 3865–3870.（写论文时优选这条作为引用）

3. **Moore, B. C. J., Gibbs, A., Onions, G., & Glasberg, B. R. (2014).** Measurement and modeling of binaural loudness summation for hearing-impaired listeners. *Journal of the Acoustical Society of America*, 136(2), 736–747. DOI: **10.1121/1.4889868** ｜ PMID: **25096108**
   → 关键数据：LDEL = **5.6 dB @500 Hz**、**4.2 dB @3–4 kHz**（听障被试）。注意：这是**听障**群体数据，正常听力组亦约 5–6 dB。

4. **Schlittenlacher, J., Ellermeier, W., & Arseneau, J. (2014).** Binaural loudness gain measured by simple reaction time. *Attention, Perception, & Psychophysics*, 76(5), 1407–1419.（在线 2014-05-08）DOI: **10.3758/s13414-014-0651-1** ｜ PMID: **24806401**
   → 关键数据：1 kHz 纯音，45–85 dB SPL，等反应时所需双耳电平差（BLDERT）**≈ 5 dB**。

**延伸（尚未核验，引用前需查）**：Moore, B. C. J., & Glasberg, B. R. (2007). Modeling binaural loudness. *JASA*, 121(3), 1604–1612. ——多条文献用其作为"diotic 约为 monotic 1.5 倍"的理论依据，写 Discussion 时值得引用。

---

*档案结束。若内容有更新，请连同日期一并追加，不要覆盖历史版本。*
