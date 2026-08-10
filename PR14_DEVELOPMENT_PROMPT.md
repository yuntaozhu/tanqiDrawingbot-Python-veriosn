# 🚀 PR #14: 修复启动阻塞导致的 502 错误 - 开发提示词

**问题**: FastAPI 应用在 Railway 上返回 502 `connection refused` 错误
**根本原因**: startup_event() 中的数据库清理函数阻塞了应用启动
**解决方案**: 改为异步后台任务 + 分批数据库处理

---

## 📋 问题背景

### 症状
- Railway 网络日志: 所有请求返回 502 `connection refused`
- Deploy 日志: 应用启动日志在 `[STARTUP] Starting database cleanup...` 后停止
- 应用进程: 仍在运行(CPU/内存指标正常),但无法接收请求
- 客户端: 无法访问 https://tanqibot.up.railway.app

### 根本原因分析

**当前代码流程** (src/main.py):
```python
@app.on_event("startup")
async def startup_event():
 # ... 获取锁 ...
 if should_run:
 cleanup_zero_vectors_in_db()  # ← 同步调用!
```

**问题链**:
1. `cleanup_zero_vectors_in_db()` 是**同步函数** (不是 async)
2. 在 async startup_event() 中直接调用,会**阻塞事件循环**
3. 函数内部: `db.query(PsychVectorDB).all()` - **一次性加载所有行**
4. 然后逐行处理和更新
5. 最后 `db.commit()` - **一次性提交**
6. 如果表很大或有数据库锁定,这个过程可能耗时 30 秒以上
7. 由于事件循环被阻塞,应用**无法启动完成**
8. FastAPI 无法进入运行状态,无法接收任何请求
9. Railway 网关尝试连接 → 超时 → 返回 502 connection refused

---

## ✨ 修复方案

### 修复 1: src/main.py - 异步后台运行

**关键改动**:

**之前**:
```python
@app.on_event("startup")
async def startup_event():
 # ... 获取锁 ...
 if should_run:
 try:
 cleanup_zero_vectors_in_db()  # ❌ 同步阻塞!
 except Exception as start_err:
 logger.error(...)
```

**之后**:
```python
@app.on_event("startup")
async def startup_event():
 # ... 获取锁 ...
 if should_run:
 import asyncio
 
 async def _run_cleanup_with_timeout():
 try:
 from src.crud import cleanup_zero_vectors_in_db
 logger.info("[STARTUP] Starting database cleanup...")
 
 loop = asyncio.get_running_loop()
 # 关键: run_in_executor 让同步函数在线程中运行,不阻塞事件循环
 await asyncio.wait_for(
 loop.run_in_executor(None, cleanup_zero_vectors_in_db),
 timeout=10,  # 10 秒超时
 )
 logger.info("[STARTUP] Cleanup completed.")
 except asyncio.TimeoutError:
 # ✅ 超时后继续启动,不让 app 卡住
 logger.warning("[STARTUP] Cleanup timed out; continuing startup...")
 except Exception as start_err:
 logger.error(f"[ERROR] Cleanup failed: {start_err}")
 finally:
 # 清理锁文件
 ...
 
 # ✅ 关键: 创建后台任务,不等待完成
 asyncio.create_task(_run_cleanup_with_timeout())
```

**为什么这样修复**:
1. ✅ `run_in_executor()` 在线程池中运行阻塞函数,不阻塞事件循环
2. ✅ `asyncio.wait_for(..., timeout=10)` 给 cleanup 最多 10 秒时间
3. ✅ 如果超时,捕获异常但继续启动(不 raise)
4. ✅ `asyncio.create_task()` 让 cleanup 在后台运行
5. ✅ `startup_event()` 立即返回,应用进入运行状态
6. ✅ cleanup 继续在后台处理,无碍应用接收请求

---

### 修复 2: src/crud.py - 分批数据库处理

**关键改动**:

**之前**:
```python
def cleanup_zero_vectors_in_db():
 db = SessionLocal()
 try:
 entries = db.query(PsychVectorDB).all()  # ❌ 一次性加载全表!
 updated_count = 0
 for e in entries:
 # 处理...
 
 if updated_count > 0:
 db.commit()  # ❌ 一次性提交
```

**之后**:
```python
def cleanup_zero_vectors_in_db(batch_size: int = 1000):
 """
 分批处理: 避免一次性加载全表,减少数据库锁定时间
 """
 db = SessionLocal()
 start_time = time.time()
 total_updated = 0
 total_scanned = 0
 
 try:
 total_rows = db.query(PsychVectorDB).count()  # 先计数,了解规模
 print(f"[INFO] Starting cleanup for {total_rows} rows...")
 
 offset = 0
 while True:
 # ✅ 关键: LIMIT + OFFSET 分批查询
 entries = (
 db.query(PsychVectorDB)
 .order_by(PsychVectorDB.id)  # 确保分页顺序一致
 .offset(offset)
 .limit(batch_size)  # 每批 1000 条
 .all()
 )
 
 if not entries:
 break  # 没有更多数据
 
 batch_updated = 0
 for e in entries:
 try:
 embedding = json.loads(e.embedding_json) if e.embedding_json else []
 # 检查是否为零向量
 is_zero = len(embedding) == 0 or all(x == 0.0 for x in embedding)
 
 metadata = json.loads(e.metadata_json) if e.metadata_json else {}
 changed = False
 
 if is_zero:
 if metadata.get("embedding_valid") is not False:
 metadata["embedding_valid"] = False
 metadata["embedding_available"] = False
 changed = True
 else:
 if metadata.get("embedding_valid") is not True:
 metadata["embedding_valid"] = True
 metadata["embedding_available"] = True
 changed = True
 
 if changed:
 e.metadata_json = json.dumps(metadata)
 batch_updated += 1
 except Exception as entry_err:
 print(f"[WARNING] Failed to process entry: {entry_err}")
 
 # ✅ 关键: 每批提交
 try:
 if batch_updated > 0:
 db.commit()
 else:
 db.rollback()
 except Exception as commit_err:
 print(f"[ERROR] Commit failed at offset {offset}: {commit_err}")
 db.rollback()
 
 # ✅ 记录进度
 total_updated += batch_updated
 total_scanned += len(entries)
 print(f"[INFO] Batch offset={offset} size={len(entries)} updated={batch_updated} "
 f"(scanned {total_scanned}/{total_rows} so far)")
 
 offset += batch_size
 
 # ✅ 记录完成统计
 duration = time.time() - start_time
 print(f"[INFO] Finished: scanned {total_scanned} rows, "
 f"updated {total_updated} in {duration:.2f}s")
 
 except Exception as e:
 print(f"[ERROR] Cleanup failed: {e}")
 try:
 db.rollback()
 except:
 pass
 finally:
 db.close()
```

**为什么这样修复**:
1. ✅ `LIMIT + OFFSET` 分页查询,每批只加载 1000 行
2. ✅ 内存占用有界 (最多 1000 行的对象)
3. ✅ 数据库锁定时间短 (每批独立的查询和提交)
4. ✅ 失败恢复 (一批失败不影响其他批)
5. ✅ 进度可见 (打印每批的进度)
6. ✅ 性能可测 (计时和统计)

---

## 🔧 技术细节

### 为什么 run_in_executor 有效?

```python
loop = asyncio.get_running_loop()
await asyncio.wait_for(
 loop.run_in_executor(None, cleanup_zero_vectors_in_db),
 timeout=10
)
```

- `run_in_executor(None, func)` 在**线程池**中运行 `func`
- 这个**不会阻塞事件循环**
- 事件循环仍可以处理其他任务(如 HTTP 请求)
- 如果函数超时(10 秒),抛出 `asyncio.TimeoutError`
- 我们捕获超时,记录警告,但继续启动

### 为什么分批处理重要?

假设表有 1,000,000 条记录:

**一次性加载** (之前):
```
db.query(PsychVectorDB).all()
 → 创建 100万个 ORM 对象
 → 内存占用 ~ 100MB+ 
 → 数据库锁定时间 ~ 30+ 秒
 → 应用完全卡住
```

**分批处理** (之后):
```
for offset in range(0, 1000000, 1000):
 query().offset(offset).limit(1000).all()
 → 每次创建 1000 个对象
 → 内存占用 ~ 1MB (恒定)
 → 数据库锁定时间 ~ 100ms * 1000 批 (可以间隔)
 → 应用仍可处理请求
```

---

## 📊 对比: 修复前后

| 方面 | 修复前 ❌ | 修复后 ✅ |
|------|----------|----------|
| **启动时长** | 无限期卡住 | < 10 秒 |
| **事件循环** | 被阻塞 | 不阻塞 |
| **应用响应** | 无法接收请求 | 立即可用 |
| **数据库加载** | 全表加载 | 分批加载 |
| **内存占用** | 随表大小增长 | 恒定 |
| **提交频率** | 一次 | 每批一次 |
| **超时处理** | 无 | 10 秒超时 |
| **错误恢复** | 全部失败 | 单批失败 |
| **日志信息** | 无 | 详细进度 |
| **用户体验** | 502 错误 | 正常响应 |

---

## 🧪 验证和测试

### 部署后验证

1. **检查应用启动**:
   ```bash
   # Railway Deploy 日志应该显示:
   Starting server on port 3000 with 4 workers...
   [STARTUP] Starting database cleanup...
   [STARTUP] Cleanup completed.  ← 或 timed out warning
   # 然后能处理请求
   ```

2. **检查请求响应**:
   ```bash
   curl https://tanqibot.up.railway.app/health
   # 应该返回 200 OK,不是 502
   ```

3. **检查日志进度**:
   ```
   [INFO] Starting cleanup for 12345 rows...
   [INFO] Batch offset=0 size=1000 updated=200 (scanned 1000/12345 so far)
   [INFO] Batch offset=1000 size=1000 updated=150 (scanned 2000/12345 so far)
   ...
   [INFO] Finished: scanned 12345 rows, updated 5000 in 8.34s
   ```

4. **网络日志**:
   ```bash
   # 应该没有 502 connection refused
   # 应该看到 200, 201, 400, 404 等正常状态码
   ```

---

## 💡 关键要点总结

### 修复原理
1. **异步化**: 同步阻塞函数 → 异步后台任务
2. **超时保护**: 给 cleanup 最多 10 秒时间
3. **不等待**: 使用 `create_task()`,不在 startup 中等待
4. **分批处理**: 全表加载 → 1000 行一批
5. **增量提交**: 一次提交 → 每批提交
6. **可观测**: 添加详细日志记录

### 为什么有效
- ✅ 应用启动不再被卡住
- ✅ cleanup 在后台继续进行
- ✅ 大表不会导致内存问题
- ✅ 数据库锁定时间大幅减少
- ✅ 超时后不让应用无法启动
- ✅ 失败不会导致全部数据丢失

### 预期效果
- 📊 启动时间: 从无限期 → 秒级
- 🔌 连接: 从 502 connection refused → 200 OK
- 💾 内存: 从峰值 100MB+ → 恒定 1-10MB
- 📈 吞吐: 从 0 → 正常处理请求
- 📝 可观测: 详细的 cleanup 进度日志

---

## 🚀 部署步骤

1. **合并 PR #14**
   ```bash
   # PR 会被自动检测并合并到 main
   ```

2. **Railway 自动部署**
   ```
   → 3-5 分钟完成构建和部署
   → 观察 Deploy 日志
   ```

3. **验证修复**
   ```bash
   curl https://tanqibot.up.railway.app/health
   # 应该返回 {"status": "healthy"}
   ```

4. **观察日志**
   ```
   查看 Railway Deploy 日志
   → 应该看到 Cleanup completed 或 timed out warning
   → 不应该再看到卡在 [STARTUP] Starting database cleanup...
   ```

---

## 📚 参考资源

### asyncio 文档
- `asyncio.wait_for()`: 为异步操作设置超时
- `loop.run_in_executor()`: 在线程池中运行同步函数
- `asyncio.create_task()`: 创建后台任务

### SQLAlchemy 最佳实践
- `LIMIT + OFFSET`: 大表分页查询的标准方法
- `commit()` vs `rollback()`: 事务管理
- `db.close()`: 释放数据库连接

### FastAPI 生命周期
- `@app.on_event("startup")`: 应用启动事件
- 一个任务阻塞 startup 会导致应用无法启动

---

## 📝 总结

这个修复解决了一个**经典的异步应用问题**:
- 在 async 函数中调用同步阻塞操作
- 导致整个应用卡住

解决方案是**标准的 asyncio 模式**:
- 使用 `run_in_executor()` 运行阻塞代码
- 使用 `wait_for()` 添加超时
- 使用 `create_task()` 在后台运行

对于数据库操作,**分批处理**是**大规模数据**的标准做法:
- 避免内存溢出
- 减少数据库锁定
- 提高容错性

修复后,应用应该能在 Railway 上正常运行,不再有 502 错误! 🎉

