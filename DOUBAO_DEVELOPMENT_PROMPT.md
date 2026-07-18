# 探奇 AI 智能机器人：豆包音频大模型与儿童心理学向量分析集成开发方案 (Specification & Prompt)

本篇文档为 **探奇 AI 智能机器人** 的功能迭代设计方案，旨在基于现有架构，引入**火山引擎豆包音频大模型 (Doubao Audio LLM)**、**豆包多模态向量模型 (Doubao Embedding Vision)** 以及最新的 **Doubao Seedream 5.0 pro 高精度画作生成模型**，实现与儿童的高度共情交互、心理状态跟踪、向量语义检索、原生中文简笔画创作（及图像局部交互编辑），以及行为评估数据沉淀。

**注意：根据用户指令，本阶段不进行实际代码修改（不做任何开发），仅进行方案设计并输出高可复用、高精度的「开发提示词与集成规约文档」。**

---

## 一、 系统架构升级设计 (Enhanced Architecture)

为支持「豆包大模型全生态交互」和「儿童心理成长评估向量库」，现有服务端流水线升级如下：

1.  **端到端语音交互层 (Doubao Audio LLM)**：
    *   设备端录制的儿童语音（或经前端带通滤波整流后的 PCM/WAV 字节流）直接编码为 `Base64`。
    *   服务端直接通过 **豆包端到端音频大模型 (Chat API / Responses API)** 进行识别与理解，合并了原本的分立式 ASR (STT) 和 LLM 决策，极大地提升了端到端响应时延与儿童语调、情绪的细腻捕捉能力。
2.  **原生中文简笔画创作引擎 (Doubao Seedream 5.0 pro)**：
    *   儿童通过语音或按键提出的创意绘画指令，不再需要繁琐的中译英步骤。
    *   **Doubao Seedream 5.0 pro** 原生完美支持中文提示词，具备极强的文本空间解析、原生多语种生成及交互编辑（Inpainting/局部微调）特色，可极其高效地创作出高对比度的黑白简笔画。
    *   其 2K 级高精度输出对后续二值化压缩算法（`apply_line_art_filter` -> 320x320 1-bit 排包）具有完美的保真度，能产生边缘极致锐利、无灰色杂质的打印位图，极大提升热敏打印机的输出质感。
3.  **向量数据库与语义分析层 (Vector DB & Embeddings)**：
    *   每次对话后，提取「儿童输入文本 + AI 老师回复文本 + 情绪/心理成长标注元数据」。
    *   调用 **Doubao-embedding-vision** 模型将文本与视觉标签转为高维稠密向量。
    *   持久化存储在向量数据库（如 `ChromaDB` / `pgvector` / `Milvus`）中，便于进行跨越时间周期的儿童心理变迁检索、情感异常检测。
4.  **专业儿童心理知识库 (Empathetic Agent KB)**：
    *   内置儿童发展心理学经典理论（如皮亚杰认知发展理论、埃里克森社会心理发展阶段、蒙台梭利教育法等）。
    *   AI 在对话时主动引入知识库内的引导性问题，生成结构化分析日志，并最终在 Web 报告端生成「儿童成长多维评估雷达图与建议报告」。

---

## 二、 豆包 API 集成核心规约 (API Blueprints)

所有的豆包模型接口统一采用火山方舟平台的通用 API 密钥及鉴权方式进行调用。

*   **统一 API KEY**: `05a5b825-69f6-40ff-93e9-7493c05e4fb0`
*   **统一 Base URL**: `https://ark.cn-beijing.volces.com/api/v3`

### 1. 豆包端到端音频理解接口 (Doubao Audio LLM)
*   **使用模型**: `doubao-seed-2-0-lite-260428` (具备卓越的端到端音频转写、情感识别与多模态分析能力)
*   **调用协议规约 (OpenAI Python SDK 兼容模式)**:
    ```python
    import os
    import base64
    from openai import OpenAI

    client = OpenAI(
        api_key="05a5b825-69f6-40ff-93e9-7493c05e4fb0",
        base_url="https://ark.cn-beijing.volces.com/api/v3"
    )

    def encode_audio_to_base64(file_path):
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    # 调用示例：直接传送 Base64 音频并让模型进行语义理解、意图分流与心理判定
    def analyze_child_voice(audio_path, previous_context=""):
        base64_audio = encode_audio_to_base64(audio_path)
        
        response = client.chat.completions.create(
            model="doubao-seed-2-0-lite-260428",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一位极其温柔、懂得儿童心理学的幼儿园特级教师，名字叫'小探宝'。\n"
                        "你的任务是与小朋友进行顺畅好玩的互动聊天。在聊天的过程中，你需要暗中观察并评估小朋友的：\n"
                        "1. 情绪状态 (如：快乐、焦虑、沮丧、好奇、愤怒)\n"
                        "2. 语言表达能力 (如：句子完整度、逻辑连贯性)\n"
                        "3. 核心关切/当前兴趣点\n"
                        "请在回复中融入专业且无痕的温和引导，必要时主动提出启发性问题。保持回复简短、充满童趣（控制在 3-5 句话内）。"
                    )
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64_audio,
                                "format": "wav"
                            }
                        },
                        {
                            "type": "text",
                            "text": "这是小朋友刚才说的话，请你识别并温柔地回答。如果他提到了想要画画，请引导并鼓励他描述想画什么。"
                        }
                    ]
                }
            ],
            stream=False
        )
        return response.choices[0].message.content
    ```

### 2. 豆包 Seedream 5.0 pro 高精度生图接口
*   **使用模型**: `doubao-seedream-5-0-pro-260628` (最高分辨率 2K，支持极致画面控制、原生中英文文字排版与高精度局部修改)
*   **黑白简笔画 Prompt 装饰器策略**:
    原生支持中文后，系统直接构建高质感简笔画提示词：
    > `“简笔画，一个可爱卡通的{child_prompt}，高对比度，纯白底，纯黑线条，1-bit 扁平矢量线稿风格，无渐变，无阴影，居中，极简美学，适合热敏纸打印。”`
*   **生图协议规约 (OpenAI Python SDK 兼容模式)**:
    ```python
    def generate_child_drawing(child_prompt):
        # 原生中文 Prompt 组合装饰器，无需翻译
        optimized_prompt = f"简笔画，一个可爱卡通的{child_prompt}，高对比度，纯白底，纯黑线条，1-bit 扁平矢量线稿风格，无渐变，无阴影，居中，极简美学，适合热敏纸打印。"
        
        response = client.images.generate(
            model="doubao-seedream-5-0-pro-260628",
            prompt=optimized_prompt,
            size="2K",              # 分辨率设为 2K，提升线稿边缘细腻度，便于二值化算法处理
            response_format="url",   # 返回生成的图片公网链接
            watermark=False,         # 打印线稿不带水印
            extra_body={
                "optimize_prompt_options": {
                    "mode": "fast"   # 极速生图模式，缩短儿童在硬件端的等待焦虑
                }
            }
        )
        return response.data[0].url
    ```

### 3. 豆包多模态向量化接口 (Doubao Embedding Vision)
*   用于将儿童的心理评估报告、对话片段和画作标签生成高维向量，便于在向量库中进行聚类和相似度匹配。
*   **调用规约**:
    ```python
    def generate_doubao_embedding(text_content):
        # 封装豆包多模态/文本向量化请求
        response = client.embeddings.create(
            model="doubao-embedding-vision-240528",  # 示例多模态/文本向量化模型
            input=[text_content]
        )
        return response.data[0].embedding
    ```

---

## 三、 儿童成长与心理状态向量库结构设计 (Vector DB Schema)

为了给后期的心理与行为多维分析提供完备数据底座，向量数据库中的单条记录包含以下**精细元数据 (Metadata)** 维度：

| 元数据字段 | 类型 | 说明 | 示例值 |
| :--- | :--- | :--- | :--- |
| **`id`** | string | 唯一记录 UUID | `conv_9f81a7b2-3c81...` |
| **`device_token`** | string | 对应设备 ID 绑定 | `test-token-123` |
| **`child_text`** | string | 儿童说话转写文本 | `“小探宝，今天小狗在雨里跑，它会不会冷呀？”` |
| **`ai_response`** | string | 探奇老师温和回复文本 | `“宝贝真是一个善良的小暖男！小狗身上有暖和的毛毛，不过如果雨太大它也会想回家的。我们要不要给它画一个小雨伞呢？”` |
| **`drawing_prompt`** | string | 调用的 Seedream 简笔画提示词 | `“画一把红色的大雨伞”` |
| **`drawing_url`** | string | Seedream 生成的原始高保真 URL | `https://ark-project.tos-cn-beijing.volces.com/...png` |
| **`sentiment_state`**| string | 豆包提取的情绪底色 | `empathy_curiosity` (同理心/好奇心) |
| **`cognitive_tag`** | string | 对应认知发展阶段标记 | `preoperational_symbolic` (前运算阶段/符号表征) |
| **`linguistic_score`**| float | 语言表达完整度评分 ($0.0 \sim 1.0$) | `0.85` |
| **`psych_alert`** | boolean | 心理危机/消极情绪干预预警 | `False` |
| **`timestamp`** | integer | 发生时的 Epoch 时间戳 | `1781298412` |

---

## 四、 核心开发提示词模板 (Highly Reusable Prompt)

以下是供未来实际编码阶段直接复制，用以驱动 Code Agent 或团队研发进行「零偏差」快速实现的**黄金提示词规范**：

```markdown
# Role: 全栈系统集成架构专家 & Python 核心工程师

## Task: 
请在不破坏原有 FastAPI 核心路由逻辑、SQLite 历史数据库(`app_history.db`)、热敏打印 1-bit 二值化排包算法的前提下，为 `/app.py` 优雅地扩展集成豆包端到端音频大模型、最新 Doubao Seedream 5.0 pro 生图引擎及向量数据库，完善儿童心理智能诊断与绘画创作的闭环。

## Specifications:

### 1. 密钥与环境管理 (Environment Variables)
- 引入 `ARK_API_KEY`，对应值为 `"05a5b825-69f6-40ff-93e9-7493c05e4fb0"`。
- 引入端到端模型配置项 `ARK_AUDIO_MODEL = "doubao-seed-2.0-lite-260428"`。
- 引入最新绘画模型配置项 `ARK_DRAW_MODEL = "doubao-seedream-5.0-pro-260628"`。
- 在原有 `.env.example` 中补充上述说明，在 `.env` 中初始化。

### 2. 豆包端到端音频通信集成 (`/api/device/v1/voice`)
- 重构原本分立的 `preprocess_audio` -> `STT_Engine` -> `LLM_Agent` 流水线。
- 新流水线：
  a. 读取上传的 WAV 字节流。
  b. 进行基本的幅值和频率整流后，调用豆包 `doubao-seed-2-0-lite-260428` 端到端语音理解接口。
  c. 传参时，在 system prompt 设定「专业少儿心理学家与探奇老师」的双重人格，让模型直接在回包中同步返回文字结果与情绪诊断标签。

### 3. 原生中文 Seedream 5.0 pro 简笔画创作
- 在触发绘画决策（即原有的 `generate_drawing` 函数调用）时，由调用 Replicate 切换至调用 `doubao-seedream-5.0-pro-260628`。
- 传入原生中文 Prompt 组合装饰器，分辨率指定为 `"2K"`，且设置 `"optimize_prompt_options": {"mode": "fast"}` 以极速响应。
- 接口回包后，将获取的 2K 高画质图像 URL 输送至原有图像重采样过滤器 (`apply_line_art_filter` 转换为 320x320 纯黑白 1-bit 压包) 写入打印数据库队列。

### 4. 多维度心理成长特征提取器 (Child Psych Metrix Extractor)
- 每次对话生成时，利用豆包的结构化输出 (Structured Outputs / JSON Mode / Function Calling) 自动输出一个符合以下 JSON 格式的心理诊断包：
  ```json
  {
    "detected_emotions": ["快乐", "同理心"],
    "linguistic_richness_score": 0.9,
    "cognitive_milestone_ref": "感知运算至前运算阶段关联性",
    "attention_span_seconds": 15,
    "key_interests": ["动物", "天气环境"],
    "requires_attention": false
  }
  ```

### 5. 向量库持久化引擎 (Vector DB & Embeddings)
- 选择嵌入式轻量向量库 `ChromaDB` (在 Python 本地初始化，使用 `chromadb.PersistentClient(path="./psych_vectors.db")`)。
- 采用 `doubao-embedding-vision-240528` 对儿童原句、AI 回复进行双重 Embed，合并上述第 4 步输出的 JSON 心理诊断元数据、Seedream 生成的图片 URL 写入。
- 这样，每位绑定的设备 ID 用户都将在本地拥有专属的心理演变时序向量。

### 6. 儿童成长 Web 评估报告生成 (`/api/admin/reports/{device_token}`)
- 新增一个优雅的 REST 接口，用以拉取指定设备的向量库历史记录。
- 使用大模型对这些历史向量序列和元数据进行一键摘要，生成包含以下内容的报告：
  - 儿童情绪变化曲线统计数据。
  - 核心兴趣图谱 (Bento / Pie Chart 数据)。
  - 启发式的家庭共育指导意见。
  - 画作展示。
- 报告端通过优美的 Tailwind CSS + Recharts (网页格式) 前端呈现。

### 7. 健壮性与安全容灾
- 豆包接口设置 15s 强制超时，若火山方舟平台限流或网络抖动，自动无缝降级回退至原有的分立式 SiliconFlow / DeepSeek / Replicate 运行，确保儿童玩具端的绝对不卡顿。
```

---

## 五、 后续实施开发执行计划

1.  **第一步：基础 SDK 与依赖升级**
    *   在 `requirements.txt` 中引入 `volcengine-python-sdk[ark]` / `openai>=1.0.0` 兼容支持，并引入 `chromadb`。
2.  **第二步：环境变量注入**
    *   在 `.env` 中注入分配的豆包 Key，检验方舟终端连通性。
3.  **第三步：重构 `handle_voice` 音频端点与 `generate_drawing` 节点**
    *   将语音端点转接至 `doubao-seed-2-0-lite-260428` 平台，并配置 Seedream 5.0 pro 作为绘画默认驱动。
4.  **第四步：实现 Web 管理端报告页面**
    *   在 FastAPI 路由中挂载 `/reports`，调取 SQLite 和 ChromaDB 的复合统计结果，绘制优美的互动趋势和行为心理图谱。
