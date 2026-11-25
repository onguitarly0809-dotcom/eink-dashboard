' EPD_Dashboard_Refresh hidden launcher (keep ASCII-only: wscript reads ANSI).
' powershell.exe -WindowStyle Hidden still flashes a console window, because the
' window is created visible first and hidden afterwards. WScript.Shell.Run with
' window style 0 (SW_HIDE) passes the hide flag at process creation, so conhost
' creates the console hidden from the very start: no flash at all.
' Third arg True = wait for the refresh to finish, so the task instance
' (MultipleInstancesPolicy=IgnoreNew, ExecutionTimeLimit=PT10M) behaves the same
' as when powershell.exe was launched directly.
' dashboard_control.ps1 is resolved next to this script, so no hardcoded path.
' refresh -Wait 40: if a mail popup or lock-screen restore holds the mutex (they
' only need it for a dozen seconds), wait up to 40s for it instead of dropping
' this refresh cycle. A long carousel render still yields at the deadline.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & fso.BuildPath(here, "dashboard_control.ps1") & """ refresh -Wait 40"
shell.Run cmd, 0, True
