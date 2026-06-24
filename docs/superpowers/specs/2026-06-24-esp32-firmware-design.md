# ESP32-S3 AI Companion Runtime 固件设计规格

> 日期: 2026-06-24  
> 状态: 设计完成，待审批  
> 关联项目: AI Companion Runtime (后端 + 前端)

---

## 1. 概述

### 1.1 目标

将 AI Companion Runtime 部署到 ESP32-S3 小智扩展板硬件上，实现语音优先的 AI 情绪陪伴设备。

### 1.2 硬件规格

| 项目 | 规格 |
|------|------|
| 芯片 | ESP32-S3 (Xtensa LX7, 240MHz) |
| 显示 | ST7789 SPI LCD, 240×320 竖屏, 无触摸 |
| 音频输入 | MEMS 麦克风, I2S SIMPLEX RX, 16kHz 16bit 单声道 |
| 音频输出 | 3W 扬声器, I2S SIMPLEX TX |
| USB | CH340 串口 |
| 按键 | GPIO0 (长按 3 秒进入 WiFi 配网) |
| Flash | 16MB |
| PSRAM | 8MB |

### 1.3 架构原则

- **薄客户端模式**: ESP32 负责 UI 渲染、音频采集/播放、网络通信；所有 AI 逻辑跑在云端后端
- **语音优先**: 主要交互方式为语音，屏幕为辅助显示
- **离线可用**: 时钟、定时器、任务清单等本地功能断网可用
- **复用后端协议**: WebSocket 消息类型完全复用现有后端 8 种消息

---

## 2. 交互模型

### 2.1 状态机

```
SLEEP ──"小智小智"──▶ ACTIVE (5分钟窗口)
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
         语音对话      TTS播放中      后台定时器
        (持续对话)    (说完继续听)   (闹钟/倒计时)
            │             │             │
            └─────────────┼─────────────┘
                          │
                 5分钟无对话 → SLEEP
```

### 2.2 状态行为

| 状态 | 屏幕 | WebSocket | 麦克风 |
|------|------|-----------|--------|
| SLEEP | 时钟屏, 低亮度 | 断开 (节省功耗) | VAD 持续监听 |
| ACTIVE | 按场景切换屏幕 | 保持连接 | 对话中持续录音 |

### 2.3 触发规则

- **唤醒**: 喊"小智小智" → L1 本地 VAD 检测人声 → 2 秒音频片段发云端 ASR → 文本匹配"小智" → 激活
- **休眠**: 5 分钟内无任何语音交互 → 自动进入 SLEEP
- **手动休眠**: 说"小智睡觉"或"小智休息"提前进入 SLEEP
- **5 分钟计时器**: 每次语音输入或 TTS 播放完成时重置

---

## 3. 屏幕导航

### 3.1 界面层级

```
┌──────────────────────────────────────┐
│  STATUS BAR  (WiFi / 电池 / 时间)     │  ← 固定 20px
├──────────────────────────────────────┤
│                                      │
│         主内容区 (300px)              │  ← 各屏内容
│                                      │
├──────────────────────────────────────┤
│  底部提示 / 快捷操作 (可选)            │  ← 按需显示
└──────────────────────────────────────┘
```

### 3.2 7 个屏幕

| 屏 | 文件名 | 触发方式 | 说明 |
|----|--------|---------|------|
| CLOCK | screen_clock.c | 默认/SLEEP状态 | 大数字时钟 + 日期 + 天气图标 + 情绪色条 |
| LISTENING | screen_listen.c | 唤醒后自动 | 脉冲光环 + 波形动画 + "正在听..." |
| SPEAKING | screen_speak.c | 收到 first_reply 后 | AI 回复文字流式显示 + 情绪标签 + 光标 |
| TIMER | screen_timer.c | 语音"设闹钟" | 闹钟/倒计时列表 + 开关状态 |
| TASKS | screen_tasks.c | 语音"看任务" | 任务清单 + 勾选状态 |
| RISK ALERT | screen_risk.c | 后端 risk_alert (high/critical) | 全屏警告 + 热线信息 |
| WIFI CONFIG | screen_wifi.c | 长按GPIO0 3秒 | AP 模式 + QR 码 + 连接指引 |

### 3.3 自动切换流程

```
CLOCK ──唤醒词──▶ LISTENING ──ASR完成──▶ SPEAKING ──TTS结束──▶ CLOCK
```

### 3.4 视觉风格

- **主题**: 暗色 (#0F1117 背景), AI 陪伴感, 大字体
- **强调色**: 暖橙色 #FF9500 (主色), 柔和蓝 #5AC8FA (辅助, 情绪/天气)
- **字体**: LVGL 大字库, 中文 16-48px, emoji 混排
- **元素**: 圆角面板, 柔和阴影, 脉冲/波形 CSS 动画

---

## 4. WebSocket 协议适配

### 4.1 固件 → 后端

| 消息类型 | Payload | 触发时机 |
|---------|---------|---------|
| `auth` | `{token, device_id}` | WebSocket 连接建立后立即发送 |
| `message` | `{"type":"text","content":"..."}` | 语音 ASR 转文字后 |
| `ping` | `{}` | 每 30 秒保活 |

### 4.2 后端 → 固件 (消费的消息类型)

| 消息类型 | 固件处理 |
|---------|---------|
| `trace` | 记录 trace_id, 不显示 |
| `risk_alert` | high/critical → 强制切 RISK ALERT 屏 |
| `first_reply` | 切 SPEAKING 屏, 触发 TTS 播放 |
| `delta` | 追加显示文字, 流式渲染 |
| `tool_status` | 显示小字提示 (如"正在查天气...") |
| `final` | 标记消息完成, 显示延迟 + 工具摘要 |

### 4.3 消息流

```
auth → trace → risk_alert(可选) → first_reply → delta... → tool_status(穿插) → final
```

### 4.4 定时器/任务的结构化指令

后端 intent_engine 识别意图后通过 `tool_status` 返回结构化参数:

```json
{
  "tool": "timer_create",
  "status": "done",
  "params": {
    "type": "alarm",
    "label": "起床",
    "target_time": 1719298800,
    "repeat": "once"
  }
}
```

固件解析 `params` 后执行本地 NVS 存储 + FreeRTOS 定时器注册。

---

## 5. 音频管线

### 5.1 整体数据流

```
MEMS麦克风 → I2S RX 16kHz 16bit → 环形缓冲(5秒) → HTTP POST → 云端ASR(阿里/百度)
                                                              │
                                                          文本结果
                                                              │
                                                              ▼
                                                        WebSocket → 后端
                                                              │
                                                         文字回复
                                                              │
                                                              ▼
扬声器 ← I2S TX ← 双缓冲乒乓解码 ← 分段MP3 ← HTTP GET ← 云端TTS(火山/讯飞)
```

### 5.2 ASR (语音识别)

- **方案**: 固件 HTTP 直连云 ASR (方案 C)
- **格式**: 一句话识别, 16kHz 16bit PCM, 最大 5 秒
- **静音截断**: 1.5 秒无声 → 自动截断发 ASR
- **备选**: 后端不做 ASR, 固件完全自治

### 5.3 唤醒词检测

| 层 | 方案 | 延迟 |
|----|------|------|
| L1 本地 VAD | ESP-IDF esp_audio 内置 VAD | <10ms |
| L2 云端校验 | 2 秒音频片段 → 云端 ASR → 关键词匹配 "小智" | ~500ms |

- L1 持续监听, 检测到人声 → 录 2 秒发 L2 校验
- L2 确认包含"小智" → 激活 ACTIVE, 剔除唤醒词后的内容作为首条消息
- 未检测到人声 → 丢弃片段, 继续监听

### 5.4 TTS (语音合成)

- **方案**: 固件 HTTP 直连云 TTS (方案 C1, 推荐)
- **格式**: 流式 MP3 分段, 双缓冲乒乓播放
- **首音节延迟**: <300ms (收到第一段即播放)
- **解码**: 固件 libmad / helix MP3 解码 → I2S TX

### 5.5 后端改动

仅一个轻量 TTS 模块 (如果用方案 C2), 或者 0 改动 (方案 C1)。其他模块完全复用。

---

## 6. 定时器与任务系统

### 6.1 数据模型

#### Timer (定时器)

```
Timer {
  id: uuid (uint32 简化)
  type: "alarm" | "countdown" | "reminder"
  label: string (最长 32 字节)
  target_time: unix_ts (alarm/reminder 的绝对时间)
  duration_sec: uint16 (countdown 倒计时秒数)
  repeat: "once" | "daily" | "weekdays" | "custom"
  days: uint8 bitmask (custom 模式, bit0=周日...bit6=周六)
  sound: uint8 (铃声索引 0-4)
  enabled: bool
}
```

#### Task (任务)

```
Task {
  id: uuid (uint32 简化)
  content: string (最长 64 字节)
  done: bool
  created_at: unix_ts
  due_date: unix_ts | null
  priority: 0=low | 1=normal | 2=high
}
```

### 6.2 存储

- **存储介质**: NVS (Non-Volatile Storage)
- **容量**: 最多 16 个定时器 + 32 个任务 (足够日常使用)
- **键名**: `timer_0` ~ `timer_15`, `task_0` ~ `task_31`，均为 blob

### 6.3 触发机制

- **闹钟/提醒**: 每天凌晨计算当天的触发时间 → 注册 FreeRTOS 单次软件定时器
- **倒计时**: 收到指令后立即注册 FreeRTOS 定时器 (精确到秒级)
- **到期表现**: 无论 SLEEP/ACTIVE, 强制响铃 + 屏幕亮起 + 显示到期卡片
- **停止**: 按 GPIO0 按钮停止响铃

### 6.4 重复规则

- `once`: 触发后自动禁用
- `daily`: 每天触发，永不过期
- `weekdays`: 周一至周五触发
- `custom`: 按 days bitmask 计算下一个触发日

### 6.5 创建方式 (全语音)

| 语音 | 操作 |
|------|------|
| "小智，明天早上七点叫我" | 创建 alarm |
| "小智，倒计时三分钟" | 创建 countdown |
| "小智，每周一到周五早上八点提醒我吃药" | 创建 reminder (repeat:weekdays) |
| "小智，把买菜加到任务" | 创建 task |
| "小智，买菜完成了" | 标记 task done |
| "小智，删除闹钟" | 删除对应 timer |

---

## 7. 固件目录结构

```
firmware/
├── main/
│   ├── CMakeLists.txt
│   ├── main.c                    # 启动入口, FreeRTOS 任务创建
│   ├── idf_component.yml
│   ├── Kconfig.projbuild
│   │
│   ├── ui/
│   │   ├── ui_manager.h/c        # LVGL 初始化, 屏切换管理
│   │   ├── screens/
│   │   │   ├── screen_clock.c    # CLOCK 屏: 时间/日期/天气/情绪
│   │   │   ├── screen_listen.c   # LISTENING 屏: 脉冲动画
│   │   │   ├── screen_speak.c    # SPEAKING 屏: 文字流式+光标
│   │   │   ├── screen_timer.c    # TIMER 屏: 定时器列表
│   │   │   ├── screen_tasks.c    # TASKS 屏: 任务清单
│   │   │   ├── screen_risk.c     # RISK ALERT 屏: 风险告警
│   │   │   └── screen_wifi.c     # WIFI CONFIG 屏: 配网页+QR
│   │   ├── widgets/
│   │   │   ├── clock_face.c      # 数字时钟
│   │   │   ├── emotion_bar.c     # 情绪条
│   │   │   ├── wave_anim.c       # 波形动画
│   │   │   └── qr_display.c      # QR 码
│   │   └── styles.c/h            # 全局样式/主题
│   │
│   ├── audio/
│   │   ├── mic.c/h               # I2S RX 麦克风采集
│   │   ├── speaker.c/h           # I2S TX 扬声器播放
│   │   ├── vad.c/h               # 本地 VAD 检测
│   │   └── tts_client.c/h        # 云端 TTS HTTP 客户端
│   │
│   ├── network/
│   │   ├── wifi_manager.c/h      # WiFi 连接 + NVS 凭证
│   │   ├── wifi_ap.c/h           # AP 配网页 + Captive DNS
│   │   ├── ws_client.c/h         # WebSocket 客户端
│   │   ├── asr_client.c/h        # 云端 ASR HTTP 客户端
│   │   └── http_utils.c/h        # HTTP 公共工具
│   │
│   ├── app/
│   │   ├── chat_controller.c/h   # 对话状态机 SLEEP/ACTIVE/5min
│   │   ├── clock_controller.c/h  # SNTP 同步 + RTC 管理
│   │   ├── timer_manager.c/h     # 定时器 CRUD + FreeRTOS
│   │   ├── task_manager.c/h      # 任务 CRUD + NVS
│   │   ├── emotion_display.c/h   # 情绪 → UI 映射
│   │   └── settings.c/h          # NVS 设置读写
│   │
│   └── utils/
│       ├── nvs_helper.c/h        # NVS 封装
│       ├── ring_buffer.c/h       # 环形缓冲
│       └── time_utils.c/h        # 时间格式化/星期计算
│
├── sdkconfig.defaults            # ESP-IDF 默认配置
├── partitions.csv                # 分区表
└── CMakeLists.txt                # 顶层 CMake
```

---

## 8. 开发计划 (4 阶段)

### P1 - 基础 (8 个文件)
**产出**: 屏幕亮起 + 连接 WiFi + 显示时间

| 文件 | 职责 |
|------|------|
| main.c | 启动入口, 初始化各模块 |
| wifi_manager.c/h | STA 模式连接 + NVS 凭证 |
| wifi_ap.c/h | AP 配网模式 (已有, 复用) |
| clock_controller.c/h | SNTP 同步, RTC 管理 |
| ui_manager.c/h | LVGL 初始化, 屏切换框架 |
| screen_clock.c | CLOCK 屏实现 |
| styles.c/h | 全局主题/颜色/字体 |
| nvs_helper.c/h | NVS 读写封装 |

### P2 - 通信 (9 个文件)
**产出**: 语音对话闭环 (ASR → WS → TTS → 播放)

| 文件 | 职责 |
|------|------|
| ws_client.c/h | WebSocket 连接/消息/重连 |
| asr_client.c/h | 云端 ASR HTTP |
| tts_client.c/h | 云端 TTS HTTP |
| http_utils.c/h | HTTP 公共封装 |
| mic.c/h | I2S RX 麦克风 |
| speaker.c/h | I2S TX 扬声器 |
| vad.c/h | 本地 VAD |
| screen_listen.c | LISTENING 屏 |
| screen_speak.c | SPEAKING 屏 |
| chat_controller.c/h | SLEEP/ACTIVE 状态机 |

### P3 - 工具 (8 个文件)
**产出**: 闹钟/倒计时/任务全功能

| 文件 | 职责 |
|------|------|
| timer_manager.c/h | 定时器 CRUD + FreeRTOS 定时器 |
| task_manager.c/h | 任务 CRUD + NVS |
| screen_timer.c | TIMER 屏 |
| screen_tasks.c | TASKS 屏 |
| ring_buffer.c/h | 环形缓冲 |
| time_utils.c/h | 时间工具 |
| clock_face.c | 时钟控件 |
| wave_anim.c | 波形动画 |

### P4 - 完善 (9 个文件)
**产出**: 全功能交付

| 文件 | 职责 |
|------|------|
| emotion_bar.c | 情绪色条 |
| emotion_display.c/h | 情绪 → UI |
| screen_risk.c | RISK ALERT 屏 |
| screen_wifi.c | WIFI CONFIG 屏 |
| qr_display.c | QR 码控件 |
| settings.c/h | 全局设置 |
| partitions.csv | Flash 分区表 |
| sdkconfig.defaults | 默认配置 (复用+扩展已有) |
| CMakeLists.txt | 顶层构建 |

---

## 9. 边界条件与错误处理

### 9.1 网络异常

| 场景 | 处理 |
|------|------|
| WiFi 断连 | 自动重连 (指数退避 1s/2s/4s/8s...最大 60s) |
| WebSocket 断连 | SLEEP 状态下不重连, ACTIVE 状态下重连 |
| ASR 请求超时 | 5 秒超时 → 显示 "没听清，请再说一次" |
| TTS 请求超时 | 降级显示纯文字 (无语音播报) |
| 完全离线 | 所有本地功能正常 (时钟/定时器/任务), UI 显示离线图标 |

### 9.2 资源限制

| 资源 | 限制 | 处理 |
|------|------|------|
| 定时器 | 最多 16 个 | 超过提示 "闹钟已满" |
| 任务 | 最多 32 个 | 超过提示 "任务已满" |
| NVS 空间 | ~24KB 可用 | 启动时检查, 低空间告警 |
| 环形缓冲 | 5 秒 / 160KB | 溢出时丢弃最旧数据 |

### 9.3 安全

| 项目 | 措施 |
|------|------|
| WebSocket | TLS (wss://), 证书固定在固件中 |
| ASR API Key | 存储在 NVS, 不在代码中硬编码 |
| TTS API Key | 同上 |
| WiFi 凭证 | NVS 加密分区存储 |
| 后端 JWT | 固件不存 JWT, 每次通过 token endpoint 获取短期 token |

---

## 10. 与后端的接口边界

固件与后端之间通过 WebSocket + HTTP 通信, **接口边界清晰**:

| 固件 → 后端 | 后端 → 固件 |
|-------------|-------------|
| WebSocket `auth` | WebSocket `trace` |
| WebSocket `message` | WebSocket `risk_alert` |
| WebSocket `ping` | WebSocket `first_reply` |
| (HTTP ASR — 固件自调) | WebSocket `delta` |
| (HTTP TTS — 固件自调) | WebSocket `tool_status` |
| | WebSocket `final` |

后端无需感知固件的 ASR/TTS 实现, 也不需要感知固件的本地定时器/任务存储。后端只关注对话逻辑, 固件处理所有硬件和本地状态。
