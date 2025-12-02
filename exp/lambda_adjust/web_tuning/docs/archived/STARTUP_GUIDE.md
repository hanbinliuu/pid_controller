# 🚀 启动指南

## 快速启动

### 一键启动（推荐）

```bash
./start.sh
```

就这么简单！脚本会自动完成所有配置和启动。

---

## 📋 启动流程

脚本会自动执行以下步骤：

### 1. 🤖 检查和启动AI服务
- 检查Ollama是否安装
- 如果未运行，自动启动Ollama服务
- 检查AI模型是否存在（qwen2.5:7b）
- 如果不存在，询问是否下载

### 2. 🔧 启动后端服务
- 检查Python依赖
- 自动安装缺失的包
- 启动FastAPI服务（端口8000）

### 3. 🌐 启动前端服务
- 启动HTTP服务器（端口8080）
- 提供静态文件访问

### 4. ✅ 完成
- 显示访问地址
- 实时显示后端日志
- 按Ctrl+C停止所有服务

---

## 🌐 访问地址

启动成功后，访问：

- **前端界面**: http://localhost:8080/pid_tuning_interface_v2.html
- **后端API**: http://localhost:8000
- **API文档**: http://localhost:8000/docs
- **AI服务**: http://localhost:11434

---

## 💡 使用提示

### 首次使用

1. **确保已安装Ollama**（可选，用于AI功能）
   ```bash
   brew install ollama
   ```

2. **运行启动脚本**
   ```bash
   ./start.sh
   ```

3. **等待服务启动**
   - 如果是首次运行，可能需要下载AI模型（几分钟）
   - 脚本会显示进度

4. **打开浏览器**
   - 访问前端地址
   - 开始使用系统

### 停止服务

按 `Ctrl+C` 即可停止所有服务。

脚本会自动清理：
- 停止后端服务
- 停止前端服务
- 清理端口占用

---

## 🔧 手动启动（可选）

如果你想分别控制各个服务：

### 启动后端
```bash
cd backend
python app.py
```

### 启动前端（另开终端）
```bash
python -m http.server 8080
```

### 启动Ollama（如需AI功能）
```bash
ollama serve
```

---

## 🐛 常见问题

### Q1: 端口被占用怎么办？

**A**: 脚本会自动清理端口，如果还有问题：

```bash
# 手动清理
lsof -ti:8000 | xargs kill -9  # 后端
lsof -ti:8080 | xargs kill -9  # 前端
lsof -ti:11434 | xargs kill -9 # Ollama
```

### Q2: Ollama未安装怎么办？

**A**: 脚本会提示安装方法，你可以：

1. **安装Ollama**（推荐，获得AI功能）
   ```bash
   brew install ollama
   ```

2. **跳过AI功能**
   - 脚本会询问是否跳过
   - 选择 `y` 继续启动（不含AI）

### Q3: 启动失败怎么办？

**A**: 查看日志文件：

```bash
# 查看后端日志
tail -f backend.log

# 查看前端日志
tail -f frontend.log

# 查看Ollama日志
tail -f ollama.log
```

### Q4: AI模型下载很慢？

**A**: 

1. **使用国内镜像**（如果可用）
2. **或者跳过AI功能**
   - 系统其他功能不受影响
   - 只是AI助手无法使用

### Q5: 如何更换AI模型？

**A**: 编辑 `.env` 文件：

```bash
# .env
AI_MODEL=qwen2.5:7b  # 改成你想要的模型
```

然后重启服务。

---

## 📊 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端 | 8080 | HTTP静态文件服务 |
| 后端 | 8000 | FastAPI服务 |
| Ollama | 11434 | AI模型服务 |

---

## 🎯 快速开始示例

```bash
# 1. 进入项目目录
cd /path/to/web_tuning

# 2. 一键启动
./start.sh

# 3. 等待启动完成（看到"系统启动成功"）

# 4. 打开浏览器
# http://localhost:8080/pid_tuning_interface_v2.html

# 5. 开始使用
# - 上传CSV数据
# - 点击"开始整定"
# - 使用AI助手获取优化建议

# 6. 停止服务
# 按 Ctrl+C
```

---

## 📖 更多文档

- [README.md](README.md) - 项目简介和完整结构
- [AI_OPTIMIZATION_GUIDE.md](AI_OPTIMIZATION_GUIDE.md) - AI优化使用指南
- [OLLAMA_SETUP.md](OLLAMA_SETUP.md) - Ollama安装配置

---

**就这么简单！** 🎉

一条命令启动所有服务：
```bash
./start.sh
```
