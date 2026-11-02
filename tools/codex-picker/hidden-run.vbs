' hidden-run.vbs - start a program without opening a console window.
'
' wscript hidden-run.vbs <program> <args...>
'
' pwsh.exe is a console application. When Task Scheduler starts it directly,
' Windows creates a console window before -WindowStyle Hidden takes effect.
' wscript.exe is a GUI host and can start the target with window style 0, so
' scheduled watchdog checks do not flash a console every five minutes.
'
' Every argument is quoted for CreateProcess; the first argument is the
' executable. This wrapper is intended for pwsh -File calls. It is not suitable
' for cmd.exe /c with quoted redirection because cmd has special /c quoting.
Option Explicit
Dim shell, cmdline, sep, i
Set shell = CreateObject("WScript.Shell")
cmdline = ""
sep = ""
For i = 0 To WScript.Arguments.Count - 1
    cmdline = cmdline & sep & """" & WScript.Arguments(i) & """"
    sep = " "
Next
shell.Run cmdline, 0, False
