# 探奇 AI 机器人系统架构设计与拓扑文档 (System Architecture)

本篇文档详尽阐述了 **Toddler Drawing Dreamer (探奇智能对话与绘画机器人)** 全栈系统的技术架构、核心组件交互、以及多通道数据流转拓扑。系统采用轻量化设备/小端接入 + 云端大模型 + 多级本地缓存的架构模型，兼具高灵活性与极速交互响应。

---

## 一、 系统架构图 (Mermaid.js Specification)

你可以使用支持 Mermaid 的渲染器直接查看以下图形。图形直观表达了从微控制器硬件到云端 AI 算力底座的完整处理链：

```mermaid
graph TD
    %% ------------------ 物理设备与客户端 ------------------
    subgraph Client_Layer [智能硬件/客户端层 (device_client.py)]
        A1[麦克风录音 / MIC Input] -->|PCM 16bit WAV| A2[音频文件读取与封装]
        A2 -->|HTTP POST /api/device/v1/voice| B1
        A3[键盘输入 / Command] -->|HTTP POST /api/device/v1/chat| B2
        
        A4[定时轮询任务 / Cron Poll] -->|HTTP GET /api/device/v1/print-jobs| B3
        A5[Type-C 热敏打印机] <---|1-bit 压包位图 Hex| A4
    end

    %% ------------------ 服务端接口网关与路由 ------------------
    subgraph Server_Gateway [服务端网关与路由层 (FastAPI - src/main.py & src/routes.py)]
        B1{语音交互网关<br>POST /api/device/v1/voice}
        B2{文本交互网关<br>POST /api/device/v1/chat}
        B3{打印队列网关<br>GET /api/device/v1/print-jobs}
        B4{儿童心理诊断报告<br>GET /api/admin/reports/{token}}
        
        %% 权限拦截
        Auth[安全验证 x-device-token] -.-> B1
        Auth -.-> B2
        Auth -.-> B3
    end

    %% ------------------ 服务端核心业务流水线 ------------------
    subgraph Core_Pipeline [核心业务流转与算法引擎 (src/utils.py & src/services.py)]
        %% 语音预处理与STT
        P_Audio[音频预处理<br>1.带通滤波 80Hz-7kHz<br>2.幅值归一化 -1dB]
        STT_Engine{STT 调度器}
        STT_Cache[(stt_cache.json)]
        
        %% LLM 智能中控
        LLM_Agent[LLM 智能代理中控<br>System Prompt: 探奇老师]
        Tool_Call{意图分类与分流<br>Function Calling}
        
        %% TTS 与 绘图分支
        TTS_Engine{TTS 调度器}
        TTS_Cache[(tts_cache.json)]
        
        Draw_Engine{简笔画生成调度器}
        Line_Art[图像降维滤波<br>1. OpenCV二值化<br>2. 320x320重采样<br>3. 1-bit位图压缩压包]
        Print_DB[(SQLite / app_history.db - src/database.py)]
        
        %% 连接关系
        B1 --> P_Audio
        P_Audio --> STT_Engine
        STT_Engine <--> STT_Cache
        STT_Engine -->|转换文本| LLM_Agent
        
        B2 --> LLM_Agent
        LLM_Agent --> Tool_Call
        
        %% 分支 A: 温柔对话路径
        Tool_Call -->|纯语音对话| TTS_Engine
        TTS_Engine <--> TTS_Cache
        TTS_Engine -->|Base64 音频回传| B1
        TTS_Engine -->|Base64 音频回传| B2
        
        %% 分支 B: 绘画创意路径
        Tool_Call -->|触发 generate_drawing| Draw_Engine
        Draw_Engine --> Line_Art
        Line_Art -->|写入打印队列与历史| Print_DB
        Print_DB <--> B3
    end

    %% ------------------ 外部多云 AI 服务提供商 ------------------
    subgraph AI_Providers [多云 AI 模型提供商层 (云端服务)]
        %% STT / TTS 与端到端语音
        Cloud_STT[SiliconFlow & OpenAI]
        Cloud_TTS[SiliconFlow: tts-1]
        Cloud_Doubao_Audio[火山引擎: 豆包端到端音频大模型]
        
        %% LLM
        Cloud_LLM[DeepSeek-V3]
        
        %% Drawing / Embeddings
        Cloud_Doubao_Draw[火山引擎: Doubao Seedream 5.0 pro]
        Cloud_Doubao_Embed[火山引擎: Doubao-embedding-vision]
        Cloud_Draw_Fallback[Replicate & Ideogram (备用)]
        
        %% 核心连接
        STT_Engine <--> Cloud_STT
        LLM_Agent <--> Cloud_LLM
        
        Draw_Engine <--> Cloud_Doubao_Draw
        Draw_Engine <.->|Fallback| Cloud_Draw_Fallback
        
        STT_Engine <.->|端到端交互| Cloud_Doubao_Audio
        TTS_Engine <.->|端到端交互| Cloud_Doubao_Audio
        Cloud_Doubao_Embed <-->|心理成长向量| Print_DB
    end

    %% 样式声明
    style Client_Layer fill:#f5f7fa,stroke:#909399,stroke-width:2px;
    style Server_Gateway fill:#ecf5ff,stroke:#409eff,stroke-width:2px;
    style Core_Pipeline fill:#f0f9eb,stroke:#67c23a,stroke-width:2px;
    style AI_Providers fill:#fdf6ec,stroke:#e6a23c,stroke-width:2px;
```

---

## 二、 系统重构与设计模式 (Design Patterns & Refactoring)

为解决原有单体 `app.py` 膨胀过大（超 2200 行）、高耦合、难以扩展等问题，项目采用了 **分层架构模式 (Layered Architecture Pattern)** 与 **关注点分离 (Separation of Concerns)** 原则进行优雅重构。

重构后的目录结构与职责划分如下：

### 1. `app.py` (引导与启动入口)
*   **职责**：轻量级主程序入口，仅负责读取环境变量，并拉起 `uvicorn` 服务运行 `src/main.py` 中的 FastAPI 实例。
*   **模式**：**启动器模式 (Launcher Pattern)**。

### 2. `src/main.py` (应用实例化与中间件管理)
*   **职责**：负责实例化 FastAPI 应用程序，配置跨域访问（CORS），并统一挂载路由模块 `/src/routes.py`。

### 3. `src/config.py` (全局配置中心)
*   **职责**：统一管理与解析所有的系统环境变量、第三方云服务 API 密钥（如 `DEEPSEEK_API_KEY`, `ARK_API_KEY`）及基础连接参数。
*   **模式**：**配置单例模式 (Configuration Singleton Pattern)**。

### 4. `src/database.py` (持久化 ORM 抽象层)
*   **职责**：基于 SQLAlchemy 声明 SQLite 数据库模型，并统一封装所有的数据读写操作（如 `save_history_to_db`, `save_psych_vector`），隔离底层数据存储引擎。
*   **数据库表职责**：
    *   `GenerationHistoryDB`：存储简笔画画作的主角、中英文提示词、画作图片 base64 等。
    *   `FeedbackDB`：记录用户对画作的反馈打分。
    *   `PrintJobDB`：热敏打印待处理异步消费任务队列。
    *   `PsychVectorDB`：通过 `Doubao-embedding-vision` 提取的小朋友历史交流数据向量化表示，用于检索儿童心理偏好。
*   **模式**：**数据访问对象模式 (Data Access Object / Repository Pattern)**。

### 5. `src/utils.py` (算法与工具函数层)
*   **职责**：实现与核心网络框架无关的通用业务算法。
    *   `retry_with_backoff`：带指数避让和高可用容灾特性的高级重试装饰器。
    *   `preprocess_audio`：对原始音频执行 Butterworth 带通滤波降噪和幅值峰值归一化算法。
    *   `apply_line_art_filter`：基于 OpenCV 的 1-bit 二值化排包与图像降维过滤。
    *   `get_dhash`：计算感知哈希（64位差异哈希），用于图像指纹排重。
*   **模式**：**公用工具模式 (Utility / Helper Pattern)**。

### 6. `src/services.py` (第三方 AI 服务对接与多级缓存)
*   **职责**：包装外部云服务客户端。
    *   `DeepSeekAPI`：对接文本生成、语音识别（STT）和语音合成（TTS）。
    *   `DoubaoAPI`：集成火山引擎端到端音频大模型、Doubao Seedream 5.0 pro 生图引擎、以及 Doubao Embedding 向量处理。
    *   `ReplicateAPI` & `IdeogramAPI`：提供强大的画作备用生成。
    *   统一封装 `generate_image_with_fallback` 图像多源回退生成路由器。
*   **缓存机制**：
    *   `STT_CACHE` & `TTS_CACHE`：本地轻量级文件缓存，对相同音频/文本一秒回显。
*   **模式**：**代理模式 (Proxy Pattern) & 外观模式 (Facade Pattern) & 路由器/回退模式 (Fallback Routing)**。

### 7. `src/routes.py` (API 业务路由与业务编排)
*   **职责**：FastAPI APIRouter 注册点，定义了所有的核心 HTTP 交互接口、权限校验，以及 `process_llm_interaction` 和 `generate_growths_summary` 心理评估业务逻辑。

---

## 三、 核心流转分层描述

### 1. 客户端/硬件层 (Client Layer)
*   **物理设备模型**：代表嵌入式小车硬件、遥控中控芯片或开发中的模拟测试终端（`device_client.py`）。
*   **离线/在线指令双轨运行**：对高频控制词提供毫秒级匹配；而对于语义复杂的对话或绘画创意，将高清晰度的 PCM WAV 音频包或文本封包，通过网络同步上送。
*   **异步打印消费**：轮询请求专属设备 ID 的未完成打印任务。拉取到紧凑型的 `1-bit` 压包位图后，透传至热敏打印机头执行加热出纸。

### 2. 服务端网关与路由层 (Server Gateway)
*   **安全验证机制**：API 端点强制验证 HTTP Headers 中的 `x-device-token`，实现不同设备、不同儿童之间的数据深度隔离，并用于匹配专属成长分析报告。

### 3. 心理分析向量计算层 (Vector Storage & Report Engine)
*   **向量计算与存储**：聊天回复及交互文本通过 `Doubao-embedding-vision-240528` 转换为 1024 维的高维特征向量，调用 SQLite 中的余弦相似度（通过 numpy 实现）快速执行语义偏好分析。
*   **情绪与成长诊断（报告生成）**：大模型结合历史十余次儿童表达的词汇丰富度分数、关注热词、需要特别关注的情绪波动标记（如分离焦虑、恐惧等），动态撰写出极其专业温暖的“儿童成长与行为心理诊断意见”。
