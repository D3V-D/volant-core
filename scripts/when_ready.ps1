#requires -Version 5.0
<#
.SYNOPSIS
    Waits until Streamlit serves HTTP, opens the app in the default browser,
    then minimizes the launcher console.
#>
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$WindowTitle,
    [int]$Port = 8501,
    [int]$TimeoutSeconds = 180,
    [int]$DelayBeforeMinimizeSeconds = 4
)

# localhost often stalls on IPv6; 127.0.0.1 is reliable on Windows.
$Url = $Url -replace '://localhost([:/])', '://127.0.0.1$1'

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'

function Test-ServerReady {
    param([string]$CheckUrl, [int]$CheckPort)
    try {
        $client = New-Object System.Net.Sockets.TcpClient('127.0.0.1', $CheckPort)
        $client.Close()
    } catch {
        return $false
    }

    try {
        $request = [System.Net.HttpWebRequest]::Create($CheckUrl)
        $request.Method         = 'GET'
        $request.Timeout        = 5000
        $request.ReadWriteTimeout = 5000
        $request.UserAgent      = 'VolantLauncher/1.0'
        $response = $request.GetResponse()
        $code = [int]$response.StatusCode
        $response.Close()
        return ($code -ge 200 -and $code -lt 500)
    } catch {
        return $false
    }
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$ready    = $false

while ((Get-Date) -lt $deadline) {
    if (Test-ServerReady -CheckUrl $Url -CheckPort $Port) {
        $ready = $true
        break
    }
    Start-Sleep -Milliseconds 500
}

if (-not $ready) { exit 1 }

Start-Process $Url

if ($DelayBeforeMinimizeSeconds -gt 0) {
    Start-Sleep -Seconds $DelayBeforeMinimizeSeconds
}

Add-Type -Namespace Native -Name Win32 -MemberDefinition @'
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(System.IntPtr hWnd, int nCmdShow);
'@

$SW_SHOWMINNOACTIVE = 7
$minimized = $false

function Try-Minimize([System.IntPtr]$Handle) {
    if ($Handle -eq [System.IntPtr]::Zero) { return $false }
    return [Native.Win32]::ShowWindowAsync($Handle, $SW_SHOWMINNOACTIVE)
}

Get-Process |
    Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like "*$WindowTitle*" } |
    ForEach-Object {
        if (-not $minimized -and (Try-Minimize $_.MainWindowHandle)) {
            $minimized = $true
        }
    }

exit 0
