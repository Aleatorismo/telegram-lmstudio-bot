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
  - 按 `<用户名>_<Telegram用户ID>/对话开始日期/对话文件.md` 组织日志
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
| `/settings` | 查看当前模型、模式、思考强度、采样参数及模板参数 |
| `/params temperature=0.6 max_tokens=4096` | 修改当前模型、当前模式的参数 |
| `/params on top_p=0.95 top_k=20 min_p=0 presence_penalty=0` | 修改当前模型的思考参数，不切换当前模式 |
| `/params off temperature=0.7` | 修改当前模型的非思考参数 |
| `/params on repetition_penalty=1.05 reasoning_effort=xhigh` | 修改重复惩罚及该模式的思考强度 |
| `/params on chat_template_kwargs.preserve_thinking=true` | 单独修改模板参数，保留其他模板开关 |
| `/params on chat_template_kwargs={"enable_thinking": true, "preserve_thinking": true}` | 用 JSON 对象替换该模式的模板参数，支持对象内空格 |
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
- 模式内的 `reasoning_effort` 优先于模型级 `thinking_effort`，支持 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`。实际支持范围取决于模型和 LM Studio；思考模式不能设 `none`，非思考模式不能设开启强度。
- 模式内缺少 `reasoning_effort` 时沿用之前的开关逻辑：思考模式使用 `thinking_effort`（缺省 `medium`），可切换模型的非思考模式发送 `none`，非思考专用模型不发送。显式设为 `null`、`""` 或 `default` 则省略该字段，不回退到 `thinking_effort`。
- 缺失、`null` 或 `""` 参数均不发送给 LM Studio。此规则也适用于 `temperature` 和 `max_tokens`。
- 参数不再从 `.env` 读取，旧 `LMSTUDIO_TEMPERATURE` 等采样变量会被忽略；新发现模型的采样参数初始全为空，不自动沿用旧全局值。
- 手动修改文件后，下次命令或模型请求即生效。自动发现不会覆盖已有的明确类型、思考强度或采样参数；需要重新识别类型时可设为 `unknown` 后执行 `/model`。
- 同一个模型的参数预设由所有用户共享，但每个用户选中的模型和模式独立。
- `temperature` 范围 0–2；`top_p`、`min_p` 为 0–1；`presence_penalty` 为 -2–2；`top_k` 为非负整数；`max_tokens` 为正整数或 `-1`（不限输出长度，仍受模型上下文限制）。
- `repetition_penalty` 为有限正数（`1.0` 不加惩罚），发送时转换为 LM Studio 官方字段 `repeat_penalty`，不转换成 `presence_penalty`。也接受直接写 `repeat_penalty`；两种写法同时出现且值不同时报错。指令编辑一种写法会替换另一种。
- `chat_template_kwargs` 支持 `enable_thinking`、`preserve_thinking` 两个布尔键，使用 JSON `true`/`false`。`enable_thinking` 必须与所在模式一致，切换请使用 `/think`。空对象和空值键不发送；`false` 不会被当作空值丢弃。点号赋值可以单独编辑或清除某个键。
- 模板参数在 HTTP JSON 请求顶层原样传递，不额外包裹 `extra_body`。LM Studio 当前 [Chat Completions 官方文档](https://lmstudio.ai/docs/developer/openai-compat/chat-completions) 列出了 `repeat_penalty`，未明确列出 `chat_template_kwargs`；因此模板参数的最终解释仍依赖服务端版本及模板。
- `official_recommendations` 及根级参考元数据仅保留为资料，不作为请求参数发送；其中的任务预设、分别限制思考/答案的说明性 token 键和系统提示前缀也不会自动启用。
- `MODEL_PROFILES_PATH` 和 `MODEL_SELECTIONS_PATH` 可覆盖文件路径。文件使用 UTF-8 JSON，不支持注释或尾随逗号；损坏文件会报错而不会被静默覆盖。
- `LMSTUDIO_MODEL` 现在仅为可选的初始模型；留空时使用本地列表中的第一个模型。未加载模型能否自动加载取决于 LM Studio 的服务器设置。

思考开关仍走 `/v1/chat/completions`；未显式清空 `reasoning_effort` 时，关闭发送 `none`，开启发送对应强度。
已在本机当前加载的 Qwen 模型上验证实际思考 token 的开关效果；其它模型的行为由其模板和 LM Studio 实现决定。
能力字段见 [LM Studio 官方模型列表文档](https://lmstudio.ai/docs/developer/rest/list)。

### 保留历史思考（Preserve Thinking）

机器人会把新完成回合的思考以 `reasoning_content` 单独保存在 `session_store.json` 的
assistant 消息中，最终回答仍在 `content` 中。只有成功生成并发送最终回答的回合才会
进入上下文；出错、中断或只有思考没有答案的回合不保存到上下文。

当前模型、当前模式设置 `chat_template_kwargs.preserve_thinking=true` 时，后续请求会
带回已保存的历史思考，按 [Qwen 官方示例](https://huggingface.co/Qwen/Qwen3.8-27B#api-usage)
写入历史 assistant 消息的 `reasoning_content` 和 `reasoning` 字段，二者是同一内容的
兼容字段，不混入最终答案。`turn_id` 仍只用于本地管理，不会发送。

```text
/params on chat_template_kwargs.preserve_thinking=true
/params off chat_template_kwargs.preserve_thinking=true
/settings
```

以上两条 `/params` 分别配置思考与非思考模式的回传开关，不会切换当前模式。设为
`false`、留空、`null` 或缺失时，只回传问题与答案，不回传思考；本地已保存的思考仍保留，
以后开启时可以使用。`/settings` 中的 `Historical thinking replay` 显示机器人端开关状态，
不是服务端实际采用思考的检测结果。

切换模型继续沿用该用户的历史，是否回传思考由新选模型的模式配置决定。`/undo`、
`/reset` 和历史长度截断会同步移除对应思考缓存，其他用户不受影响。思考不额外占一个
历史消息名额，但回传后会增加模型输入 token 和上下文占用。

旧缓存兼容，无需清空。升级前未保存的思考无法自动补回，不从 Markdown 日志恢复。
本功能已验证保存、重启恢复和 HTTP 请求结构；实际模型是否采用这些思考字段仍取决于
LM Studio 版本和模型模板，本次未进行真实模型推理验证。

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
向前撤回。不会删除 Telegram 界面消息或修改模型设置；备份日志的对应回合会加上醒目的
`WITHDRAWN FROM CONTEXT` 警告，保留用户消息、回答和思考内容。
命令不接受用户 ID 等参数；用户之间的上下文严格隔离，撤回结果重启后仍有效。
若历史长度限制只留下最早一回合的片段，最后一次撤回会清除该片段。
生成期间 `/undo` 和 `/reset` 会立即提示等待完成，避免新回答重新写回修改过的上下文。

长内容按每页 24,000 UTF-8 源码字节或 160 个换行的保守预算分段，低于 Telegram
Rich Message 的 32,768 字符上限。跨页代码块会补充围栏；格式解析失败时以浅层
Rich 文本块保留原文。普通指令回复按 4,096 UTF-16 单位分段，兼顾 emoji。
草稿默认每秒更新，可通过 `TELEGRAM_DRAFT_INTERVAL` 调整（0.5–10 秒）。限流时等待
服务器指定时间，正式消息遇到响应不明的网络超时不会盲目重发。

接口说明见 [Telegram 官方文档](https://core.telegram.org/bots/api#sendrichmessagedraft)。

## 聊天日志归档

新日志使用以下结构（文件名还包含唯一标识，避免同一秒内多次重置时覆盖）：

```text
chat_logs/
  .active_conversations.json
  alice_123456/
    2026-09-12/
      conversation_09-30-00-000000_<唯一标识>.md
      conversation_16-20-00-000000_<唯一标识>.md
  bob_789012/
    2026-09-12/
      conversation_10-00-00-000000_<唯一标识>.md
```

- 用户目录使用 `用户名_用户ID`；没有用户名时使用姓名，再无姓名时使用用户 ID 标识。文件名非法字符会替换为下划线。用户 ID 保证重名用户不会混用日志。
- 已建立的可读目录名保持稳定，之后用户改名不会拆分日志。旧 `user_ID` 目录在该用户下次写入记录或执行 `/undo` 时自动改名，保留其全部日期目录和对话文件。
- `/reset` 只结束当前日志会话，不创建新文件；等用户发送下一条消息、实际记录新回合时再创建。连续重置不会产生空对话文件，这个等待状态在重启后仍保留。新文件按实际开始记录的日期归档。
- 日期按 `Asia/Shanghai` 时区计算，代表对话开始日期。跨天继续聊天仍写入原文件，不自动按天切断。
- `.active_conversations.json` 持久保存每个用户当前的日志位置。保留它可在程序重启后继续同一文件；它独立于实际上下文 `session_store.json`。
- Markdown 包含对话信息、每回合时间、用户引用、模型正文及可折叠的斜体思考内容，方便在 Markdown 阅读器中浏览。
- `/undo` 根据持久化回合编号标记对应记录；连续撤回、重启和历史截断后仍能定位，不会误标生成失败的记录或其他用户的记录。编号不会发送给模型。
- 旧版无编号记录仅在能唯一匹配时原位标记；无法定位的上下文会在当前日志末尾追加撤回说明及被撤回内容副本。旧的顶层 `.txt` 日志不读取、不迁移、不删除。
- 如果上下文已撤回但归档写入失败，机器人会明确提示归档标记失败，不会谎报全部成功。
- 升级不需要清空上下文。首次使用新日志逻辑时新建 Markdown 文件，之前保留的上下文仍正常供模型使用。

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
  - 到 `chat_logs/<用户名>_<用户ID>/` 下按对话开始日期浏览 `.md` 文件
- 想保留重启前的上下文：
  - 不要删除 `session_store.json`
- 提示模型错误：
  - 确认 `LMSTUDIO_MODEL` 填的是实际模型 ID，而不是显示名称

## 测试

```powershell
pytest
```
