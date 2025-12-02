#!/usr/bin/env python3
"""
PyInstaller 打包脚本
将 web_tuning 打包成独立可执行文件
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"

def clean_build():
    """清理之前的构建"""
    print("🧹 清理之前的构建...")
    for dir_path in [DIST_DIR, BUILD_DIR]:
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"   删除: {dir_path}")

def install_pyinstaller():
    """安装 PyInstaller"""
    print("📦 检查 PyInstaller...")
    try:
        import PyInstaller
        print(f"   已安装: PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("   安装 PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

def create_spec_file():
    """创建 PyInstaller spec 文件"""
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['{BACKEND_DIR / "app.py"}'],
    pathex=['{BACKEND_DIR}'],
    binaries=[],
    datas=[
        ('{FRONTEND_DIR}', 'frontend'),
        ('{ROOT_DIR / "data"}', 'data'),
        ('{ROOT_DIR / ".env.example"}', '.'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'asyncua',
        'matplotlib',
        'scipy',
        'pandas',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='pid-tuning-system',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='pid-tuning-system',
)
"""
    
    spec_file = ROOT_DIR / "pid-tuning-system.spec"
    with open(spec_file, 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print(f"✅ 创建 spec 文件: {spec_file}")
    return spec_file

def build_executable(spec_file):
    """使用 PyInstaller 构建可执行文件"""
    print("🔨 开始构建可执行文件...")
    cmd = [
        "pyinstaller",
        "--clean",
        "--noconfirm",
        str(spec_file)
    ]
    
    subprocess.check_call(cmd, cwd=ROOT_DIR)
    print("✅ 构建完成!")

def create_readme():
    """创建使用说明"""
    readme_content = """# PID 参数整定系统 - 独立版本

## 🚀 快速开始

### Windows
双击运行 `pid-tuning-system.exe`

### macOS/Linux
```bash
chmod +x pid-tuning-system
./pid-tuning-system
```

## 📝 访问系统

启动后，在浏览器中访问：
- 前端界面: http://localhost:8080/frontend/index.html
- 后端 API: http://localhost:8000
- API 文档: http://localhost:8000/docs

## 📂 目录结构

```
pid-tuning-system/
├── pid-tuning-system(.exe)  # 主程序
├── frontend/                 # 前端文件
├── data/                     # 数据文件
├── logs/                     # 日志文件
└── .env                      # 配置文件
```

## ⚙️ 配置

编辑 `.env` 文件修改配置：
- AI 模型设置
- 端口配置
- OPC UA 连接等

## 📞 支持

如有问题，请查看 logs/ 目录下的日志文件。
"""
    
    readme_file = DIST_DIR / "pid-tuning-system" / "README.txt"
    with open(readme_file, 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    print(f"✅ 创建使用说明: {readme_file}")

def main():
    """主函数"""
    print("=" * 60)
    print("🎛️  PID 参数整定系统 - PyInstaller 打包工具")
    print("=" * 60)
    
    try:
        # 1. 清理构建
        clean_build()
        
        # 2. 安装 PyInstaller
        install_pyinstaller()
        
        # 3. 创建 spec 文件
        spec_file = create_spec_file()
        
        # 4. 构建可执行文件
        build_executable(spec_file)
        
        # 5. 创建使用说明
        create_readme()
        
        print("\n" + "=" * 60)
        print("✅ 打包完成!")
        print("=" * 60)
        print(f"📦 输出目录: {DIST_DIR / 'pid-tuning-system'}")
        print("\n使用方法:")
        print("  1. 进入 dist/pid-tuning-system/ 目录")
        print("  2. 运行 pid-tuning-system 可执行文件")
        print("  3. 在浏览器访问 http://localhost:8080/frontend/index.html")
        
    except Exception as e:
        print(f"\n❌ 打包失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
