#!/usr/bin/env python3
"""
PID 智能整定系统 - 桌面版启动脚本
自动启动后端服务并打开浏览器
"""
import sys
import os
import webbrowser
import time
import threading
import socket
from pathlib import Path

# 添加后端路径
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))

def is_port_in_use(port):
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def wait_for_server(url, timeout=60):
    """等待服务器启动"""
    import urllib.request
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except:
            time.sleep(0.5)
    return False

def open_browser(url):
    """等待服务器启动后打开浏览器"""
    print("⏳ 等待服务器启动...")
    # 检查 API 根路径是否可访问
    api_url = url.rsplit('/', 1)[0] if '/' in url else url
    if wait_for_server(api_url):
        print(f"✅ 服务器已启动，打开浏览器: {url}")
        webbrowser.open(url)
    else:
        print("❌ 服务器启动超时")

def main():
    """主函数"""
    # 配置
    HOST = "127.0.0.1"
    PORT = 8000
    URL = f"http://{HOST}:{PORT}/pid_tuning_interface_v2.html"  # 🔧 打开前端页面
    
    # 检查端口
    if is_port_in_use(PORT):
        print(f"⚠️  端口 {PORT} 已被占用")
        print(f"🌐 直接打开浏览器: {URL}")
        webbrowser.open(URL)
        return
    
    # 启动浏览器（延迟）
    browser_thread = threading.Thread(target=open_browser, args=(URL,))
    browser_thread.daemon = True
    browser_thread.start()
    
    # 启动 FastAPI 服务器
    print("=" * 60)
    print("🚀 PID 智能整定系统 - 桌面版")
    print("=" * 60)
    print(f"📡 服务器地址: {URL}")
    print(f"💡 提示: 关闭此窗口将停止服务")
    print("=" * 60)
    print()
    
    # 导入并运行 FastAPI 应用
    import uvicorn
    from backend.app import app
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    import os
    
    # 🔧 配置静态文件服务（用于打包后的应用）
    # 获取应用的根目录
    if getattr(sys, 'frozen', False):
        # 打包后的应用
        app_root = sys._MEIPASS
    else:
        # 开发环境
        app_root = Path(__file__).parent
    
    # 添加静态文件路由
    @app.get("/pid_tuning_interface_v2.html")
    async def serve_html():
        html_path = os.path.join(app_root, "pid_tuning_interface_v2.html")
        return FileResponse(html_path)
    
    @app.get("/{file_path:path}")
    async def serve_static(file_path: str):
        """提供静态文件"""
        # 只处理特定的静态文件
        if file_path.endswith(('.js', '.css', '.svg', '.json', '.html')):
            full_path = os.path.join(app_root, file_path)
            if os.path.exists(full_path):
                return FileResponse(full_path)
        # 其他请求返回 404（让 API 路由处理）
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")
    
    # 配置 uvicorn
    config = uvicorn.Config(
        app=app,
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=False  # 减少日志输出
    )
    
    server = uvicorn.Server(config)
    
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n👋 正在关闭服务器...")
    except Exception as e:
        print(f"❌ 服务器错误: {e}")
        import traceback
        traceback.print_exc()
        input("\n按回车键退出...")

if __name__ == "__main__":
    main()
