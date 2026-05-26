#requires -Version 5.0
<#
.SYNOPSIS
    Polls localhost until the Streamlit server responds, then minimizes the
    launcher console window.
#>
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$WindowTitle,
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$ready    = $false

while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
            $ready = $true
            break
        }
    } catch { }
    Start-Sleep -Milliseconds 500
}

if (-not $ready) { exit 1 }

Add-Type -Namespace Native -Name Win32 -MemberDefinition @'
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(System.IntPtr hWnd, int nCmdShow);

    [System.Runtime.InteropServices.DllImport("kernel32.dll")]
    public static extern System.IntPtr GetConsoleWindow();
'@

$SW_SHOWMINNOACTIVE = 7
$minimized = $false

function Try-Minimize([System.IntPtr]$Handle) {
    if ($Handle -eq [System.IntPtr]::Zero) { return $false }
    return [Native.Win32]::ShowWindowAsync($Handle, $SW_SHOWMINNOACTIVE)
}

if (Try-Minimize ([Native.Win32]::GetConsoleWindow())) { $minimized = $true }

if (-not $minimized) {
    Get-Process |
        Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like "*$WindowTitle*" } |
        ForEach-Object {
            if (-not $minimized -and (Try-Minimize $_.MainWindowHandle)) {
                $minimized = $true
            }
        }
}
