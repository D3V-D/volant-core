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
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                Start-Process $Url
                exit 0
            }
        } catch { }
    }

    Start-Sleep -Milliseconds 500
}

exit 1
