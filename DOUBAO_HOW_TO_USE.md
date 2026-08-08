# 如何使用豆包 API 优先调用方案

## 快速开始(3 分钟)

### 步骤 1: 选择提示词文件

#### 📄 推荐方案(简洁快速)
**文件**: `DOUBAO_PRIORITY_QUICK_PROMPT.txt` ⭐ **推荐使用**
- 大小: 3.6 KB
- 时间: 3-5 分钟
- 包含: 清晰的修改位置 + 代码对比
- 适合: 快速让 AI 理解并修改

**用法**:
1. 打开 `DOUBAO_PRIORITY_QUICK_PROMPT.txt`
2. 复制全部内容
3. 粘贴给 AI(Claude/ChatGPT)
4. AI 会输出完整修改后的 `src/business_logic.py`

---

#### 📘 详细方案(学习理解)
**文件**: `DOUBAO_API_PRIORITY_PROMPT.md`
- 大小: 8 KB
- 时间: 10-15 分钟  
- 包含: 完整分析 + 修改要求 + 环境变量确认
- 适合: 想深入理解为什么要改

**用法**:
1. 先阅读 `DOUBAO_API_PRIORITY_PROMPT.md` 理解方案
2. 再用 `DOUBAO_PRIORITY_QUICK_PROMPT.txt` 给 AI

---

#### 🔧 代码参考方案
**文件**: `DOUBAO_API_PRIORITY_CODE_CHANGES.md`
- 大小: 12 KB
- 包含: 5 个修改位置的详细 diff
- 适合: 手工逐个修改(不推荐,用 AI 更快)

---

## 推荐工作流

### ✅ 最简单的方式(推荐)

```
1. 打开 DOUBAO_PRIORITY_QUICK_PROMPT.txt
   ↓
2. 复制全部内容给 AI
   ↓
3. AI 输出修改后的代码
   ↓
4. 保存为 src/business_logic.py
   ↓
5. git add . && git commit && git push
   ↓
6. 等待 Railway 自动部署
```

---

## 分步骤详解

### Step 1: 获取提示词

打开项目目录,找到这个文件:
```
DOUBAO_PRIORITY_QUICK_PROMPT.txt
```

### Step 2: 复制提示词

**方式 A: 直接复制**
```bash
cat DOUBAO_PRIORITY_QUICK_PROMPT.txt  # 查看内容
# 然后选择全部复制
```

**方式 B: 在编辑器中打开**
- VSCode: Ctrl+O 打开文件 → 全选 → 复制

### Step 3: 给 AI 提示词

**在 Claude 或 ChatGPT 中**:
```
粘贴提示词内容

【等 AI 生成代码】

AI 会输出完整的 src/business_logic.py 文件
```

### Step 4: 保存修改

**方式 A: 复制粘贴替换**
1. AI 生成的代码全部复制
2. 打开项目的 `src/business_logic.py`
3. 全选现有代码(Ctrl+A)
4. 粘贴新代码(Ctrl+V)
5. 保存(Ctrl+S)

**方式 B: 让 AI 生成完整文件**
```
给 AI 说:
"保存为 src/business_logic.py"
AI 会给你完整路径
```

### Step 5: 提交到 GitHub

```bash
cd /your/project

# 查看修改
git status

# 暂存修改
git add src/business_logic.py

# 提交
git commit -m "feat: prioritize Doubao API over DeepSeek"

# 推送
git push origin main
```

### Step 6: 等待部署

Railway 会自动:
1. 检测代码变更(约 1 分钟)
2. 开始构建(约 2-3 分钟)
3. 部署到容器(约 1 分钟)
4. 启动服务(约 30 秒)

**总时间**: 约 5-8 分钟

### Step 7: 验证成功

打开 Railway Dashboard → Deployments → Deploy Logs

**应该看到**:
```
Starting Container
Starting server on port 3000...
INFO: Uvicorn running on http://0.0.0.0:3000
```

打开服务 DNS 日志:
```
✅ 主要是 api.doubao.com 的请求
❌ 很少或没有 api.deepseek.com 的请求
```

---

## 常见问题

### Q1: 该用哪个提示词?
**A**: 新手用 `DOUBAO_PRIORITY_QUICK_PROMPT.txt`(快速版)

### Q2: 修改后需要手工测试吗?
**A**: 不需要。Railway 自动构建和部署。查看日志就能验证。

### Q3: 怎么知道豆包被优先调用了?
**A**: 
- 查看 Deploy Logs:应该看到 `[DEBUG] [FAST_PATH] Querying Doubao...`
- 查看 DNS 日志:应该主要是 `api.doubao.com`

### Q4: 如果修改出错怎么办?
**A**:
1. 查看 Build Logs 找错误信息
2. 让 AI 根据错误修复代码
3. 重新提交

### Q5: 可以只修改部分位置吗?
**A**: 不建议。要么全改,要么不改。部分改的话会导致不一致。

### Q6: DeepSeek 的 API Key 还需要吗?
**A**: 可以保留(作为备用),或者删除。
- 保留 = 豆包故障时自动降级到 DeepSeek
- 删除 = 豆包故障时只能返回错误提示

### Q7: 修改会影响现有功能吗?
**A**: 不会。只是改变了 API 调用的优先级:
- 豆包成功 = 和之前一样
- 豆包失败 = 降级到 DeepSeek(比之前更稳定)

---

## 修改前后对比

### 修改前(现在的问题)
```
用户请求 → DeepSeek API ✗ (总是用 DeepSeek)
                └── 不会调用豆包 ❌
```

日志:
```
api.deepseek.com 100%
api.doubao.com   0%
```

### 修改后(期望的结果)
```
用户请求 → 豆包 API ✓ (优先使用)
           ├─ 成功 = 返回结果 ✅
           └─ 失败 → DeepSeek API (备用) ✓
```

日志:
```
api.doubao.com   90%+ ✅
api.deepseek.com 0-10% (仅故障时)
```

---

## 文件清单

### 提示词文档
- ✅ `DOUBAO_PRIORITY_QUICK_PROMPT.txt` - **推荐使用**
- ✅ `DOUBAO_API_PRIORITY_PROMPT.md` - 详细版本
- ✅ `DOUBAO_API_PRIORITY_CODE_CHANGES.md` - 代码参考

### Dockerfile 相关(之前修复的)
- ✅ `Dockerfile` - 已修复权限问题
- ✅ README_DOCKERFILE_FIX.md - 快速参考

### 项目文件
- 📝 `src/business_logic.py` - 需要修改的文件

---

## 预计部署时间

| 步骤 | 时间 |
|------|------|
| 复制提示词 + 给 AI | 2 分钟 |
| AI 生成代码 | 1 分钟 |
| 保存并提交 | 2 分钟 |
| Railway 自动部署 | 5-8 分钟 |
| **总计** | **10-13 分钟** |

---

## 后续支持

如果修改后有问题:
1. 查看 Deploy Logs 找错误信息
2. 对比 `DOUBAO_API_PRIORITY_CODE_CHANGES.md` 中的代码
3. 让 AI 根据具体错误修复
4. 重新提交

**祝修改顺利!** ✨


