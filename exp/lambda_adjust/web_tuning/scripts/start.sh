#!/bin/bash

# ============================================
# PID整定系统 - 完整启动脚本（前端+后端+AI）
# ============================================

set -e

echo "🚀 启动PID整定系统（完整版 + AI）"
echo "=================================="

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# 获取脚本所在目录和项目根目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# 日志文件
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
OLLAMA_LOG="$LOG_DIR/ollama.log"

# PID变量
OLLAMA_PID=""
BACKEND_PID=""
FRONTEND_PID=""

# 清理函数
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 正在停止所有服务...${NC}"
    
    # 停止后端
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
        echo -e "${GREEN}✅ 后端服务已停止${NC}"
    fi
    
    # 停止前端
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
        echo -e "${GREEN}✅ 前端服务已停止${NC}"
    fi
    
    # 停止Ollama（可选，因为Ollama通常保持运行）
    # if [ ! -z "$OLLAMA_PID" ]; then
    #     kill $OLLAMA_PID 2>/dev/null || true
    #     echo -e "${GREEN}✅ Ollama服务已停止${NC}"
    # fi
    
    # 清理端口
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    lsof -ti:8080 | xargs kill -9 2>/dev/null || true
    
    echo -e "${GREEN}👋 服务已全部停止${NC}"
    echo -e "${BLUE}💡 提示: Ollama服务仍在后台运行（这是正常的）${NC}"
    exit 0
}

# 捕获退出信号
trap cleanup SIGINT SIGTERM

# ============================================
# 1. 检查并启动Ollama服务
# ============================================
echo ""
echo -e "${PURPLE}🤖 步骤1: 检查Ollama AI服务...${NC}"

if ! command -v ollama &> /dev/null; then
    echo -e "${YELLOW}⚠️  Ollama未安装${NC}"
    echo ""
    echo "安装方法："
    echo "  macOS:   brew install ollama"
    echo "  Linux:   curl -fsSL https://ollama.com/install.sh | sh"
    echo "  或访问:  https://ollama.com"
    echo ""
    read -p "是否跳过AI功能继续启动？(y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
    SKIP_AI=true
else
    SKIP_AI=false
    
    # 检查Ollama是否运行
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Ollama服务未运行，正在启动...${NC}"
        
        # 在后台启动Ollama
        nohup ollama serve > "$OLLAMA_LOG" 2>&1 &
        OLLAMA_PID=$!
        
        # 等待Ollama启动
        echo "等待Ollama服务启动..."
        for i in {1..15}; do
            if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
                echo -e "${GREEN}✅ Ollama服务已启动 (PID: $OLLAMA_PID)${NC}"
                break
            fi
            sleep 1
            echo -n "."
        done
        
        if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo -e "${RED}❌ Ollama启动失败${NC}"
            echo "查看日志: $OLLAMA_LOG"
            exit 1
        fi
    else
        echo -e "${GREEN}✅ Ollama服务已运行${NC}"
    fi
    
    # 检查模型
    echo ""
    echo -e "${PURPLE}🤖 检查AI模型...${NC}"
    
    # 读取配置的模型
    if [ -f ".env" ]; then
        MODEL=$(grep "^AI_MODEL=" .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
        if [ -z "$MODEL" ]; then
            MODEL="qwen:7b"
        fi
    else
        MODEL="qwen:7b"
    fi
    
    echo "配置的模型: $MODEL"
    
    # 检查模型是否存在
    if ollama list | grep -q "$MODEL"; then
        echo -e "${GREEN}✅ 模型 $MODEL 已安装${NC}"
    else
        echo -e "${YELLOW}⚠️  模型 $MODEL 未安装${NC}"
        echo ""
        read -p "是否现在下载模型？这可能需要几分钟 (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "正在下载模型..."
            ollama pull "$MODEL"
            echo -e "${GREEN}✅ 模型下载完成${NC}"
        else
            echo -e "${YELLOW}⚠️  跳过模型下载，AI功能可能无法使用${NC}"
        fi
    fi
    
    # 配置环境变量
    echo ""
    echo -e "${PURPLE}⚙️  配置AI环境...${NC}"
    
    if [ ! -f ".env" ]; then
        echo "创建.env配置文件..."
        cat > .env << EOF
# AI配置
OPENAI_API_KEY=ollama
OPENAI_API_BASE=http://localhost:11434/v1
AI_MODEL=$MODEL

# 其他配置
DEBUG=false
EOF
        echo -e "${GREEN}✅ .env文件已创建${NC}"
    else
        echo -e "${GREEN}✅ .env文件已存在${NC}"
    fi
fi

# ============================================
# 2. 检查并清理端口
# ============================================
echo ""
echo -e "${BLUE}📦 步骤2: 检查端口...${NC}"

# 检查后端端口
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  端口 8000 已被占用，正在清理...${NC}"
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# 检查前端端口
if lsof -Pi :8080 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  端口 8080 已被占用，正在清理...${NC}"
    lsof -ti:8080 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

echo -e "${GREEN}✅ 端口检查完成${NC}"

# ============================================
# 3. 启动后端服务
# ============================================
echo ""
echo -e "${BLUE}🔧 步骤3: 启动后端服务...${NC}"

cd "$PROJECT_ROOT/backend"

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 错误: Python3未安装${NC}"
    exit 1
fi

# 检查依赖
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}❌ 错误: requirements.txt不存在${NC}"
    exit 1
fi

# 安装依赖（如果需要）
echo "检查Python依赖..."
pip3 install -q -r requirements.txt 2>&1 | tee -a "$BACKEND_LOG" || true

# 启动后端（后台运行）
echo "启动后端服务..."
python3 app.py > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# 等待后端启动
echo "等待后端服务启动..."
for i in {1..15}; do
    if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 后端服务已启动 (PID: $BACKEND_PID)${NC}"
        break
    fi
    sleep 1
    echo -n "."
done

if ! curl -s http://localhost:8000/docs > /dev/null 2>&1; then
    echo -e "${RED}❌ 后端启动失败，查看日志: $BACKEND_LOG${NC}"
    tail -20 "$BACKEND_LOG"
    exit 1
fi

# ============================================
# 4. 启动前端服务
# ============================================
echo ""
echo -e "${BLUE}🌐 步骤4: 启动前端服务...${NC}"

cd "$PROJECT_ROOT"

# 启动前端（后台运行）
echo "启动前端服务..."
python3 -m http.server 8080 > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

# 等待前端启动
sleep 2

if lsof -Pi :8080 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${GREEN}✅ 前端服务已启动 (PID: $FRONTEND_PID)${NC}"
else
    echo -e "${RED}❌ 前端启动失败${NC}"
    exit 1
fi

# ============================================
# 5. 显示访问信息
# ============================================
echo ""
echo "=================================="
echo -e "${GREEN}🎉 系统启动成功！${NC}"
echo "=================================="
echo ""
echo -e "${BLUE}📍 访问地址：${NC}"
echo "   🌐 前端界面: http://localhost:8080/frontend/index.html"
echo "   🔧 后端API:  http://localhost:8000"
echo "   📚 API文档:  http://localhost:8000/docs"
if [ "$SKIP_AI" = false ]; then
    echo "   🤖 AI服务:   http://localhost:11434"
fi
echo ""
echo -e "${BLUE}📊 服务状态：${NC}"
if [ "$SKIP_AI" = false ]; then
    echo "   ✅ AI服务:   运行中 (Ollama)"
    echo "   ✅ AI模型:   $MODEL"
fi
echo "   ✅ 后端服务: 运行中 (PID: $BACKEND_PID)"
echo "   ✅ 前端服务: 运行中 (PID: $FRONTEND_PID)"
echo ""
echo -e "${BLUE}📝 日志文件：${NC}"
if [ "$SKIP_AI" = false ]; then
    echo "   📄 AI日志:   $OLLAMA_LOG"
fi
echo "   📄 后端日志: $BACKEND_LOG"
echo "   📄 前端日志: $FRONTEND_LOG"
echo ""
echo -e "${BLUE}💡 功能说明：${NC}"
echo "   ✅ 参数整定 - 上传数据自动整定PID参数"
echo "   ✅ 多回路管理 - 管理多个控制回路"
if [ "$SKIP_AI" = false ]; then
    echo "   ✅ AI智能助手 - 参数优化建议和问题诊断"
else
    echo "   ⚠️  AI智能助手 - 未启用（Ollama未安装）"
fi
echo "   ✅ 报告生成 - 导出JSON/Markdown格式报告"
echo ""
echo -e "${BLUE}🎯 快速开始：${NC}"
echo "   1. 在浏览器打开: http://localhost:8080/frontend/index.html"
echo "   2. 点击'📁 上传数据'上传CSV文件"
echo "   3. 点击'🚀 开始整定'进行参数整定"
if [ "$SKIP_AI" = false ]; then
    echo "   4. 使用'🤖 AI助手'获取优化建议"
fi
echo ""
echo -e "${YELLOW}⚠️  按 Ctrl+C 停止所有服务${NC}"
echo ""
echo "=================================="
echo ""

# 实时显示后端日志
echo -e "${YELLOW}📊 实时后端日志（按 Ctrl+C 停止）：${NC}"
echo ""

# 跟踪后端日志
tail -f "$BACKEND_LOG"

# 保持脚本运行
wait
