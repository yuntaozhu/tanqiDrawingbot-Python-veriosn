# 📧 完整开发邮件模板

发送给: immanuel.zhu@gmail.com

---

## 邮件主题
```
tanqiDrawingbot 项目 - 完整开发资料已准备(代码集成 + 数据库架构)
```

---

## 邮件正文

亲爱的 Immanuel,

感谢你的支持!我们的多轮对话绘画应用(tanqiDrawingbot)已完成数据库架构和业务逻辑设计,现在需要进行服务器端代码集成。

我已准备了**完整的开发资料包**,包括:

### 📋 文档清单

#### 1️⃣ DEVELOPER_PROMPT.md (703 行)
**完整的开发提示词 - AI 按照此指南进行代码开发**
- 项目背景和核心需求
- 4 个详细的开发任务(带完整代码示例)
- 5 个实现步骤(每步都有代码片段)
- 7 个测试场景(验证多轮对话功能)
- 11 项集成检查清单
- 关键实现细节(Prompt 融合规则、错误处理)
- 完成标准(4 个质量标准)

#### 2️⃣ DATABASE_SCHEMA_REFERENCE.md (628 行)
**完整的数据库架构参考 - AI 了解数据结构和 CRUD 操作**
- 数据库概览
- 2 个表的详细字段定义
- JSONB 数据结构示例
- SQLAlchemy 模型定义
- 7 个常用 SQL 查询
- 所有 Python CRUD 方法说明
- 完整的数据流示例
- 性能建议和数据验证规则

#### 3️⃣ QUICK_DB_INIT.md
**SQL 初始化快速指南 - 3 步完成数据库设置**

#### 4️⃣ DATABASE_INIT_GUIDE.md
**SQL 初始化详细指南 - 详细的步骤和故障排查**

#### 5️⃣ IMPLEMENTATION_STATUS.md
**项目完整进度总结**

### 🎯 任务概览

| 任务 | 说明 | 预计时间 |
|-----|------|--------|
| **任务 1** | 修改 `src/routes/device.py` - 核心集成 | 1.5-2 小时 |
| **任务 2** | 新增 `/api/device/v1/conversation-history` API | 0.5 小时 |
| **任务 3** | 新增 `/api/device/v1/conversation-reset` API | 0.5 小时 |
| **任务 4** | 创建后台清理任务 `src/background_tasks.py` | 0.5 小时 |
| **总计** | - | **2-4 小时** |

### 📊 数据库结构一览

#### 表 1: conversation_contexts (用户会话上下文)
- **主键**: device_token (用户唯一标识)
- **核心字段**:
  - message_history (JSONB): 完整的对话历史
  - scene_elements (TEXT[]): 当前画面的元素列表
  - last_generated_prompt: 最后一次的绘图 Prompt
  - last_operation_type: 最后的操作类型(create/add/modify/remove)
  - current_image_url: 当前图片 URL

#### 表 2: drawing_history (绘画历史记录)
- **主键**: job_id (绘画任务 ID)
- **外键**: device_token → conversation_contexts
- **记录**: 每次绘画的完整信息(Prompt、图片 URL、时间等)

### 💾 已有的 Python 模块

```
✅ src/conversation_models.py - SQLAlchemy ORM 模型(ready)
✅ src/conversation_crud.py - 7 个数据库 CRUD 方法(ready)
✅ src/operation_recognizer.py - 操作识别引擎(ready)
✅ src/prompt_fusion.py - Prompt 融合引擎(ready)
✅ src/database.py - 数据库连接配置(已更新)
```

### 🚀 如何使用这些资料

#### Step 1: 阅读开发提示词
- 打开 DEVELOPER_PROMPT.md
- 理解 4 个任务和实现步骤

#### Step 2: 参考数据库架构
- 打开 DATABASE_SCHEMA_REFERENCE.md
- 了解表结构、字段定义、CRUD 方法

#### Step 3: 按照提示词编写代码
- 修改 `src/routes/device.py`
- 新增 2 个 API 端点
- 创建后台清理任务

#### Step 4: 验证实现
- 按照 11 项检查清单检查
- 执行 7 个测试场景
- 提交代码到 GitHub

### 📚 项目链接

| 资源 | 链接 |
|-----|------|
| **GitHub 仓库** | https://github.com/yuntaozhu/tanqiDrawingbot-Python-veriosn |
| **DEVELOPER_PROMPT.md** | https://github.com/yuntaozhu/tanqiDrawingbot-Python-veriosn/blob/sandbox/343aad6a-bab5-48f2-bb49--hoc2/DEVELOPER_PROMPT.md |
| **DATABASE_SCHEMA_REFERENCE.md** | https://github.com/yuntaozhu/tanqiDrawingbot-Python-veriosn/blob/sandbox/343aad6a-bab5-48f2-bb49--hoc2/DATABASE_SCHEMA_REFERENCE.md |
| **所有文档** | https://github.com/yuntaozhu/tanqiDrawingbot-Python-veriosn/tree/sandbox/343aad6a-bab5-48f2-bb49--hoc2 |

### ✨ 核心特性

实现完成后的效果:

**多轮对话支持** ✅
```
用户: "画查理王小猎犬奔跑"
  → 返回: [小猎犬]的画面

用户: "在小兔子旁边增加一个小狗"
  → 返回: [小猎犬 + 小兔子 + 小狗]的画面

用户: "把小狗的颜色改成白色"
  → 返回: [小猎犬 + 小兔子 + 白色小狗]的画面
```

**API 端点** ✅
- GET `/api/device/v1/conversation-history` - 查看对话历史
- POST `/api/device/v1/conversation-reset` - 重置会话

**自动清理** ✅
- 后台任务每小时运行一次
- 自动删除 24 小时未活跃的会话

### 🔧 技术栈

- **框架**: FastAPI (Python)
- **数据库**: PostgreSQL (Railway)
- **ORM**: SQLAlchemy 2.0+
- **预计代码行数**: 200-300 行新增代码

### ⏱️ 预计时间表

```
Day 1: 
- 阅读文档(1 小时)
- 完成任务 1(2 小时)
- 测试任务 1(1 小时)

Day 2:
- 完成任务 2-4(1-2 小时)
- 完整测试(1 小时)
- 提交 GitHub(30 分钟)
```

---

## 资料包内容

### 完整的开发提示词(DEVELOPER_PROMPT.md)

[复制下面的完整提示词内容到邮件中,或直接链接 GitHub]

---

### 完整的数据库架构参考(DATABASE_SCHEMA_REFERENCE.md)

[复制下面的完整数据库参考内容到邮件中,或直接链接 GitHub]

---

## GitHub 操作指南

### 克隆仓库
```bash
git clone https://github.com/yuntaozhu/tanqiDrawingbot-Python-veriosn.git
cd tanqiDrawingbot-Python-veriosn
git checkout sandbox/343aad6a-bab5-48f2-bb49--hoc2
```

### 查看文档
```bash
# 打开提示词
cat DEVELOPER_PROMPT.md

# 打开数据库参考
cat DATABASE_SCHEMA_REFERENCE.md
```

### 完成开发后
```bash
# 创建新分支
git checkout -b feat/conversation-integration

# 提交代码
git add .
git commit -m "Implement conversation context integration"

# 推送并创建 PR
git push origin feat/conversation-integration
# 然后在 GitHub 网页上创建 PR 到 main
```

---

## 后续支持

如有任何问题或需要澄清,可以随时联系。这份资料已经包含了:
- ✅ 完整的代码指导
- ✅ 详细的数据库架构
- ✅ 具体的实现步骤
- ✅ 测试场景和验证方法
- ✅ 错误处理建议

期待看到你的代码实现! 🚀

---

**项目信息**:
- 项目名: tanqiDrawingbot 多轮对话绘画应用
- 功能: 实现多轮对话上下文管理系统
- 预计工作量: 2-4 小时
- 难度: 中等

---

祝开发顺利!

