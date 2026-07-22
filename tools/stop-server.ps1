<#
    Stops any apartment server left running from a previous session.

    This lives in its own file rather than inline in เปิดระบบ.bat on purpose: an
    inline `powershell -Command "... $_ ..."` is mangled by whichever shell happens
    to launch it, and the failure is silent. A .ps1 is parsed by PowerShell alone,
    and can be run and tested directly.

    Run manually any time:  powershell -ExecutionPolicy Bypass -File tools\stop-server.ps1
#>

$ErrorActionPreference = 'Stop'

# Regex, not -like '*apartment serve*': the two words are NOT adjacent when a global
# flag sits between them, e.g. `python -m apartment --db other.db serve`. A wildcard
# match silently found nothing and reported success, which is the worst failure a
# cleanup step can have.
$running = @(
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match '-m\s+apartment\b.*\bserve\b' }
)

if ($running.Count -eq 0) {
    Write-Host '   ไม่มีระบบเปิดค้างอยู่'
    exit 0
}

foreach ($proc in $running) {
    try {
        Stop-Process -Id $proc.ProcessId -Force
        Write-Host ('   ปิดระบบเดิมแล้ว (PID ' + $proc.ProcessId + ')')
    } catch {
        Write-Host ('   ปิดไม่สำเร็จ PID ' + $proc.ProcessId + ' - ' + $_.Exception.Message)
    }
}

# Give Windows a moment to release the listening socket before the caller rebinds it.
Start-Sleep -Milliseconds 500
exit 0

