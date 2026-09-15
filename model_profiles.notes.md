# 模型参数来源与备选方案

## 2026-09-14 Preserve Thinking 支持更新

机器人已补齐历史思考的本地保存与请求回传。新完成回合的思考单独存入
`session_store.json`；当前模式的 `preserve_thinking=true` 时，按 Qwen 官方示例在历史
assistant 消息中发送 `reasoning_content` 和 `reasoning`。关闭或留空则不回传。
旧版没有存下的思考不自动补回，旧上下文无需删除。实际模板处理仍依赖 LM Studio。
下节“不会让历史思考内容自动进入上下文”描述的是此前仅透传开关时的状态。

## 2026-09-14 程序适配更新

程序现已接受下面记录的新增模式参数，原 `model_profiles.json` 数值和资料保持不变。
`repetition_penalty` 自动映射为 LM Studio 的 `repeat_penalty`；模式内 `reasoning_effort`
优先于 `thinking_effort`，显式留空则不发送。`chat_template_kwargs` 的
`enable_thinking`、`preserve_thinking` 布尔值按模式传递，也可通过 `/params` 编辑。

LM Studio [Chat Completions 官方文档](https://lmstudio.ai/docs/developer/openai-compat/chat-completions)
列出了 `repeat_penalty`，尚未明确列出 `chat_template_kwargs`。程序支持传递不等于
当前服务端和模板一定执行这些开关；本次未进行模型推理验证。机器人仍只回传问题和最终
回答的历史，因此 `preserve_thinking=true` 不会让历史思考内容自动进入上下文。
参考区的 token 限制说明、任务预设、系统提示前缀不自动执行。

下文“程序尚未扩展”的描述是配置更新时的历史状态，以本节和 README 的适配说明为准。

## 2026-09-14 更新：完整记录官方参数

按用户要求，`model_profiles.json` 现在包含当前程序尚未支持的字段。四款 Qwen 两种模式均加入 `repetition_penalty=1.0`，HY-MT2 非思考模式加入 `repetition_penalty=1.05`。Qwen 的 `chat_template_kwargs.enable_thinking` 按模式显式设置；Qwen3.8 两种模式均加入 `preserve_thinking=true`，思考强度改为官方默认 `xhigh`，并同时记录现有项目字段 `thinking_effort` 与官方字段 `reasoning_effort`。

Qwen3.5/3.6 的通用 `max_tokens` 统一为官方推荐的 32768；竞赛评测的 81920 记录在各模型的 `official_recommendations.output_length` 中。Qwen3.8 保留已有统一输出预算 44081，并在该参考区记录官方针对 1M 上下文的独立思考上限 262144 和答案上限 131072；44081 是本地自定值，不是官方推荐。参考区的长度键是说明性字段，官方没有在该段指定统一的 API 字段名。

`official_recommendations` 还记录官方编程等任务预设、Qwen3.6 可选的历史思考保留，以及 Gemma 的系统提示思考标记。Qwen3.5 模型卡的 API Usage 与 Best Practices 对非思考推理任务存在数值差异，两套均保存并标明来源。各模型含对应官方来源链接，根部元数据标记核对日期和字段用途。

JSON 语法与写入值已检查；程序代码未扩展。当前 `ModelStore` 会拒绝模式配置中的新增未知字段，因此本次文件不能被视为已经适配当前程序的运行配置。

## 2026-09-12 历史记录

以下保留上次调研快照；表格、兼容性取舍和“未写入”描述仅适用于当时版本，当前值以上面的更新及 JSON 为准。

核对日期：2026-09-12。`model_profiles.json` 采用官方通用任务推荐中当前程序支持的参数。这里的“推荐”是起点，不代表在每种量化、语言和任务上都最优。社区方案仅供对照试用，未写入生效配置。

本机 LM Studio `/api/v1/models` 确认 Qwen3.8 Uncensored 发布者为 JonathanColetti，两款 HauhauCS 模型发布者为 HauhauCS。以下参数继承对应基础模型，不能据此声称官方已对这些去审查衍生模型做过独立调参验证。

## 已写入的参数

`null` 表示请求不发送该字段，由服务端决定；不等于零或关闭。

| 本地模型 | 模式 | temperature | top_p | top_k | min_p | presence_penalty | max_tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen3.8-27b-uncensored | thinking | 1.0 | 0.95 | 20 | 0.0 | 0.0 | null |
| qwen3.8-27b-uncensored | non_thinking | 0.7 | 0.8 | 20 | 0.0 | 1.5 | null |
| qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive | thinking | 1.0 | 0.95 | 20 | 0.0 | 1.5 | 32768 |
| qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive | non_thinking | 0.7 | 0.8 | 20 | 0.0 | 1.5 | 32768 |
| qwen3.5-35b-a3b-uncensored-hauhaucs-aggressive | thinking | 1.0 | 0.95 | 20 | 0.0 | 1.5 | 32768 |
| qwen3.5-35b-a3b-uncensored-hauhaucs-aggressive | non_thinking | 0.7 | 0.8 | 20 | 0.0 | 1.5 | 32768 |
| qwen/qwen3.5-9b | thinking | 1.0 | 0.95 | 20 | 0.0 | 1.5 | 32768 |
| qwen/qwen3.5-9b | non_thinking | 0.7 | 0.8 | 20 | 0.0 | 1.5 | 32768 |
| hy-mt2-1.8b | non_thinking | 0.7 | 0.6 | 20 | null | null | 4096 |
| google/gemma-4-26b-a4b | thinking / non_thinking | 1.0 | 0.95 | 64 | null | null | null |

来源逐项对应：

- Qwen3.8：[官方模型卡](https://huggingface.co/Qwen/Qwen3.8-27B#best-practices)；[JonathanColetti 衍生模型卡](https://huggingface.co/JonathanColetti/Qwen3.8-27B-Uncensored) 同样引用 Qwen 的 temperature、top_p、top_k 推荐。
- Qwen3.6 35B：[官方模型卡](https://huggingface.co/Qwen/Qwen3.6-35B-A3B#best-practices)；[HauhauCS 作者配置](https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive#recommended-settings)。
- Qwen3.5 35B：[官方模型卡](https://huggingface.co/Qwen/Qwen3.5-35B-A3B#best-practices)；[HauhauCS 作者配置](https://huggingface.co/HauhauCS/Qwen3.5-35B-A3B-Uncensored-HauhauCS-Aggressive#recommended-settings)。
- Qwen3.5 9B：[官方模型卡](https://huggingface.co/Qwen/Qwen3.5-9B#best-practices)。
- HY-MT2 1.8B：[腾讯官方模型卡](https://huggingface.co/tencent/Hy-MT2-1.8B#inference-and-deployment)。
- Gemma 4 26B A4B：[Google 指令模型卡](https://huggingface.co/google/gemma-4-26B-A4B-it#best-practices)，两种模式均使用其统一采样推荐。

## 适配范围与保留项

- 当前程序只接受六个采样字段，不支持 `repetition_penalty`。Qwen 官方还推荐该值为 `1.0`，HY-MT2 推荐 `1.05`；本次没有把它伪装成 `presence_penalty` 或加入会被校验拒绝的字段。要完整复现这部分配置，需在推理端设置，或后续扩展客户端支持。未检查或改动 LM Studio 的重复惩罚预设。
- HY-MT2 官方没有给出 `min_p`、`presence_penalty` 推荐；Gemma 官方上述最佳实践只指定 temperature、top_p、top_k。对应空值保留。HY-MT2 不支持思考，未使用的 thinking 配置保留空值。
- Qwen3.5/3.6 官方对多数问题推荐 32,768 输出 token，对竞赛数学和编程评测推荐 81,920；本次采用前者。输出上限不等于模型加载的上下文窗口；长历史与生成仍受实际上下文容量和现有超时限制。
- Qwen3.8 官方针对 1M 上下文、可分别限制思考与答案的框架，推荐思考最多 262,144、答案最多 131,072 token。本项目仅有统一 `max_tokens`，本机模型元数据声明原生最大上下文为 262,144；因此保留 `max_tokens=null`，没有把两项相加或机械照搬。
- 保留现有 `thinking_effort=medium`。Qwen3.8 官方默认为 `xhigh`，同时将 `medium` 列为兼顾准确率与速度的选项；本机发现接口只声明 on/off，未验证 GGUF 模板是否实际区分强度。本次只调整采样与可直接映射的输出上限。Qwen3.8 的思考历史保留机制也不属于此次配置更新。
- 配置按操作重新读取，新生成请求即可使用；已开始的生成不追溯变更。本次未运行模型质量评测。

## 官方的任务专用备选

- Qwen3.5（35B、9B）及 Qwen3.6 35B 的精确编程思考模式：`temperature=0.6, top_p=0.95, top_k=20, min_p=0, presence_penalty=0`。这是上述官方模型卡中的另一套推荐，适合优先尝试于编程任务。
- Qwen3.5 两款模型的非思考推理任务：`temperature=1.0, top_p=1.0, top_k=40, min_p=0, presence_penalty=2.0`。HauhauCS 的 Qwen3.6 卡也列出此项，但当前 Qwen3.6 基础模型卡仅列非思考通用配置，故不将前者描述为当前 Qwen3.6 官方通用推荐。

## 社区报告：有改善反馈，尚无普遍更优的证据

以下为使用者自己的经验报告，量化版本和任务与本机未必相同。搜索未找到能证明它们对本机六款模型普遍优于官方配置的受控比较。

| 适用模型 / 场景 | 报告的参数 | 证据与限制 |
| --- | --- | --- |
| Qwen3.5 35B，思考聊天 | temperature=0.9、top_p=0.95、top_k=0、min_p=0.05、presence_penalty=1.3 | 使用者称对话更自然；非系统评测，也未证明对 HauhauCS 版本或编程有效。[原讨论及跟进参数](https://www.reddit.com/r/LocalLLaMA/comments/1ryb028/qwen35_best_parameters_collection/) |
| Qwen3.8 27B，代理编程 | temperature=0.4、top_p=0.90、top_k=15、min_p=0.02；文中配置继承 presence_penalty=0.1、repeat-penalty=1.0 | 作者报告完成真实项目，使用 Unsloth Q3_K_XL 与另一套上下文、缓存、思考预算配置，无法单独归因于采样。搜索摘要曾显示另一组值，此处以打开的正文为准；不能视为本机 JonathanColetti Q4_K_M 的最优值。[作者原帖](https://www.reddit.com/r/LocalLLaMA/comments/1vqrt86/after_pushing_1m_tokens_through_qwen_38_27b_here/) |
| Gemma 4 26B A4B，思考编程 | 尝试将 temperature 提高到 1.4–1.5；帖子没有提供一套统一、完整的其余采样参数 | 有使用者称答案改善，但也报告 1.5 时思考约长三倍、反复自我检查。它只是任务相关温度试验，不能视为完整可复现预设。[原讨论](https://www.reddit.com/r/LocalLLaMA/comments/1sg8r4l/gemma_4_seems_to_work_best_with_high_temperature/) |
| Gemma 4 26B A4B，非思考角色扮演 | temperature=1.15、top_p=0.37、top_k=50、min_p=0.075、presence_penalty=0、repetition_penalty=1.18；关闭 DRY，重复惩罚范围 1024 | 作者在 TextGen、特定德语提示及 Q6 量化上的主观反馈；本程序不能仅靠现有 JSON 完整复现。[作者完整预设](https://www.reddit.com/r/Oobabooga/comments/1soekcx/optimal_sampling_parameters_for_gemma_4_models/) |

对于 Qwen3.6，找到的[参数优化讨论](https://www.reddit.com/r/LocalLLaMA/comments/1srziyq/optimizing_qwen_36_35b_a3b_sampling_parameters/)仍在讨论如何克服评测方差，没有给出经过充分验证的胜出参数。HY-MT2 1.8B 与 Qwen3.5 9B 也未找到有充分对照证据的替代推荐，因此保持官方配置。
