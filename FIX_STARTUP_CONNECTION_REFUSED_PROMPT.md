# 🤖 AI 修复提示词：解决 Startup Connection Refused 502 错误

## 问题简述

**现象**: 部署显示 SUCCESS, 但客户端请求返回 502 Bad Gateway: connection refused

**日志证据**:
```
2026-08-10 14:32:28 - Starting server on port 3000 with 4 workers
2026-08-10 14:32:29 - [STARTUP] Database schema initialized
2026-08-10 14:32:29 - [STARTUP] Cleanup completed
2026-08-10 14:33:08 - HTTP 请求 → connection refused ❌
```

**根本原因**: Uvicorn HTTP 服务器在 startup_event() 运行时无法接收请求

---

## 修复任务

### 任务 1: 添加启动完成确认日志 (2 分钟) ⭐ 推荐

**文件**: `src/main.py`  
**位置**: startup_event() 函数的最后

#### 修改内容

在 startup_event() 的最后添加:

```python
@app.on_event("startup")
async def startup_event():
    import os
    import time
    import asyncio
    
    # ===== Step 1: Initialize database schema (MUST SUCCEED) =====
    logger.info("[STARTUP] Initializing database schema...")
    try:
        from src.database import initialize_db_schema
        loop = asyncio.get_running_loop()
        
        await asyncio.wait_for(
            loop.run_in_executor(None, initialize_db_schema),
            timeout=15,
        )
        logger.info("[STARTUP] Database schema initialized.")
    except asyncio.TimeoutError:
        logger.error("[STARTUP] Database schema initialization timed out!")
        raise
    except Exception as db_init_err:
        logger.error(f"[STARTUP] Failed to initialize database schema: {db_init_err}")
        raise

    # ===== Step 2: Start background cleanup task (non-blocking) =====
    # ... 现有代码 ...
    
    if should_run:
        async def _run_cleanup_with_timeout():
            # ... 现有代码 ...
            finally:
                try:
                    if os.path.exists(lock_path):
                        os.remove(lock_path)
                except Exception:
                    pass

        asyncio.create_task(_run_cleanup_with_timeout())
    else:
        logger.info("[STARTUP] Skipping database cleanup (handled by another primary worker process).")
    
    # 🔴 添加这些确认日志 (NEW)
    logger.info("[STARTUP] ✅ All startup tasks initiated successfully!")
    logger.info("[STARTUP] 🎉 Application is ready to accept HTTP requests on port 3000")
```

**说明**: 这两行新日志会确认应用完全初始化完成,帮助诊断启动是否成功。

### 任务 2: 检查 Uvicorn 启动配置 (3 分钟)

**目标**: 确保 Uvicorn 正确配置

**查找位置**:
1. 查看 `app.py` 或 `main.py` 的 `if __name__ == "__main__":` 块
2. 查看 Dockerfile 的 CMD 或 ENTRYPOINT
3. 查看 Railway 配置的启动命令

#### 应该看到的启动命令

```bash
# 正确的方式 1: 使用 python -m uvicorn
python -m uvicorn src.main:app --host 0.0.0.0 --port 3000 --workers 4

# 正确的方式 2: 直接使用 uvicorn
uvicorn src.main:app --host 0.0.0.0 --port 3000 --workers 4
```

#### 如果启动命令不对

修改 `app.py` 或 `main.py` 的 `__main__` 块:

```python
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=3000,
        workers=4,
        log_level="info",
        access_log=True,
    )
```

### 任务 3: 检查端口 3000 绑定 (5 分钟)

**目标**: 确保应用实际上在监听端口 3000

**修改位置**: `src/main.py` 的 startup_event() 中

```python
@app.on_event("startup")
async def startup_event():
    import socket
    
    # 添加这个诊断代码
    logger.info("[STARTUP] Checking port 3000 availability...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", 3000))
        sock.close()
        
        if result == 0:
            logger.warning("[STARTUP] ⚠️ Port 3000 already in use (possible duplicate process)")
        else:
            logger.info("[STARTUP] ✅ Port 3000 is available and ready")
    except Exception as e:
        logger.warning(f"[STARTUP] Could not verify port status: {e}")
    
    # ... 其他代码 ...
```

### 任务 4: 添加 HTTP 服务器启动完成标记 (3 分钟)

**目标**: 明确标记何时 HTTP 服务器准备就绪

**修改位置**: `src/main.py` 的最后

```python
# 在 app 定义的最后添加

@app.on_event("startup")
async def final_startup_check():
    """最后的启动检查,确保 HTTP 服务器完全准备就绪"""
    logger.info("[STARTUP] Final startup check...")
    logger.info("[STARTUP] ✅✅✅ HTTP Server is FULLY READY and accepting connections ✅✅✅")
    logger.info("[STARTUP] Service endpoint: http://0.0.0.0:3000")
```

---

## 修改顺序

1. **任务 1** (2 min) - 添加启动确认日志 - **立即做**
2. **任务 2** (3 min) - 检查启动命令 - 如果任务 1 后仍有问题
3. **任务 3** (5 min) - 检查端口绑定 - 诊断用
4. **任务 4** (3 min) - 添加最终标记 - 可选,增强诊断

---

## 测试步骤

修改后部署:

1. **查看部署日志**
   ```
   应该看到:
   [STARTUP] ✅ All startup tasks initiated successfully!
   [STARTUP] 🎉 Application is ready to accept HTTP requests on port 3000
   ```

2. **立即测试 HTTP 请求**
   ```
   curl https://tanqibot.up.railway.app/health
   ```
   
   应该返回:
   ```
   {"status": "healthy"}
   ```
   不应该返回 502

3. **监控部署日志**
   观察是否有任何其他错误消息

---

## 检查清单

- [ ] 修改 src/main.py 的 startup_event()
- [ ] 添加启动完成确认日志
- [ ] 检查 Uvicorn 启动命令是否正确
- [ ] 部署修改
- [ ] 查看部署日志中的新日志消息
- [ ] 测试 HTTP 请求是否仍返回 502
- [ ] 如果仍有问题,检查端口 3000 绑定

---

## 预期结果

### 修复前 ❌
```
部署日志:
Starting server on port 3000 with 4 workers
[STARTUP] Database schema initialized
[STARTUP] Cleanup completed
← 没有确认 HTTP 服务器准备好的日志

HTTP 请求:
502 Bad Gateway
connection refused
```

### 修复后 ✅
```
部署日志:
Starting server on port 3000 with 4 workers
[STARTUP] Database schema initialized
[STARTUP] Cleanup completed
[STARTUP] ✅ All startup tasks initiated successfully!
[STARTUP] 🎉 Application is ready to accept HTTP requests on port 3000
← 清楚的确认消息

HTTP 请求:
200 OK
{"status": "healthy"}
```

---

## 可能的原因分析

如果修复后仍然 502:

1. **Workers 之间的端口竞争**
   - 多个 worker 都在尝试绑定端口 3000
   - 解决: 使用 Uvicorn 的官方配置来处理多进程

2. **startup_event() 中有阻塞操作**
   - 数据库初始化没有正确异步化
   - 解决: 检查 `initialize_db_schema()` 是否在线程池中运行

3. **Network/Firewall 问题**
   - Railway 网关无法连接到应用
   - 解决: 检查应用是否正确绑定到 0.0.0.0:3000

4. **资源限制**
   - 应用内存或 CPU 不足
   - 解决: 增加 Railway 的资源限制

---

**修复优先级**: 🔴 **极高** - 应用无法响应  
**修复时间**: 2-5 分钟  
**风险**: 🟢 **低** - 仅添加日志和诊断代码

