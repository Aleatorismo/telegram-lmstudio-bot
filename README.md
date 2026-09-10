# Telegram Bot + LM Studio Bridge

这个项目会把 Telegram 私聊消息转发给你本机的 LM Studio 模型，并把模型回复再发回 Telegram。

## 功能特点

- Telegram 外网访问强制走 `http://127.0.0.1:7890`
- LM Studio 本地接口直连，不经过代理
- 每个 Telegram 私聊用户有独立上下文
- 支持 `/start`、`/reset`、`/model`、`/think`、`/settings` 和 `/params`，指令回复为英文
- 自动拆分超长回复，避免 Telegram 单条消息长度超限
- 推理期间持续显示 `typing...`
- Rich Markdown 流式草稿、斜体思考折叠块、`/undo` 上下文撤回
- 所有成功对话都会按用户写入本地可读文本日志
- 会话记忆会写入本地状态文件，程序重启后仍然保留
- Telegram 代理短暂中断后会自动清理并重建 Bot 应用

## 目录结构

- `main.py`：程序入口
- `config.py`：环境变量读取和校验
- `telegram_bot.py`：Telegram 消息处理
- `lmstudio_client.py`：LM Studio OpenAI 兼容接口客户端
- `session_store.py`：内存会话存储

## 先决条件

1. 已安装 Miniconda
2. 本机代理 `http://127.0.0.1:7890` 可用
3. 已在 LM Studio 中加载模型，并启动本地服务
4. 已在 BotFather 创建 Telegram Bot，并拿到 token

## 创建 conda 环境

```powershell
conda env create -f environment.yml
conda activate telegram-lmstudio-bot
```

如果你更喜欢手动创建，也可以：

```powershell
conda create -n telegram-lmstudio-bot python=3.12 -y
conda activate telegram-lmstudio-bot
python -m pip install -r requirements.txt
```

## 配置环境变量

复制 `.env.example` 为 `.env`，然后填写真实值：

```env
TELEGRAM_BOT_TOKEN=你的_bot_token
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_MODEL=你在_LM_Studio_里加载的模型ID
LMSTUDIO_SYSTEM_PROMPT=You are a helpful assistant running locally through LM Studio.
LMSTUDIO_TIMEOUT=900
MAX_HISTORY_MESSAGES=20
CHAT_LOG_DIR=chat_logs
SESSION_STORE_PATH=session_store.json
MODEL_PROFILES_PATH=model_profiles.json
MODEL_SELECTIONS_PATH=model_selections.json
TELEGRAM_TYPING_INTERVAL=4
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
NO_PROXY=127.0.0.1,localhost
```

## 关键配置说明

- `LMSTUDIO_TIMEOUT`
  - 控制等待 LM Studio 返回结果的最长秒数
  - 默认 `900` 秒，也就是 `15` 分钟
  - 如果你用的是推理模型，可以继续调大，比如 `1800`
- `TELEGRAM_TYPING_INTERVAL`
  - 控制 Bot 在等待模型期间，多久发送一次 `typing...`
  - 默认 `4` 秒
- `TELEGRAM_NETWORK_ERROR_THRESHOLD`
  - 控制连续出现多少次 Telegram 轮询网络错误后，主动重建整个 Bot 应用
  - 默认 `4`
- `TELEGRAM_NETWORK_ERROR_WINDOW`
  - 控制上面的连续错误统计窗口，单位秒
  - 默认 `120`
- `TELEGRAM_RESTART_DELAY`
  - 控制触发自愈重启后，等待多久再重建 Telegram 客户端
  - 默认 `3` 秒
- `CHAT_LOG_DIR`
  - 控制本地聊天日志目录
  - 默认是项目下的 `chat_logs/`
  - 每个 Telegram 用户会生成一个单独的 `.txt` 文件
- `SESSION_STORE_PATH`
  - 控制会话记忆状态文件路径
  - 默认是项目下的 `session_store.json`
  - 这个文件用于恢复 Bot 的上下文记忆，不是给人看的聊天日志

## LM Studio 设置

1. 打开 LM Studio
2. 加载你想聊天的模型
3. 启动本地开发者服务
4. 确认服务地址类似 `http://127.0.0.1:1234/v1`
5. 确认 `LMSTUDIO_MODEL` 与服务可见的模型 ID 一致

## 模型、思考模式和参数

重启机器人后，Telegram 的指令菜单会自动更新。四个新命令仅在私聊中使用：

| 命令 | 用法 |
| --- | --- |
| `/model` | 实时获取模型列表，显示可用模型 ID 和模式类型 |
| `/model qwen3.8-27b-uncensored` | 切换模型；支持思考则默认开启，否则关闭 |
| `/think` | 切换思考开关；也可用 `/think on` 或 `/think off` |
| `/settings` | 查看当前模型、模式、思考强度及六个采样参数 |
| `/params temperature=0.6 max_tokens=4096` | 修改当前模型、当前模式的参数 |
| `/params on top_p=0.95 top_k=20 min_p=0 presence_penalty=0` | 修改当前模型的思考参数，不切换当前模式 |
| `/params off temperature=0.7` | 修改当前模型的非思考参数 |
| `/params temperature=default max_tokens=` | 清除指定参数覆盖，恢复使用 LM Studio 默认值 |

`/params` 不带参数会显示帮助。赋值用空格分隔，等号两侧不要加空格。
切换模型或模式保留上下文；想开始新对话时使用 `/reset`。
模型和模式选择按 Telegram 用户保存在 `model_selections.json`，重启后恢复。
`/reset` 仅清空对话，不清空模型选择或参数。

### 可手动编辑的本地文件

`model_profiles.json` 保存模型列表和按模式区分的参数；启动时及执行 `/model` 时，
优先从 LM Studio `/api/v1/models` 获取模型及能力，并补充到文件中。
若接口不可用，依次尝试 `/api/v0/models`、`/v1/models`，最后使用本地文件。
embedding 模型会在原生接口列表中被排除。旧版接口不提供可靠能力信息时，
新模型标记为 `unknown`，需要手动填写类型后使用，不会凭模型名字猜测。

文件示例（模型 ID 应替换为实际值）：

```json
{
  "models": {
    "your-model-id": {
      "type": "both",
      "thinking_effort": "medium",
      "thinking": {
        "temperature": 0.6,
        "max_tokens": null,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": null,
        "presence_penalty": null
      },
      "non_thinking": {
        "temperature": 0.7,
        "max_tokens": 4096
      }
    }
  }
}
```

- `type` 支持 `non_thinking`（只能非思考）、`thinking`（只能思考）、`both`（可切换）。
- `thinking_effort` 控制思考开启时发送的 API 值，默认 `medium`；也支持 `minimal`、`low`、`high`、`xhigh`，实际支持范围取决于模型和 LM Studio。只控制开关的模型使用 `medium` 即可。
- 缺失、`null` 或 `""` 参数均不发送给 LM Studio。此规则也适用于 `temperature` 和 `max_tokens`。
- 六个参数已不再从 `.env` 读取，旧 `LMSTUDIO_TEMPERATURE` 等采样变量会被忽略；新文件初始全为空，不自动沿用旧全局值。
- 手动修改文件后，下次命令或模型请求即生效。自动发现不会覆盖已有的明确类型、思考强度或采样参数；需要重新识别类型时可设为 `unknown` 后执行 `/model`。
- 同一个模型的参数预设由所有用户共享，但每个用户选中的模型和模式独立。
- `temperature` 范围 0–2；`top_p`、`min_p` 为 0–1；`presence_penalty` 为 -2–2；`top_k` 为非负整数；`max_tokens` 为正整数或 `-1`（不限输出长度，仍受模型上下文限制）。
- `MODEL_PROFILES_PATH` 和 `MODEL_SELECTIONS_PATH` 可覆盖文件路径。文件使用 UTF-8 JSON，不支持注释或尾随逗号；损坏文件会报错而不会被静默覆盖。
- `LMSTUDIO_MODEL` 现在仅为可选的初始模型；留空时使用本地列表中的第一个模型。未加载模型能否自动加载取决于 LM Studio 的服务器设置。

思考开关仍走 `/v1/chat/completions`，关闭发送 `reasoning_effort=none`，开启发送对应强度。
已在本机当前加载的 Qwen 模型上验证实际思考 token 的开关效果；其它模型的行为由其模板和 LM Studio 实现决定。
能力字段见 [LM Studio 官方模型列表文档](https://lmstudio.ai/docs/developer/rest/list)。

## 运行程序

```powershell
conda activate telegram-lmstudio-bot
python main.py
```

启动后，直接给你的 Telegram Bot 发私聊消息即可。

## 流式回复和上下文撤回

回复使用 Rich Markdown 流式草稿，结束后保存为正式消息。思考内容放在默认折叠的
Thinking 块中，内部统一为斜体普通段落，保留换行；格式回退也使用相同的斜体样式。
思考文本会转义，代码符号、引用符号和 HTML 不会改变其样式。思考记录写入日志，
但不进入后续模型上下文。

所有停止生成功能已移除：没有原生停止按钮、独立 Stop generating 按钮或 /stop 命令。
模型模式切换仍用于设置后续请求。程序退出、重启和超时仍正常清理连接。

`/undo` 删除当前用户最近一回合的本地上下文（用户消息及对应回答），连续发送可继续
向前撤回。只修改会话存储，不删除 Telegram 界面消息，也不修改历史聊天日志或模型设置。
命令不接受用户 ID 等参数；用户之间的上下文严格隔离，撤回结果重启后仍有效。
若历史长度限制只留下最早一回合的片段，最后一次撤回会清除该片段。
生成期间 `/undo` 和 `/reset` 会立即提示等待完成，避免新回答重新写回修改过的上下文。

长内容按每页 24,000 UTF-8 源码字节或 160 个换行的保守预算分段，低于 Telegram
Rich Message 的 32,768 字符上限。跨页代码块会补充围栏；格式解析失败时以浅层
Rich 文本块保留原文。普通指令回复按 4,096 UTF-16 单位分段，兼顾 emoji。
草稿默认每秒更新，可通过 `TELEGRAM_DRAFT_INTERVAL` 调整（0.5–10 秒）。限流时等待
服务器指定时间，正式消息遇到响应不明的网络超时不会盲目重发。

接口说明见 [Telegram 官方文档](https://core.telegram.org/bots/api#sendrichmessagedraft)。

## 故障排查

- 提示 Telegram 网络错误：
  - 确认本机代理 `http://127.0.0.1:7890` 已启动
  - 确认代理支持 HTTP 代理，而不只是 SOCKS
  - 如果日志里出现连续 `502 Bad Gateway`，通常是代理或上游节点临时异常；程序会在达到阈值后清理当前 Telegram Application 并重建
  - 如果出现 `ExtBot is not properly initialized` 或 `Application is not initialized`，程序会把它当作可恢复的 Telegram 生命周期状态异常并重新创建 Bot 应用
- 提示 LM Studio 无法连接：
  - 确认 LM Studio 本地服务已启动
  - 确认 `LMSTUDIO_BASE_URL` 正确，默认是 `http://127.0.0.1:1234/v1`
- 提示 LM Studio 超时：
  - 把 `LMSTUDIO_TIMEOUT` 调大，例如 `1800`
  - 确认模型确实仍在推理，而不是卡死
- 想查看历史聊天：
  - 到 `chat_logs/` 目录下查看对应用户的 `.txt` 文件
- 想保留重启前的上下文：
  - 不要删除 `session_store.json`
- 提示模型错误：
  - 确认 `LMSTUDIO_MODEL` 填的是实际模型 ID，而不是显示名称

## 测试

```powershell
pytest
```
