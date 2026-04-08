@echo off
setlocal EnableDelayedExpansion

:: ============================================================
:: CPA-Codex-Manager Windows 构建脚本
:: ✅ 兼容 GitHub Actions 与本地开发环境
:: ✅ 自动适配 CI 传入的 PYTHON_CMD / PIP_CMD
:: ============================================================

:: 1. 设置命令（优先使用 CI 环境变量，否则 fallback 到系统默认）
if "%PYTHON_CMD%"=="" set "PYTHON_CMD=python"
if "%PIP_CMD%"=="" set "PIP_CMD=%PYTHON_CMD% -m pip"

echo [1/5] 清理旧产物...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
if exist "*.spec" del /q "*.spec" 2>nul

echo [2/5] 检查依赖...
:: ✅ 关键修复：使用环境变量指定的 Python 命令检测
%PYTHON_CMD% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo ⚠️ 未检测到 PyInstaller，正在通过 %PIP_CMD% 安装...
    %PIP_CMD% install --upgrade pip >nul 2>&1
    %PIP_CMD% install "pyinstaller==6.11.1" pillow
    if errorlevel 1 (
        echo ❌ PyInstaller 安装失败，请检查网络或 pip 配置
        exit /b 1
    )
)
echo ✅ PyInstaller 已就绪

echo [3/5] 获取版本信息...
set "BUILD_VERSION=%APP_VERSION%"
if "%BUILD_VERSION%"=="" set "BUILD_VERSION=1.0.0-dev"
:: 移除可能的 'v' 前缀
if /i "%BUILD_VERSION:~0,1%"=="v" set "BUILD_VERSION=%BUILD_VERSION:~1%"
echo 📦 构建版本: !BUILD_VERSION!

echo [4/5] 开始 PyInstaller 构建...
set "BUILD_MODE=%~1"
if "%BUILD_MODE%"=="" set "BUILD_MODE=onedir"

:: 拼接 PyInstaller 参数（Windows 路径分隔符为 ;）
set "PYI_ARGS=--name=CPA-Codex-Manager"
set "PYI_ARGS=!PYI_ARGS! --add-data config;config"
set "PYI_ARGS=!PYI_ARGS! --hidden-import=pkg_resources.py2_warn"
set "PYI_ARGS=!PYI_ARGS! --hidden-import=charset_normalizer.md__mypyc"
if /i "%BUILD_MODE%"=="onefile" (
    set "PYI_ARGS=!PYI_ARGS! --onefile --icon=assets/icon.ico"
) else (
    set "PYI_ARGS=!PYI_ARGS! --onedir --windowed --icon=assets/icon.ico"
)

:: 执行构建
echo 🔨 执行命令: %PYTHON_CMD% -m PyInstaller !PYI_ARGS! webui.py
%PYTHON_CMD% -m PyInstaller !PYI_ARGS! webui.py
if errorlevel 1 (
    echo ❌ PyInstaller 构建失败，请检查上方日志
    exit /b 1
)

echo [5/5] 验证产物...
if /i "%BUILD_MODE%"=="onefile" (
    if not exist "dist\CPA-Codex-Manager.exe" (
        echo ❌ 未找到预期文件: dist\CPA-Codex-Manager.exe
        exit /b 1
    )
    echo ✅ 构建成功: dist\CPA-Codex-Manager.exe
) else (
    if not exist "dist\CPA-Codex-Manager\CPA-Codex-Manager.exe" (
        echo ❌ 未找到预期文件: dist\CPA-Codex-Manager\CPA-Codex-Manager.exe
        exit /b 1
    )
    echo ✅ 构建成功: dist\CPA-Codex-Manager\
)

echo 🎉 全部完成！
exit /b 0
