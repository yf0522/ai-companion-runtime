# Elder Companion Pivot — Design Spec

**Date**: 2026-06-15
**Scope**: Pivot from "emotional companion" to "elderly companion" + recurring reminder system + family management

## 1. Target User

**独居老人**：子女不在身边，需要日常聊天解闷、生活提醒、健康异常检测。设备端为 ESP32-S3-BOX-3（语音交互），子女通过管理后台远程查看/管理。

**用户角色**：
- `elder`：老人，使用设备端语音交互
- `family`：子女，通过 Web/API 管理提醒、查看风险通知

## 2. Personality Overhaul

### 2.1 Base Personality (`personality.yaml`)

| 属性 | 值 |
|------|-----|
| name | 默认陪伴 |
| tone | 温暖、耐心、清晰、慢节奏 |
| max_length | 120 字（默认），紧急情况不限 |

**style_rules**:
- 句子短，一句一个意思，不用长从句
- 不用网络流行语、英文缩写
- 禁止"您老"、"老人家"等居高临下称呼
- 像晚辈一样自然说话，可以称呼"叔叔/阿姨"（可在 profile 自定义）
- 重要信息主动重复确认
- 主动关心身体、饮食、睡眠

### 2.2 Adaptation Rules

| 规则 | 触发条件 | 语气调整 |
|------|---------|---------|
| `loneliness_high` | emotion=loneliness AND intensity>0.5 | 多聊几句，问今天做了什么，回忆开心的事 |
| `confusion` | 用户重复问同一问题，或表示"记不清" | 耐心重复，不表现不耐烦，语速更慢 |
| `health_concern` | intent=health_concern | 关切询问，建议就医，不给具体医疗建议 |
| `fatigue_high` | emotion=fatigue AND intensity>0.7 | 建议休息，不啰嗦 |
| `joy_high` | emotion=joy AND intensity>0.7 | 分享快乐，轻松互动 |
| `task_mode` | intent=task OR intent=reminder_request | 简洁高效，确认后执行 |

### 2.3 Emotion Engine Changes

**新增情绪类别**：
- `loneliness`：patterns = ["一个人", "没人", "孤独", "寂寞", "冷清", "好久没人来", "孩子不来"]
- `confusion`：patterns = ["记不清", "忘了", "刚才说什么", "搞不懂", "不会用"]

**保留现有**：sadness, joy, anger, anxiety, fatigue, fear

### 2.4 Intent Engine Changes

**新增意图类型**：
- `health_concern`：patterns = ["头疼", "胸闷", "喘不上气", "摔倒", "血压高", "血糖", "不舒服", "疼", "痛"]
- `reminder_request`：patterns = ["提醒我", "帮我记着", "别忘了提醒", "定个闹钟", "每天.*点"]

**tool_needs 映射**：
- `reminder_request` → `reminder` tool

## 3. Risk Engine Overhaul

### 3.1 Risk Categories

**替换现有 self_harm 为三类**：

#### critical（立即行动）
- **category**: `health_emergency`
- **keywords**: "胸口疼", "喘不上气", "摔倒了站不起来", "头晕眼前发黑", "说不出话", "半边身体不能动"
- **action**: 设备播报急救指导 + 通知紧急联系人（priority=1）
- **response**: 固定安全消息 + 急救指导（如"先坐下别动，我已经通知您的家人了"）

#### high（需要干预）
- **category**: `scam_alert` | `health_concern`
- **scam keywords**: "转钱", "汇款", "公安局打电话", "银行卡密码", "中奖", "保证金", "安全账户", "不要告诉别人"
- **health keywords**: "这两天一直头疼", "吃不下饭好几天", "晚上老睡不着", "腿肿"
- **scam patterns**: `(?:让|要|叫).{0,6}(?:转账|汇款|打钱|转钱)`
- **action**: AI 主动提醒 + 通知子女
- **scam response**: "这个听起来可能是骗人的，千万不要转钱！我帮您通知家人确认一下。"

#### medium（关怀触发）
- **category**: `emotional_low`
- **keywords**: "没人跟我说话", "一个人好无聊", "孩子好久没来了", "老了不中用", "给人添麻烦", "活着没意思"
- **action**: AI 陪伴式多聊 + 静默通知子女"老人今天情绪低落"

### 3.2 Emergency Contacts Table

```sql
CREATE TABLE emergency_contacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    name            VARCHAR NOT NULL,
    phone           VARCHAR NOT NULL,
    relation        VARCHAR,          -- "儿子", "女儿", "邻居"
    priority        INT DEFAULT 1,    -- 1=最优先
    notify_on_levels TEXT[] DEFAULT '{"critical","high"}',
    webhook_url     VARCHAR,          -- 子女接收通知的 webhook
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

### 3.3 Notification Worker

新增 `notification_worker.py`：
- Celery task: `send_risk_notification(user_id, risk_level, risk_category, message_summary)`
- 查询 emergency_contacts，按 priority 排序
- 对每个匹配 notify_on_levels 的联系人发送 webhook POST
- Webhook payload: `{user_id, elder_name, risk_level, category, summary, timestamp}`
- 记录通知历史到 `notification_log` 表

## 4. Reminder System

### 4.1 Data Model

```sql
CREATE TABLE reminders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    title           VARCHAR NOT NULL,
    description     TEXT,
    schedule_type   VARCHAR NOT NULL,  -- "daily", "weekly", "once", "interval"
    schedule_cron   VARCHAR,           -- cron expression
    time_of_day     TIME,              -- 触发时间 (冗余，方便查询)
    next_fire_at    TIMESTAMPTZ NOT NULL,
    last_fired_at   TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT true,
    created_by      VARCHAR DEFAULT 'user',  -- "user" / "family"
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_reminders_next_fire ON reminders (next_fire_at) WHERE is_active = true;

CREATE TABLE reminder_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reminder_id     UUID NOT NULL REFERENCES reminders(id),
    fired_at        TIMESTAMPTZ NOT NULL,
    delivered       BOOLEAN DEFAULT false,  -- WS 推送是否成功
    acknowledged    BOOLEAN DEFAULT false,  -- 老人是否回应了
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

### 4.2 Reminder Tool (改造现有 `reminder_tool.py`)

**输入**：用户自然语言，由 LLM 提取结构化参数

**AI 自动判断重复模式**：
```python
DAILY_KEYWORDS = ["吃药", "量血压", "测血糖", "吃饭", "喝水", "做操", "散步", "锻炼"]
ONCE_KEYWORDS = ["打电话", "买", "取", "寄", "明天", "后天", "下周"]
```
- 命中 DAILY_KEYWORDS → `schedule_type="daily"`
- 命中 ONCE_KEYWORDS → `schedule_type="once"`
- 不确定 → AI 反问确认

**Tool 执行流程**：
1. 解析时间和标题
2. 生成 cron 表达式
3. 写入 reminders 表
4. 计算 next_fire_at
5. 返回确认文本："好的，我会每天中午12点提醒您吃药"

### 4.3 Reminder Scheduler

新增 `reminder_scheduler.py`（Celery Beat 定时任务）：

- **每分钟执行**：查询 `next_fire_at <= now() AND is_active = true` 的提醒
- 对每个到期提醒：
  1. 检查用户是否有活跃 WS 连接
  2. **有连接** → 通过 WS 推送 `{"type": "reminder", "reminder_id": "...", "title": "吃药", "message": "该吃药啦"}`
  3. **无连接** → 标记 `delivered=false`，下次连接时补发
  4. 写入 reminder_history
  5. 根据 schedule_type 计算并更新 next_fire_at（daily→+1天，once→标记 is_active=false）

### 4.4 WS Protocol Extension

新增消息类型：
```json
// 服务端推送
{"type": "reminder", "reminder_id": "uuid", "title": "吃药", "message": "该吃药啦，记得按时吃哦"}

// 客户端确认（可选，老人回应了）
{"type": "reminder_ack", "reminder_id": "uuid"}
```

### 4.5 Family Management API

所有端点需要 `role=family` 的 JWT + `managed_user_id` 绑定校验：

```
GET    /api/reminders                  -- 查看被管理老人的所有提醒
POST   /api/reminders                  -- 子女帮老人创建提醒
PUT    /api/reminders/{id}             -- 修改提醒
DELETE /api/reminders/{id}             -- 删除提醒
GET    /api/reminders/{id}/history     -- 查看触发历史
GET    /api/notifications              -- 查看风险通知历史
```

## 5. User Role System

### 5.1 Schema Changes

```sql
-- users 表新增
ALTER TABLE users ADD COLUMN role VARCHAR DEFAULT 'elder';  -- "elder" / "family"

-- 家属绑定表
CREATE TABLE family_bindings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_user_id  UUID NOT NULL REFERENCES users(id),
    elder_user_id   UUID NOT NULL REFERENCES users(id),
    permissions     TEXT[] DEFAULT '{"view_reminders","manage_reminders","view_notifications"}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(family_user_id, elder_user_id)
);
```

### 5.2 Auth Changes

- 注册时可选 `role` 参数（默认 elder）
- Family 用户的 JWT 包含 `role: "family"`
- Family API 端点通过 `family_bindings` 校验权限
- 绑定流程：老人端生成一个 6 位绑定码（有效期 10 分钟），子女输入绑定码完成绑定

## 6. Frontend Changes

### 6.1 文案全局替换

- "AI Companion" → "智慧陪伴"
- "给 AI Companion 发消息..." → "跟我说说话吧..."
- 快捷按钮改为：["聊聊天", "设个提醒", "今天天气", "查看提醒"]

### 6.2 提醒管理页（子女端）

- `/reminders` 页面：提醒列表 + 新建/编辑/删除
- `/notifications` 页面：风险通知历史

## 7. Device Audio Layer (ESP32-S3-BOX-3)

### 7.1 Wake Word Detection

设备默认处于待机状态（低功耗，仅监听唤醒词），用户说出唤醒词后进入对话模式。

**唤醒词**：可配置，默认 "小伴小伴"（2-4 个音节，便于老人记忆）

**实现方案**：
- 使用 ESP-SR（乐鑫官方语音识别库）的 WakeNet 模型，在 ESP32-S3 本地运行
- WakeNet 模型文件约 50KB，S3 的 PSRAM 足够
- 唤醒检测纯本地，不需要网络，延迟 < 200ms
- 唤醒后播放提示音 + 设备指示灯亮起

**状态机**：
```
STANDBY（待机）──► 检测到唤醒词 ──► LISTENING（聆听）
    ▲                                      │
    │                                      ▼
    │                               VAD 检测说完
    │                                      │
    │                                      ▼
    │                              PROCESSING（处理中）
    │                                      │
    │                                      ▼
    │                              SPEAKING（播放回复）
    │                                      │
    └──── 5分钟无交互 ◄──────────── LISTENING（等待下一句）
```

### 7.2 Auto-Standby (5 分钟超时)

- 进入 LISTENING 状态后启动 5 分钟倒计时
- 每次用户说话或 AI 回复重置倒计时
- 超时后：
  - 播放提示音："我先休息一下，需要我的时候叫我就行"
  - 进入 STANDBY，仅运行 WakeNet 监听
  - 断开 WS 连接以节省功耗（下次唤醒时重连）
- **提醒例外**：即使在 STANDBY 状态，到了提醒时间设备也要主动播报（通过本地定时器触发，不依赖 WS）

### 7.3 Echo Cancellation (AEC)

设备播放 AI 回复时，麦克风仍在采集——如果不做回声消除，AI 的声音会被录进去再次发给服务端。

**实现方案**：
- 使用 ESP-ADF（Audio Development Framework）内置的 AEC 算法
- ESP32-S3-BOX-3 自带双麦克风，支持硬件级 AEC
- AEC 需要参考信号（speaker output）作为输入，ESP-ADF 的 `audio_pipeline` 原生支持
- 配置：AEC filter length = 512 samples（32ms @16kHz），足够覆盖房间混响

### 7.4 Noise Suppression (NS)

老人家里可能有电视声、空调噪声、街道噪声。

**实现方案**：
- 使用 ESP-SR 的 NS（Noise Suppression）模块
- 与 AEC 串联在音频管道中：`Mic → AEC → NS → VAD → 编码上传`
- NS 模式设为 aggressive（老人说话通常音量较大，可以激进降噪）

### 7.5 Audio Pipeline (ESP32 端完整链路)

```
           ┌──────── Speaker Output (参考信号) ────────┐
           │                                           │
Mic ──► [AEC] ──► [NS] ──► [VAD] ──► PCM 16kHz ──► WebSocket
                              │
                              └── 静音 5 分钟? → STANDBY

WebSocket ◄── 音频块 ──► [解码] ──► Speaker
```

**固件配置参数**（`config.h`）：
```c
#define WAKE_WORD           "小伴小伴"
#define SAMPLE_RATE         16000
#define AEC_FILTER_LENGTH   512
#define NS_MODE             NS_AGGRESSIVE
#define VAD_SILENCE_TIMEOUT 300   // 说完后的静音判定(ms)
#define STANDBY_TIMEOUT_S   300   // 5分钟无交互进入待机
#define REMINDER_CHECK_INTERVAL_S  60  // 每分钟检查本地提醒
```

## 8. Files Changed Summary

| 类别 | 文件 | 改动 |
|------|------|------|
| 配置 | `personality.yaml` | 全量重写 |
| 配置 | `risk_rules.yaml` | 全量重写（三类风险） |
| 引擎 | `emotion_engine.py` | 新增 loneliness/confusion |
| 引擎 | `intent_engine.py` | 新增 health_concern/reminder_request |
| 引擎 | `risk_engine.py` | 新增 scam/health_emergency 分类 |
| 工具 | `reminder_tool.py` | 重写：DB 持久化 + cron 调度 |
| 新增 | `reminder_scheduler.py` | Celery Beat 提醒调度器 |
| 新增 | `notification_worker.py` | 风险通知推送 |
| 新增 | `reminder_api.py` | 子女管理 REST API |
| DB | `models.py` | 新增 reminders/reminder_history/emergency_contacts/family_bindings 表 |
| DB | migration | 新增迁移文件 |
| 运行时 | `prompt_builder.py` | 更新老年陪伴指令 |
| 运行时 | `ws_chat.py` | 新增 reminder/reminder_ack 消息类型 |
| 运行时 | `agent_harness.py` | risk 处理增加通知触发 |
| 前端 | `ChatWindow.tsx` | 文案更新 + 提醒相关 UI |
| 前端 | 新增页面 | `/reminders`, `/notifications` |
| 前端 | `authStore.ts` | 支持 role 字段 |
| 测试 | `test_*.py` | 更新/新增老年场景测试 |
| 固件 | 新增 `firmware/` | ESP32-S3 固件：唤醒词 + AEC + NS + VAD + WS 客户端 + 本地提醒定时器 |
| 固件 | `firmware/config.h` | 唤醒词、采样率、AEC/NS 参数、超时配置 |
| 固件 | `firmware/audio_pipeline.c` | Mic → AEC → NS → VAD → WS 上传链路 |
| 固件 | `firmware/ws_client.c` | WebSocket 客户端（首包鉴权 + 提醒接收） |
| 固件 | `firmware/state_machine.c` | STANDBY/LISTENING/PROCESSING/SPEAKING 状态机 |
| 固件 | `firmware/local_reminder.c` | 本地提醒定时器（待机时也能触发播报） |
| 文档 | `README.md` | 更新项目描述 |
| 文档 | `CLAUDE.md` | 更新项目简介和规范 |
