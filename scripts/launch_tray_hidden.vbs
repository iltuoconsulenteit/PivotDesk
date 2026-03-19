Dim shell, pythonwExe, trayPy, cmd

Set shell = CreateObject("WScript.Shell")

If WScript.Arguments.Count < 2 Then
    WScript.Quit 1
End If

pythonwExe = WScript.Arguments(0)
trayPy = WScript.Arguments(1)

cmd = """" & pythonwExe & """ """ & trayPy & """"

shell.Run cmd, 0, False