# 🐛 缓存部分匹配 Bug 分析报告

## 问题描述

**用户对话**:
```
用户句1: "查理王小猎犬在奔跑"
用户句2: "有个猫咪跟着他跑 画出来"
```

**预期结果**: 基于第1句的查理王小猎犬,增加一只猫咪跟着它跑  
**实际结果**: 缓存返回的只是 "猫" (很短的提示词),导致图像质量下降

**部署日志证据**:
```
[DEBUG] [CACHE] Memory partial hit for drawing: '有个猫咪跟着他跑 画出来' -> '猫'
                                                ↑ 用户输入                    ↑ 缓存返回的错误匹配
```

---

## 根本原因分析

### 问题代码位置

**文件**: `src/cache.py` 第 58-61 行

```python
# 部分匹配逻辑 - 这里有问题!
for k, val in self.memory_cache.items():
    if k in norm_key or norm_key in k:
        print(f"[DEBUG] [CACHE] Memory partial hit for drawing: '{norm_key}' -> '{k}'")
        return val
```

### 问题分析

#### 1️⃣ **缓存键问题**

用户句1 经过 normalize_prompt 处理后被缓存为 "查理王小猎犬在奔跑"

当用户句2 "有个猫咪跟着他跑 画出来" 来时:
```
原始输入: "有个猫咪跟着他跑 画出来"
↓ normalize_prompt() 处理
规范化后: "猫咪跟着他跑" (或类似)
↓ 部分匹配检查
遍历缓存: {"查理王小猎犬在奔跑": {...}, "猫": {...}, ...}
匹配条件: if k in norm_key or norm_key in k
         "猫" in "猫咪跟着他跑" ✓ 匹配!
返回: 之前缓存的单独 "猫" 的画像
```

#### 2️⃣ **部分匹配过于宽泛**

部分匹配逻辑使用了简单的字符串包含检查:
```python
if k in norm_key or norm_key in k:
    return val
```

**问题**:
- ❌ "猫" 出现在 "猫咪跟着他跑" 中 → 匹配
- ❌ 即使 "猫" 是缓存中的一个短片段,也会被返回
- ❌ 没有考虑匹配质量(match quality)
- ❌ 没有考虑缓存项的长度(可能 "猫" 是残留的测试数据)

#### 3️⃣ **缺乏匹配质量评估**

部分匹配应该满足:
```
理想: "有个猫咪跟着他跑" 匹配 "查理王小猎犬在奔跑 增加猫咪"
    → 这是有意义的上下文扩展

现实: "有个猫咪跟着他跑" 匹配 "猫" 
    → 过于简短,缺乏上下文
```

---

## 问题链条

```
用户输入: "有个猫咪跟着他跑 画出来"
    ↓
规范化: normalize_prompt() 
    → "猫咪跟着他跑"
    ↓
查找缓存:
  1. Redis 查询 → 无结果
  2. 精确匹配 → 无结果  
  3. 部分匹配 → ❌ 错误匹配!
    ↓
    缓存中遍历: {"查理王小猎犬在奔跑": {...}, "猫": {...}}
    检查条件: if "猫" in "猫咪跟着他跑"
    匹配! → 返回 "猫" 的缓存数据
    ↓
    返回结果: 只有 "猫" 的简短画像
    ↓
    图像质量: ❌ 失去了之前的查理王小猎犬上下文
```

---

## 为什么这是问题?

### 多轮对话的上下文丢失

**期望的流程**:
```
句1: "查理王小猎犬在奔跑" → 缓存 "查理王小猎犬在奔跑"
句2: "有个猫咪跟着他跑" → ADD 操作 → 融合为 "查理王小猎犬和猫咪在奔跑"
               ↓ 需要融合的提示词,不是缓存查询
```

**实际的流程**:
```
句1: "查理王小猎犬在奔跑" → 缓存 "查理王小猎犬在奔跑"
句2: "有个猫咪跟着他跑" → 部分匹配缓存
               ↓ 错误返回 "猫" 的缓存
结果: 只画猫,没有小猎犬 ❌
```

### 缓存的作用被滥用

缓存应该用于:
```
✅ 完全相同或非常相似的请求 (如 "画一个猫" 再次请求)
✅ 完全的 fused_prompt 匹配 (多轮融合后的完整提示词)
```

不应该用于:
```
❌ 部分概念的匹配 (如 "猫咪跟着他跑" 匹配 "猫")
❌ 跨多轮对话的部分上下文恢复
```

---

## 问题的影响

| 场景 | 预期 | 实际 | 影响 |
|-----|------|------|------|
| 多轮 ADD 操作 | 保留上一张图,添加新元素 | 返回新元素的缓存,丢失旧上下文 | 🔴 严重 |
| 多轮 MODIFY 操作 | 修改已有图 | 如果概念匹配,返回简短缓存 | 🔴 严重 |
| 首次绘画 | 生成完整图 | 如果有部分匹配,返回片段缓存 | 🔴 严重 |

---

## normalize_prompt 的问题

**文件**: `src/cache.py` 第 37-44 行

```python
def normalize_prompt(self, prompt: str) -> str:
    if not prompt:
        return ""
    p = prompt.strip()
    p = re.sub(r'^(请|帮我|想要|可以|给我|你能|画一个|画一只|...|画)', '', p)
    p = re.sub(r'(的简笔画|的线稿|图|图片|画|吧|吗|呀|哦|啦)$', '', p)
    return p.strip() or prompt.strip()
```

**问题**:
- ❌ 移除了太多前缀/后缀,可能导致不同的输入规范化为相同的值
- ❌ "有个猫咪跟着他跑 画出来" 和 "猫" 规范化后都可能太短
- ❌ 缺少语义信息,只做字符串处理

---

## 修复方案

### 方案 1: 改进部分匹配逻辑(推荐) ⭐⭐⭐

**核心思路**: 添加匹配质量检查,避免返回不相关的短缓存

#### 修复 1: 添加最小长度检查

**文件**: `src/cache.py` 第 58-61 行

```python
# 修改前 - 无条件部分匹配
for k, val in self.memory_cache.items():
    if k in norm_key or norm_key in k:
        print(f"[DEBUG] [CACHE] Memory partial hit for drawing: '{norm_key}' -> '{k}'")
        return val

# 修改后 - 添加长度检查
for k, val in self.memory_cache.items():
    # 避免返回过短的缓存项(可能是残留的测试数据或片段)
    if len(k) < 4:  # 最少 4 个字符,防止 "猫" "狗" 这样的单字符匹配
        continue
    
    # 避免返回长度差异太大的匹配
    if k in norm_key or norm_key in k:
        length_ratio = len(k) / len(norm_key) if norm_key else 0
        # 如果缓存项长度不到查询的 50%,可能不是好的匹配
        if length_ratio < 0.5 or length_ratio > 2.0:
            print(f"[DEBUG] [CACHE] Partial match rejected (length mismatch): '{norm_key}' vs '{k}'")
            continue
        
        print(f"[DEBUG] [CACHE] Memory partial hit for drawing: '{norm_key}' -> '{k}'")
        return val
```

#### 修复 2: 添加语义相关性检查

```python
# 更高级的修复 - 检查关键词
def _is_relevant_match(self, query: str, cached_key: str) -> bool:
    """
    检查部分匹配是否语义相关
    """
    # 如果缓存项包含的是 ADD/MODIFY 操作结果,保留
    # 如果缓存项太短或太不同,拒绝
    
    # 简单启发式规则:
    if len(cached_key) < 4:
        return False
    
    # 检查是否都包含实体名词(而不是动词或修饰词)
    entities = ["猫", "狗", "小狗", "兔", "猪", "鸟", "车", "房", "树", "花"]
    query_entities = [e for e in entities if e in query]
    cached_entities = [e for e in entities if e in cached_key]
    
    # 如果两者的实体名词不重叠,拒绝匹配
    if query_entities and cached_entities:
        if not any(e in cached_entities for e in query_entities):
            return False
    
    return True
```

### 方案 2: 禁用部分匹配

**文件**: `src/cache.py` 第 58-61 行

```python
# 简单修复 - 禁用部分匹配,只用精确匹配
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

    # 2. Memory cache exact match only (移除部分匹配)
    if norm_key in self.memory_cache:
        print(f"[DEBUG] [CACHE] Memory exact hit for drawing: '{norm_key}'")
        return self.memory_cache[norm_key]

    # 部分匹配被完全禁用
    return None
```

**优缺点**:
- ✅ 简单安全,避免所有误匹配
- ❌ 缓存命中率下降,某些场景无法复用

### 方案 3: 多轮对话感知的缓存

这是更高级的解决方案,需要修改架构:

```python
# 在 context 中存储已缓存的 fused_prompt
# 后续的 ADD/MODIFY 操作直接使用 fused_prompt,不走缓存查询
# 只有新的 CREATE 操作才进行缓存查询
```

---

## 建议修复优先级

| 方案 | 优先级 | 复杂度 | 效果 | 时间 |
|-----|--------|--------|------|------|
| 1️⃣ 最小长度检查 | 🔴 高 | 低 | 立即解决 | 5 min |
| 2️⃣ 相关性检查 | 🟠 中 | 中 | 更安全 | 10 min |
| 3️⃣ 禁用部分匹配 | 🟠 中 | 低 | 完全安全 | 3 min |
| 4️⃣ 多轮感知缓存 | 🟡 低 | 高 | 最优 | 30 min |

**建议方案**: **方案 1 + 方案 3** 的组合
- 短期: 添加长度检查(立即修复)
- 长期: 禁用部分匹配,改用融合感知缓存

---

## 测试用例

修复后应该通过以下测试:

```python
# 测试 1: 多轮 ADD 操作 (原问题)
input1 = "查理王小猎犬在奔跑"
cache_set("查理王小猎犬在奔跑", {...image1...})

input2 = "有个猫咪跟着他跑 画出来"
# 预期: 返回 None (不使用缓存,进行融合)
# 实际(修复前): 返回 "猫" 的缓存 ❌
# 实际(修复后): 返回 None ✅

# 测试 2: 相同的请求应该返回缓存
input = "查理王小猎犬在奔跑"
cache_set("查理王小猎犬在奔跑", {...image...})
input = "查理王小猎犬在奔跑"  # 相同请求
# 预期: 返回缓存 ✅

# 测试 3: 稍有不同的请求不应返回缓存
input = "查理王小猎犬在奔跑"
cache_set("查理王小猎犬在奔跑", {...image...})
input = "查理王小猎犬在奔跑的样子"  # 稍有不同
# 预期: 返回 None (规范化后仍有差异)

# 测试 4: 短缓存项不应匹配
# 假设缓存中有残留的 "猫"
cache_memory = {"查理王小猎犬": {...}, "猫": {...}}
input = "有个猫咪跟着他跑"
# 预期(修复前): 返回 "猫" 的缓存 ❌
# 预期(修复后): 返回 None ✅
```

---

## 相关代码位置

| 文件 | 行号 | 问题 |
|-----|------|------|
| cache.py | 37-44 | normalize_prompt 可能过度规范化 |
| cache.py | 58-61 | 部分匹配逻辑过于宽泛 |
| routes/device.py | 110-120 | 缓存查询被用于 ADD/MODIFY 操作 |
| prompt_fusion.py | - | 融合结果不应再进行缓存查询 |

---

## 根本问题总结

| 层级 | 问题 | 根本原因 |
|-----|------|---------|
| 🔴 直接 | 部分匹配返回短缓存 | "猫" 包含在 "猫咪跟着他跑" 中 |
| 🔴 设计 | 部分匹配用于多轮对话 | 缓存设计没考虑融合提示词 |
| 🟠 架构 | 缓存是全局的,不感知上下文 | 没有按照多轮对话需求设计 |

**修复思路**: 
- 短期: 改进部分匹配的启发式规则
- 长期: 改用融合感知的缓存机制

---

**优先级**: 🔴 **高** - 影响多轮 ADD/MODIFY 操作  
**缺陷类型**: 逻辑错误(过度匹配)  
**影响范围**: 所有使用缓存的多轮对话  
**复现率**: 100% (当缓存中有相关关键词时)

