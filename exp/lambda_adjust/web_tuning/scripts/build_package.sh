#!/bin/bash
# 压缩包打包脚本
# 创建可分发的 tar.gz 或 zip 包

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$ROOT_DIR/dist"
PACKAGE_NAME="pid-tuning-system"
VERSION=$(date +%Y%m%d_%H%M%S)
PACKAGE_DIR="$DIST_DIR/${PACKAGE_NAME}_${VERSION}"

echo -e "${GREEN}=====================================================${NC}"
echo -e "${GREEN}🎛️  PID 参数整定系统 - 压缩包打包工具${NC}"
echo -e "${GREEN}=====================================================${NC}"

# 清理旧的构建
echo -e "\n${YELLOW}🧹 清理旧的构建...${NC}"
rm -rf "$DIST_DIR"
mkdir -p "$PACKAGE_DIR"

# 复制必要文件
echo -e "\n${YELLOW}📦 复制项目文件...${NC}"

# 复制核心目录
for dir in backend frontend servers scripts data docs; do
    if [ -d "$ROOT_DIR/$dir" ]; then
        echo "   复制: $dir/"
        cp -r "$ROOT_DIR/$dir" "$PACKAGE_DIR/"
    fi
done

# 复制配置文件
echo "   复制配置文件..."
cp "$ROOT_DIR/.env.example" "$PACKAGE_DIR/.env"
cp "$ROOT_DIR/.gitignore" "$PACKAGE_DIR/" 2>/dev/null || true
cp "$ROOT_DIR/README.md" "$PACKAGE_DIR/" 2>/dev/null || true

# 创建必要的目录
echo -e "\n${YELLOW}📁 创建必要目录...${NC}"
mkdir -p "$PACKAGE_DIR/logs"
mkdir -p "$PACKAGE_DIR/data"

# 清理不必要的文件
echo -e "\n${YELLOW}🧹 清理不必要文件...${NC}"
find "$PACKAGE_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PACKAGE_DIR" -type d -name "venv" -exec rm -rf {} + 2>/dev/null || true
find "$PACKAGE_DIR" -type d -name ".git" -exec rm -rf {} + 2>/dev/null || true
find "$PACKAGE_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
find "$PACKAGE_DIR" -type f -name "*.pyo" -delete 2>/dev/null || true
find "$PACKAGE_DIR" -type f -name ".DS_Store" -delete 2>/dev/null || true

# 创建安装脚本
echo -e "\n${YELLOW}📝 创建安装脚本...${NC}"

# Linux/macOS 安装脚本
cat > "$PACKAGE_DIR/install.sh" << 'EOF'
#!/bin/bash
# PID 参数整定系统 - 安装脚本

set -e

echo "======================================================"
echo "🎛️  PID 参数整定系统 - 安装向导"
echo "======================================================"

# 检查 Python
echo -e "\n检查 Python 环境..."
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 Python 3，请先安装 Python 3.8+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "✅ Python 版本: $PYTHON_VERSION"

# 创建虚拟环境
echo -e "\n创建虚拟环境..."
python3 -m venv venv
source venv/bin/activate

# 安装依赖
echo -e "\n安装 Python 依赖..."
if [ -f "backend/requirements.txt" ]; then
    pip install -r backend/requirements.txt
else
    echo "⚠️  未找到 requirements.txt，跳过依赖安装"
fi

# 设置权限
echo -e "\n设置执行权限..."
chmod +x scripts/*.sh 2>/dev/null || true
chmod +x backend/*.sh 2>/dev/null || true

echo -e "\n======================================================"
echo "✅ 安装完成!"
echo "======================================================"
echo "启动方法:"
echo "  ./start.sh"
echo ""
echo "或手动启动:"
echo "  source venv/bin/activate"
echo "  cd backend && python app.py"
echo "======================================================"
EOF

chmod +x "$PACKAGE_DIR/install.sh"

# Windows 安装脚本
cat > "$PACKAGE_DIR/install.bat" << 'EOF'
@echo off
REM PID 参数整定系统 - Windows 安装脚本

echo ======================================================
echo 🎛️  PID 参数整定系统 - 安装向导
echo ======================================================

REM 检查 Python
echo.
echo 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo ✅ Python 版本: %PYTHON_VERSION%

REM 创建虚拟环境
echo.
echo 创建虚拟环境...
python -m venv venv
call venv\Scripts\activate.bat

REM 安装依赖
echo.
echo 安装 Python 依赖...
if exist backend\requirements.txt (
    pip install -r backend\requirements.txt
) else (
    echo ⚠️  未找到 requirements.txt，跳过依赖安装
)

echo.
echo ======================================================
echo ✅ 安装完成!
echo ======================================================
echo 启动方法:
echo   start.bat
echo.
echo 或手动启动:
echo   venv\Scripts\activate.bat
echo   cd backend ^&^& python app.py
echo ======================================================
pause
EOF

# 创建启动脚本
cat > "$PACKAGE_DIR/start.sh" << 'EOF'
#!/bin/bash
# PID 参数整定系统 - 启动脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 激活虚拟环境
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 启动后端
echo "🚀 启动后端服务..."
cd backend
python app.py &
BACKEND_PID=$!

# 等待后端启动
sleep 3

# 启动前端
echo "🌐 启动前端服务..."
cd ..
python -m http.server 8080 &
FRONTEND_PID=$!

echo ""
echo "======================================================"
echo "✅ 系统已启动!"
echo "======================================================"
echo "访问地址: http://localhost:8080/frontend/index.html"
echo "API 文档: http://localhost:8000/docs"
echo ""
echo "按 Ctrl+C 停止服务"
echo "======================================================"

# 等待中断信号
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

wait
EOF

chmod +x "$PACKAGE_DIR/start.sh"

# Windows 启动脚本
cat > "$PACKAGE_DIR/start.bat" << 'EOF'
@echo off
REM PID 参数整定系统 - Windows 启动脚本

cd /d %~dp0

REM 激活虚拟环境
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

REM 启动后端
echo 🚀 启动后端服务...
start /b python backend\app.py

REM 等待后端启动
timeout /t 3 /nobreak >nul

REM 启动前端
echo 🌐 启动前端服务...
start /b python -m http.server 8080

echo.
echo ======================================================
echo ✅ 系统已启动!
echo ======================================================
echo 访问地址: http://localhost:8080/frontend/index.html
echo API 文档: http://localhost:8000/docs
echo.
echo 按任意键停止服务...
echo ======================================================
pause >nul

REM 停止服务
taskkill /f /im python.exe >nul 2>&1
EOF

# 创建 README
cat > "$PACKAGE_DIR/INSTALL_README.md" << 'EOF'
# PID 参数整定系统 - 安装说明

## 📦 系统要求

- Python 3.8 或更高版本
- 2GB 可用内存
- 500MB 磁盘空间

## 🚀 快速安装

### Linux / macOS

```bash
# 1. 解压文件
tar -xzf pid-tuning-system_*.tar.gz
cd pid-tuning-system_*

# 2. 运行安装脚本
./install.sh

# 3. 启动系统
./start.sh
```

### Windows

```batch
# 1. 解压文件
# 右键解压 pid-tuning-system_*.zip

# 2. 运行安装脚本
install.bat

# 3. 启动系统
start.bat
```

## 🌐 访问系统

启动后，在浏览器中访问：
- **前端界面**: http://localhost:8080/frontend/index.html
- **后端 API**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs

## ⚙️ 配置

编辑 `.env` 文件修改配置：
- AI 模型设置
- 端口配置
- OPC UA 连接等

## 📞 技术支持

如有问题，请查看：
- `logs/` 目录下的日志文件
- `docs/` 目录下的详细文档
- README.md 使用指南

## 📄 许可证

MIT License
EOF

# 创建压缩包
echo -e "\n${YELLOW}📦 创建压缩包...${NC}"

cd "$DIST_DIR"

# 创建 tar.gz (Linux/macOS)
echo "   创建 tar.gz 包..."
tar -czf "${PACKAGE_NAME}_${VERSION}.tar.gz" "$(basename "$PACKAGE_DIR")"

# 创建 zip (Windows)
if command -v zip &> /dev/null; then
    echo "   创建 zip 包..."
    zip -r -q "${PACKAGE_NAME}_${VERSION}.zip" "$(basename "$PACKAGE_DIR")"
fi

# 计算文件大小
TAR_SIZE=$(du -h "${PACKAGE_NAME}_${VERSION}.tar.gz" | cut -f1)
if [ -f "${PACKAGE_NAME}_${VERSION}.zip" ]; then
    ZIP_SIZE=$(du -h "${PACKAGE_NAME}_${VERSION}.zip" | cut -f1)
fi

# 完成
echo -e "\n${GREEN}=====================================================${NC}"
echo -e "${GREEN}✅ 打包完成!${NC}"
echo -e "${GREEN}=====================================================${NC}"
echo -e "📦 输出目录: $DIST_DIR"
echo -e ""
echo -e "生成的文件:"
echo -e "  📁 ${PACKAGE_NAME}_${VERSION}/           (源文件)"
echo -e "  📦 ${PACKAGE_NAME}_${VERSION}.tar.gz     ($TAR_SIZE)"
if [ -f "${PACKAGE_NAME}_${VERSION}.zip" ]; then
    echo -e "  📦 ${PACKAGE_NAME}_${VERSION}.zip        ($ZIP_SIZE)"
fi
echo -e ""
echo -e "分发方法:"
echo -e "  Linux/macOS: 分发 .tar.gz 文件"
echo -e "  Windows:     分发 .zip 文件"
echo -e "${GREEN}=====================================================${NC}"
