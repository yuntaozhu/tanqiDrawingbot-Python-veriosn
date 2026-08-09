# 🤖 AI 修复提示词：解决缓存部分匹配问题

> 这份提示词针对多轮对话时缓存返回错误片段导致图像生成错误的问题

---

## 问题简述

**现象**: 多轮对话时,第2句的缓存查询返回了错误的片段

```
用户句1: "查理王小猎犬在奔跑"
→ 生成图像并缓存 ✅

用户句2: "有个猫咪跟着他跑 画出来"
→ 缓存查询返回 "猫" 的缓存,而不是执行 ADD 融合
→ 结果只有猫,没有小猎犬 ❌
```

**根本原因**: 缓存的部分匹配逻辑过于宽泛,返回了长度太短的不相关缓存项

**部署日志证据**:
```
[DEBUG] [CACHE] Memory partial hit for drawing: '有个猫咪跟着他跑 画出来' -> '猫'
                 ↑ 用户输入                                          ↑ 返回的错误缓存
```

---

## 问题诊断

### 缓存工作流程

```
用户输入: "有个猫咪跟着他跑 画出来"
    ↓
normalize_prompt(): "猫咪跟着他跑"
    ↓
缓存查询:
  1. Redis 查询 → 无
  2. 精确匹配 → 无
  3. ❌ 部分匹配 → "猫" in "猫咪跟着他跑" → 匹配!
    返回 "猫" 的缓存
    ↓
    结果: 只有猫的画像 ❌
```

### 问题代码位置

**文件**: `src/cache.py` 第 58-61 行

```python
# 3. Memory cache partial match - 这里有问题!
for k, val in self.memory_cache.items():
    if k in norm_key or norm_key in k:  # ← 无条件匹配,太宽泛!
        print(f"[DEBUG] [CACHE] Memory partial hit for drawing: '{norm_key}' -> '{k}'")
        return val
```

**问题**:
- ❌ "猫" (1字) 包含在 "猫咪跟着他跑" (7字) 中
- ❌ 返回的缓存太短,缺乏上下文
- ❌ 对多轮对话的 ADD/MODIFY 操作不适用

---

## 修复任务

### 任务 1: 添加长度检查(快速修复) ⭐

**优先级**: 🔴 **高** | **时间**: 5 分钟 | **复杂度**: 低

**目标**: 防止返回过短的缓存项

**文件**: `src/cache.py`  
**行号**: 58-61 (DrawingCacheManager.get 方法中的部分匹配块)

#### 修改前

```python
def get(self, prompt: str) -> Optional[Dict[str, Any]]:
    norm_key = self.normalize_prompt(prompt)
    if not norm_key:
        return None

    # 1. Redis lookup
    if self.redis_client:
        try:
            data = self.redis_client.get(f"drawing:{norm_key}")
            if data:
                print(f"[DEBUG] [CACHE] Redis hit for drawing: '{norm_key}'")
                return json.loads(data)
        except Exception as e:
            print(f"[WARNING] [CACHE] Redis get error: {e}")

    # 2. Memory cache exact match
    if norm_key in self.memory_cache:
        print(f"[DEBUG] [CACHE] Memory exact hit for drawing: '{norm_key}'")
        return self.memory_cache[norm_key]

    # 3. Memory cache partial match - 问题在这里
    for k, val in self.memory_cache.items():
        if k in norm_key or norm_key in k:
            print(f"[DEBUG] [CACHE] Memory partial hit for drawing: '{norm_key}' -> '{k}'")
            return val

    return None
```

#### 修改后 - 快速修复版本

```python
def get(self, prompt: str) -> Optional[Dict[str, Any]]:
    norm_key = self.normalize_prompt(prompt)
    if not norm_key:
        return None

    # 1. Redis lookup
    if self.redis_client:
        try:
            data = self.redis_client.get(f"drawing:{norm_key}")
            if data:
                print(f"[DEBUG] [CACHE] Redis hit for drawing: '{norm_key}'")
                return json.loads(data)
        except Exception as e:
            print(f"[WARNING] [CACHE] Redis get error: {e}")

    # 2. Memory cache exact match
    if norm_key in self.memory_cache:
        print(f"[DEBUG] [CACHE] Memory exact hit for drawing: '{norm_key}'")
        return self.memory_cache[norm_key]

    # 3. Memory cache partial match - 改进版本
    for k, val in self.memory_cache.items():
        # 避免返回过短的缓存项(防止 "猫" 这样的片段匹配)
        if len(k) < 4:  # 最少 4 个字符
            continue
        
        # 检查是否部分匹配
        if k in norm_key or norm_key in k:
            # 避免返回长度差异太大的匹配
            length_ratio = len(k) / len(norm_key) if norm_key else 0
            
            # 缓存项长度应该在查询的 40-250% 之间
            if length_ratio < 0.4 or length_ratio > 2.5:
                print(f"[DEBUG] [CACHE] Partial match rejected (length mismatch): '{norm_key}' vs '{k}' (ratio: {length_ratio:.2f})")
                continue
            
            print(f"[DEBUG] [CACHE] Memory partial hit for drawing: '{norm_key}' -> '{k}' (quality: {length_ratio:.2f})")
            return val

    return None
```

**修改说明**:
```python
# 新增检查 1: 最小长度 >= 4 字符
if len(k) < 4:
    continue

# 新增检查 2: 长度比例在合理范围内 (0.4 - 2.5)
length_ratio = len(k) / len(norm_key)
if length_ratio < 0.4 or length_ratio > 2.5:
    continue
```

**为什么这样修复**:
- ✅ 防止 "猫" (1字) 被返回
- ✅ 允许合理的接近长度的匹配
- ✅ 保留部分匹配功能,但更安全
- ✅ 简单快速,5 分钟可完成

### 任务 2: 改进部分匹配逻辑(更安全)

**优先级**: 🟠 **中** | **时间**: 10 分钟 | **复杂度**: 中

**目标**: 添加语义相关性检查,确保匹配有意义

**文件**: `src/cache.py`  
**行号**: 49-61 (添加新的检查函数)

#### 修改内容

在 DrawingCacheManager 类中添加新方法:

```python
def _is_relevant_partial_match(self, query: str, cached_key: str) -> bool:
    """
    检查部分匹配是否语义相关
    返回 True 表示这是一个好的匹配,应该被接受
    """
    # 检查 1: 避免过短的缓存项
    if len(cached_key) < 4:
        return False
    
    # 检查 2: 避免长度差异过大
    if len(query) > 0:
        length_ratio = len(cached_key) / len(query)
        if length_ratio < 0.4 or length_ratio > 2.5:
            return False
    
    # 检查 3: 检查是否有明确的主体词汇匹配
    # (可选的更高级检查)
    # 主要动物和物体词汇
    entities = [
        "猫", "狗", "小狗", "兔", "兔子", "猪", "鸟", 
        "车", "房", "树", "花", "太阳", "月亮",
        "小猎犬", "查理王", "泰迪", "金毛"
    ]
    
    query_entities = [e for e in entities if e in query]
    cached_entities = [e for e in entities if e in cached_key]
    
    # 如果 query 和 cached_key 都有实体,要求有重叠
    # (这防止 "猫咪" 误匹配 "小狗")
    if query_entities and cached_entities:
        # 检查是否有共同的实体词
        overlap = any(e in cached_entities for e in query_entities)
        if not overlap:
            return False
    
    return True
```

然后修改 get 方法使用这个新函数:

```python
# 3. Memory cache partial match - 使用新的相关性检查
for k, val in self.memory_cache.items():
    if k in norm_key or norm_key in k:
        # 使用相关性检查
        if self._is_relevant_partial_match(norm_key, k):
            print(f"[DEBUG] [CACHE] Memory partial hit for drawing: '{norm_key}' -> '{k}'")
            return val
        else:
            print(f"[DEBUG] [CACHE] Partial match rejected (not relevant): '{norm_key}' vs '{k}'")

return None
```

### 任务 3: 禁用部分匹配(最安全方案)

**优先级**: 🟠 **中** | **时间**: 3 分钟 | **复杂度**: 极低

**目标**: 完全禁用部分匹配,只使用精确匹配

**文件**: `src/cache.py`  
**行号**: 58-61

#### 修改内容

```python
# 修改前 - 有部分匹配
def get(self, prompt: str) -> Optional[Dict[str, Any]]:
    norm_key = self.normalize_prompt(prompt)
    if not norm_key:
        return None

    # 1. Redis lookup
    if self.redis_client:
        try:
            data = self.redis_client.get(f"drawing:{norm_key}")
            if data:
                print(f"[DEBUG] [CACHE] Redis hit for drawing: '{norm_key}'")
                return json.loads(data)
        except Exception as e:
            print(f"[WARNING] [CACHE] Redis get error: {e}")

    # 2. Memory cache exact match
    if norm_key in self.memory_cache:
        print(f"[DEBUG] [CACHE] Memory exact hit for drawing: '{norm_key}'")
        return self.memory_cache[norm_key]

    # 3. ❌ Memory cache partial match - 被移除
    for k, val in self.memory_cache.items():
        if k in norm_key or norm_key in k:
            print(f"[DEBUG] [CACHE] Memory partial hit for drawing: '{norm_key}' -> '{k}'")
            return val

    return None

# 修改后 - 仅精确匹配
def get(self, prompt: str) -> Optional[Dict[str, Any]]:
    norm_key = self.normalize_prompt(prompt)
    if not norm_key:
        return None

    # 1. Redis lookup
    if self.redis_client:
        try:
            data = self.redis_client.get(f"drawing:{norm_key}")
            if data:
                print(f"[DEBUG] [CACHE] Redis hit for drawing: '{norm_key}'")
                return json.loads(data)
        except Exception as e:
            print(f"[WARNING] [CACHE] Redis get error: {e}")

    # 2. Memory cache exact match only
    if norm_key in self.memory_cache:
        print(f"[DEBUG] [CACHE] Memory exact hit for drawing: '{norm_key}'")
        return self.memory_cache[norm_key]

    # 部分匹配已禁用(被移除)
    # 理由: 多轮对话中的 ADD/MODIFY 操作需要融合提示词,
    # 而不是返回旧缓存的片段

    return None
```

**优缺点**:
- ✅ 完全安全,无法产生误匹配
- ✅ 简单快速,3 分钟完成
- ✅ 对多轮对话友好
- ❌ 缓存命中率下降 (但安全第一)

---

## 建议修复方案

### 快速方案 (今天)
```
执行任务 1: 添加长度检查
时间: 5 分钟
效果: 解决当前问题,保留部分缓存功能
```

### 安全方案 (如果长期发现问题)
```
执行任务 3: 禁用部分匹配
时间: 3 分钟
效果: 完全消除误匹配,缓存命中率略降
```

### 高级方案 (长期)
```
执行任务 2: 相关性检查
时间: 10 分钟
效果: 更智能的部分匹配,保留缓存收益
```

---

## 修改顺序(按优先级)

1. **第一步** (今天): 任务 1 - 添加长度检查 ✅ 快速解决
2. **第二步** (测试后): 任务 2 - 如果问题仍存在,添加相关性检查
3. **第三步** (如还有问题): 任务 3 - 禁用部分匹配

---

## 测试用例

完成修改后,需要测试以下场景:

### 测试 1: 原问题场景

```
缓存状态:
  "查理王小猎犬在奔跑": {...image1...}
  "猫": {...image2...}

输入1: "查理王小猎犬在奔跑"
预期: 返回 "查理王小猎犬在奔跑" 的缓存 ✅

输入2: "有个猫咪跟着他跑 画出来"
规范化后: "猫咪跟着他跑"
部分匹配检查:
  - "查理王小猎犬在奔跑" in "猫咪跟着他跑"? 否
  - "猫咪跟着他跑" in "查理王小猎犬在奔跑"? 否
  - "猫" in "猫咪跟着他跑"? 是,但被长度检查拒绝!

修复前: 返回 "猫" 的缓存 ❌
修复后(任务1): 返回 None,进行融合 ✅
修复后(任务3): 返回 None,进行融合 ✅
```

### 测试 2: 相同请求应该返回缓存

```
缓存: "查理王小猎犬在奔跑": {...}

输入: "查理王小猎犬在奔跑"
规范化: "查理王小猎犬在奔跑"
精确匹配: 匹配!
预期: 返回缓存 ✅
```

### 测试 3: 稍有不同的请求

```
缓存: "小红花": {...}

输入: "一朵小红花"
规范化: "小红花" (假设规范化后相同)
精确匹配: 匹配!
预期: 返回缓存 ✅
```

### 测试 4: 不相关的部分匹配应被拒绝

```
缓存: "猫": {...}

输入: "有个大象跟着小猫跑"
规范化: "大象跟着小猫跑"
部分匹配:
  - "猫" in "大象跟着小猫跑"? 是
  - 长度检查: len("猫") = 1 < 4? 是,被拒绝!

预期(修复前): 返回 "猫" 的缓存 ❌
预期(修复后): 返回 None ✅
```

---

## 检查清单

完成以下所有步骤:

### 代码修改
- [ ] 选择修复方案 (建议: 快速方案 + 安全方案)
- [ ] 修改 `src/cache.py` DrawingCacheManager.get() 方法
- [ ] 如选择任务2,添加 `_is_relevant_partial_match()` 方法
- [ ] 验证所有修改语法正确

### 测试
- [ ] 运行测试用例 1 (原问题)
- [ ] 运行测试用例 2 (相同请求)
- [ ] 运行测试用例 3 (稍有不同)
- [ ] 运行测试用例 4 (不相关匹配)
- [ ] 部署日志检查是否有 "partial match rejected" 消息

### 验证
- [ ] Railway 部署成功
- [ ] Web 服务 🟢 Online
- [ ] 测试多轮对话 (ADD 操作)
- [ ] 确认第2句的图像包含第1句的上下文

### 提交
- [ ] 所有代码修改完成
- [ ] 提交信息: "fix: improve cache partial match logic"
- [ ] 推送到 GitHub

---

## 预期修复结果

### 修复前 ❌

```
缓存查询: "有个猫咪跟着他跑 画出来"
部分匹配: "猫" in "猫咪跟着他跑" → 返回 "猫" 的缓存
结果: 只有猫,没有查理王小猎犬 ❌

日志:
[DEBUG] [CACHE] Memory partial hit for drawing: '有个猫咪跟着他跑 画出来' -> '猫'
```

### 修复后 ✅

```
缓存查询: "有个猫咪跟着他跑 画出来"
长度检查: len("猫") = 1 < 4 → 拒绝
部分匹配: 返回 None
结果: 执行 ADD 融合,正确生成有小猎犬和猫的图像 ✅

日志:
[DEBUG] [CACHE] Partial match rejected (length check): '猫咪跟着他跑' vs '猫'
[INFO] [INTEGRATION] Proceeding with prompt fusion (no cache hit)
```

---

## 相关文件

- **CACHE_PARTIAL_MATCH_BUG_ANALYSIS.md** - 详细的技术分析
- **src/cache.py** - 待修改文件 (主要)
- **src/routes/device.py** - 调用缓存的文件 (参考)

---

## 修复优先级和时间

| 步骤 | 方案 | 时间 | 优先级 | 效果 |
|-----|------|------|--------|------|
| 1️⃣ | 长度检查 | 5 min | 🔴 高 | 解决问题 |
| 2️⃣ | 相关性检查 | 10 min | 🟠 中 | 更安全 |
| 3️⃣ | 禁用部分匹配 | 3 min | 🔴 高 | 最安全 |

**建议**: 先执行任务 1,测试效果;如果问题解决则停止;否则执行任务 3。

---

**缺陷优先级**: 🔴 **高** - 影响多轮对话质量  
**复现难度**: 🟢 **易** - 只要缓存中有相关关键词就复现  
**修复复杂度**: 🟢 **低** - 5-10 行代码改动  
**风险等级**: 🟢 **低** - 改进启发式规则,不影响其他功能

