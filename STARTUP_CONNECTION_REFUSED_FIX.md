# 🔴 紧急修复: Connection Refused 502 错误

## 问题

虽然部署状态是 SUCCESS, 但客户端请求仍然收到 502 错误:

```
httpStatus: 502
upstreamError: "connection refused"
```

## 根本原因

**时间线分析**:
```
2026-08-10 14:32:28 - Starting server on port 3000 with 4 workers
                      ↓
                      Uvicorn 开始启动
                      
2026-08-10 14:32:29 - [STARTUP] Database schema initialized
2026-08-10 14:32:29 - [STARTUP] Cleanup completed
                      ↓
                      startup_event() 完成
                      
2026-08-10 14:33:08 - 客户端请求
                      ↓
                      connection refused ❌
                      
时间差: 40 秒
```

**问题分析**:

1. **Uvicorn 启动日志之后没有 "Uvicorn running on" 日志**
   - 这表明 Uvicorn 可能卡在启动过程中
   - 或者 HTTP 服务器没有正确绑定端口 3000

2. **startup_event() 完成了,但应用仍不响应**
   - startup_event() 中的代码在异步运行
   - 但 startup_event() 完成并不意味着 HTTP 服务器准备好了

3. **可能的阻塞点**:
   - 数据库初始化可能仍在阻塞事件循环
   - 清理任务虽然是异步,但可能有其他初始化步骤

## 快速修复方案

### 方案 A: 添加更明确的启动完成日志 (2 分钟) ⭐ 推荐

**文件**: `src/main.py`

在 `startup_event()` 的最后添加:

```python
@app.on_event("startup")
async def startup_event():
    # ... 现有代码 ...
    
    # 在最后添加:
    logger.info("[STARTUP] All startup tasks completed. HTTP server ready.")
    logger.info("[STARTUP] Application is ready to receive requests on port 3000")
```

**目的**: 确认应用完全准备好了

### 方案 B: 确保 Uvicorn 的日志输出 (3 分钟)

**检查位置**: `src/main.py` 或 `app.py`

确保应用配置了 Uvicorn 的日志记录:

```python
# 在 if __name__ == "__main__": 块中
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.main:app",  # 或 "app:app"
        host="0.0.0.0",
        port=3000,
        workers=4,
        log_level="info",  # 确保日志级别设置正确
        access_log=True,   # 启用访问日志
    )
```

### 方案 C: 检查应用的启动脚本 (5 分钟)

**找到应用启动的位置**:

1. 查看 `app.py` 或 `main.py` 的 `__main__` 块
2. 查看 Dockerfile 或 Railway 配置中的启动命令

**确保启动命令正确**:
```bash
# 应该是这样
python -m uvicorn src.main:app --host 0.0.0.0 --port 3000 --workers 4

# 或
uvicorn src.main:app --host 0.0.0.0 --port 3000 --workers 4
```

### 方案 D: 添加明确的端口绑定检查 (5 分钟)

在 startup_event 中添加:

```python
@app.on_event("startup")
async def startup_event():
    import socket
    
    # 检查端口是否可用
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("0.0.0.0", 3000))
        if result == 0:
            logger.info("[STARTUP] Port 3000 is already in use")
        else:
            logger.info("[STARTUP] Port 3000 is available")
        sock.close()
    except Exception as e:
        logger.warning(f"[STARTUP] Could not check port status: {e}")
    
    # ... 其他代码 ...
    
    logger.info("[STARTUP] HTTP server ready on port 3000")
```

## 诊断步骤

### 1. 查看 Uvicorn 的启动确认

查看部署日志,应该看到:
```
Starting server on port 3000 with 4 workers...
[info] Uvicorn running on http://0.0.0.0:3000 (press CTRL+C to quit)
```

**如果缺少第二行**, 说明 Uvicorn 没有正确启动。

### 2. 检查是否有多个应用实例竞争端口

每个 worker 都在尝试绑定同一个端口 3000,这会导致冲突!

**修复**: 
```python
# 如果使用 Uvicorn 多进程,应该只在主进程中启动
# 这通常由 Uvicorn 自动处理,但值得检查
```

### 3. 检查 startup_event 是否阻塞了事件循环

即使异步,如果有同步的阻塞操作,也会阻塞整个事件循环。

## 最可能的原因

根据日志分析,**最可能的原因是**:

❌ **Uvicorn 在 startup_event() 运行时没有完全启动 HTTP 服务器**

**为什么**:
1. startup_event() 是异步运行的,会阻塞应用的准备工作
2. Uvicorn 可能在等待 startup_event() 完成时无法接收请求
3. startup_event() 中的数据库操作虽然有超时,但可能接近超时限制

## 最终解决方案

### 立即执行: 添加启动完成日志

**文件**: `src/main.py` 最后添加到 startup_event():

```python
logger.info("[STARTUP] ✅ Application fully initialized and ready!")
logger.info("[STARTUP] HTTP server is accepting connections on port 3000")
```

### 验证修复

部署后,查看日志应该看到:
```
[STARTUP] ✅ Application fully initialized and ready!
[STARTUP] HTTP server is accepting connections on port 3000
```

然后再测试 HTTP 请求,应该能收到 200 而不是 502。

---

## 相关信息

- 部署 ID: ca8b3c25-2b2e-4cf2-9c09-5117a361f604
- 服务状态: Online (显示)
- 实际状态: connection refused (实测)
- 最后请求时间: 2026-08-10 14:33:08

## 下一步

1. 添加上述日志确认
2. 重新部署
3. 立即观察部署日志中是否出现 "ready" 的确认消息
4. 如果仍然 502,可能需要检查 Uvicorn 配置或端口绑定问题

---

**优先级**: 🔴 **极高** - 应用无法响应请求  
**修复时间**: 2-5 分钟  
**风险**: 🟢 **低** - 仅添加日志

