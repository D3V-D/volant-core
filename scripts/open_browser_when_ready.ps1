#requires -Version 5.0
<#
.SYNOPSIS
    Waits until the Streamlit server is listening and serving HTTP, then opens
    the app in the default browser.

    TCP alone is not enough — Streamlit can accept the port before the app is
    ready, which causes a 404 if the browser opens too early.
#>
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$Port = 8501,
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'

# localhost often stalls on IPv6; 127.0.0.1 is reliable on Windows.
$Url = $Url -replace '://localhost([:/])', '://127.0.0.1$1'

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

while ((Get-Date) -lt $deadline) {
    $portOpen = $false
    try {
        $client = New-Object System.Net.Sockets.TcpClient('127.0.0.1', $Port)
        $client.Close()
        $portOpen = $true
    } catch { }

    if ($portOpen) {
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
                Start-Process $Url
                exit 0
            }
        } catch { }
    }

    Start-Sleep -Milliseconds 500
}

exit 1
