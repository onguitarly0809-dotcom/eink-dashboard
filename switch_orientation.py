#!/usr/bin/env python3
"""切换墨水屏看板运营方向（横版 landscape / 竖版 portrait）。

用法: python switch_orientation.py [landscape|portrait]
做五件事（全部可逆，两个变体目录本身不动）：
  1. 写 ACTIVE_ORIENTATION.txt 方向标记
  2. 计划任务 EPD_Dashboard_Refresh 改指目标变体的 epd_refresh_hidden.vbs
     （VBS 按自身目录解析控制脚本，轮播/缓存/互斥锁两变体各自独立）
  3. 停掉两变体正在运行的 Web 控制台、热键、邮件监控三个后台进程
     （避免 8080 端口与热键注册冲突；邮件监控只有横版，竖版运营期间它仍在跑的话，
     新邮件/锁屏时会往屏上推横版画面）
  4. 重写登录自启 VBS（EPD_Web_Start.vbs）指向目标变体并立即隐藏拉起
  5. 目标是横版时，经它的登录自启脚本把邮件监控重新拉起
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK_NAME = "EPD_Dashboard_Refresh"
STARTUP_DIR = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
STARTUP_VBS = STARTUP_DIR / "EPD_Web_Start.vbs"
MAIL_MONITOR_VBS = STARTUP_DIR / "EPD_Mail_Monitor_Start.vbs"
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
    # 只匹配本项目自己的 dashboard_web.py / dashboard_hotkeys.py / mail_monitor.py 后台进程
    try:
        out = subprocess.run(
            ["wmic", "process", "where",
             "CommandLine like '%dashboard_web.py%' or CommandLine like '%dashboard_hotkeys.py%'"
             " or CommandLine like '%mail_monitor.py%'",
             "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return
    stopped = False
    for line in out.splitlines():
        line = line.strip()
        if not line or not line[-1].isdigit():
            continue
        pid = int(line.split()[-1])
        if pid == os.getpid():
            continue  # 切换发起进程自身由后续拉起新控制台兜底，这里跳过自杀前的清理
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        stopped = True
        print(f"停止后台进程 {pid}")
    if stopped:
        # taskkill 返回时进程可能还在退出途中：稍等再拉新实例，否则新监控/新控制台会因
        # "已有实例/端口被占"直接退出
        time.sleep(1.5)


def launch_hidden(script):
    """经 wscript 隐藏拉起一个自启脚本（与登录自启同一通道）。"""
    subprocess.Popen(["wscript.exe", str(script)],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NO_WINDOW", 0))


def write_startup_vbs(pythonw, web_py, hot_py):
    """重写登录自启脚本（EPD_Web_Start.vbs）：登录时隐藏拉起目标变体的控制台与热键。"""
    lines = [
        f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{web_py}""", 0, False',
        f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{hot_py}""", 0, False',
    ]
    # 自启脚本由 wscript 按 ANSI 代码页读取，这里就用系统 ANSI 编码写。此前用 ascii +
    # errors="ignore"：路径里一旦出现中文，字符被静默丢掉，写出的是个指向不存在路径的脚本
    STARTUP_VBS.write_text("\r\n".join(lines), encoding="mbcs")


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
    write_startup_vbs(pythonw, variant / "dashboard_web.py", variant / "dashboard_hotkeys.py")
    launch_hidden(STARTUP_VBS)
    if target == "landscape" and MAIL_MONITOR_VBS.exists():
        # 邮件监控只有横版，刚才随其他后台进程一起停掉了：经它的自启脚本重新拉起
        # （目标为竖版时不启动；登录自启脚本误拉起时监控自己读方向标记退出）
        launch_hidden(MAIL_MONITOR_VBS)
        print(f"已重新拉起邮件监控：{MAIL_MONITOR_VBS.name}")
    print(f"已切换到 {target} 运营：自启与后台控制台已指向 {variant}")
    print("Web 控制台 8080 端口稍后自愈，浏览器刷新即可")


if __name__ == "__main__":
    main()
