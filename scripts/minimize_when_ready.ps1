#requires -Version 5.0
<#
.SYNOPSIS
    Polls localhost until the Streamlit server responds, then minimizes the
    launcher console window.
#>
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$WindowTitle,
    [int]$TimeoutSeconds = 120,
    [int]$DelayAfterReadySeconds = 3
)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'

# localhost often stalls on IPv6; 127.0.0.1 is reliable on Windows.
$Url = $Url -replace '://localhost([:/])', '://127.0.0.1$1'

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$ready    = $false

while ((Get-Date) -lt $deadline) {
    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Method = 'GET'
        $request.Timeout = 5000
        $request.ReadWriteTimeout = 5000
        $request.UserAgent = 'VolantLauncher/1.0'
        $response = $request.GetResponse()
        $code = [int]$response.StatusCode
        $response.Close()
        if ($code -ge 200 -and $code -lt 500) {
            $ready = $true
            break
        }
    } catch { }
    Start-Sleep -Milliseconds 500
}

if (-not $ready) { exit 1 }

if ($DelayAfterReadySeconds -gt 0) {
    Start-Sleep -Seconds $DelayAfterReadySeconds
}

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
