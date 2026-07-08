# Telegram Bot + LM Studio Bridge

这个项目会把 Telegram 私聊消息转发给你本机的 LM Studio 模型，并把模型回复再发回 Telegram。

## 功能特点

- Telegram 外网访问强制走 `http://127.0.0.1:7890`
- LM Studio 本地接口直连，不经过代理
- 每个 Telegram 私聊用户有独立上下文
- 支持 `/start` 和 `/reset`
- 自动拆分超长回复，避免 Telegram 单条消息长度超限
- 推理期间持续显示 `typing...`
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
LMSTUDIO_TEMPERATURE=0.7
LMSTUDIO_MAX_TOKENS=1024
LMSTUDIO_TIMEOUT=900
MAX_HISTORY_MESSAGES=20
CHAT_LOG_DIR=chat_logs
SESSION_STORE_PATH=session_store.json
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

## 运行程序

```powershell
conda activate telegram-lmstudio-bot
python main.py
```

启动后，直接给你的 Telegram Bot 发私聊消息即可。

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
