#!/usr/bin/env python3
"""切换墨水屏看板运营方向（横版 landscape / 竖版 portrait）。

用法: python switch_orientation.py [landscape|portrait]
做四件事（全部可逆，两个变体目录本身不动）：
  1. 写 ACTIVE_ORIENTATION.txt 方向标记
  2. 计划任务 EPD_Dashboard_Refresh 改指目标变体的 epd_refresh_hidden.vbs
     （VBS 按自身目录解析控制脚本，轮播/缓存/互斥锁两变体各自独立）
  3. 停掉两变体正在运行的 Web 控制台与热键后台进程（避免 8080 端口与热键注册冲突）
  4. 重写登录自启 VBS（EPD_Web_Start.vbs）指向目标变体并立即隐藏拉起
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK_NAME = "EPD_Dashboard_Refresh"
STARTUP_VBS = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/EPD_Web_Start.vbs"
PY_PROCESS_NAMES = ("python.exe", "pythonw.exe")


def find_pythonw():
    cands = []
    if os.environ.get("EPD_PYTHON"):
        cands.append(os.environ["EPD_PYTHON"].replace("python.exe", "pythonw.exe"))
    import shutil
    which = shutil.which("pythonw")
    if which:
        cands.append(which)
    for c in cands:
        if Path(c).exists():
            return c
    raise RuntimeError("找不到 pythonw.exe（可设 EPD_PYTHON 指定解释器目录）")


def stop_dashboard_processes():
    # 只匹配本项目自己的 dashboard_web.py / dashboard_hotkeys.py 后台进程
    try:
        out = subprocess.run(
            ["wmic", "process", "where",
             "CommandLine like '%dashboard_web.py%' or CommandLine like '%dashboard_hotkeys.py%'",
             "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return
    for line in out.splitlines():
        line = line.strip()
        if not line or not line[-1].isdigit():
            continue
        pid = int(line.split()[-1])
        if pid == os.getpid():
            continue  # 切换发起进程自身由后续拉起新控制台兜底，这里跳过自杀前的清理
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        print(f"停止后台进程 {pid}")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    if target not in ("landscape", "portrait"):
        print(__doc__)
        sys.exit(2)
    variant = ROOT / ("dashboard_serial_landscape" if target == "landscape" else "dashboard_serial")
    task_vbs = variant / "epd_refresh_hidden.vbs"
    for f in (task_vbs, variant / "dashboard_web.py", variant / "dashboard_hotkeys.py"):
        if not f.exists():
            raise SystemExit(f"缺少文件: {f}")

    (ROOT / "ACTIVE_ORIENTATION.txt").write_text(target, encoding="ascii")

    r = subprocess.run(
        ["schtasks", "/Change", "/TN", TASK_NAME,
         "/TR", f'wscript.exe "{task_vbs}"'],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"计划任务重定向失败: {r.stderr.strip()}")
    print(f"计划任务 {TASK_NAME} -> {task_vbs}")

    stop_dashboard_processes()

    pythonw = find_pythonw()
    web_py = variant / "dashboard_web.py"
    hot_py = variant / "dashboard_hotkeys.py"
    lines = [
        f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{web_py}""", 0, False',
        f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{hot_py}""", 0, False',
    ]
    STARTUP_VBS.write_text("\r\n".join(lines), encoding="ascii", errors="ignore")
    subprocess.Popen(["wscript.exe", str(STARTUP_VBS)],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print(f"已切换到 {target} 运营：自启与后台控制台已指向 {variant}")
    print("Web 控制台 8080 端口稍后自愈，浏览器刷新即可")


if __name__ == "__main__":
    main()
