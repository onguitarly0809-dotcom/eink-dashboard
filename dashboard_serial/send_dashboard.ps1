param(
    [string]$PortName = $env:EPD_SERIAL_PORT,
    [int]$BaudRate = 115200,
    [string]$BinaryPath = "$PSScriptRoot\dashboard.bin",
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ([string]::IsNullOrWhiteSpace($PortName)) {
    throw "Serial port is required. Set EPD_SERIAL_PORT or pass -PortName."
}

if (-not (Test-Path -LiteralPath $BinaryPath)) {
    throw "Binary not found: $BinaryPath"
}

$bytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $BinaryPath))
if ($bytes.Length -ne 48000) {
    throw "Invalid binary size: expected 48000, got $($bytes.Length)"
}

$port = New-Object System.IO.Ports.SerialPort $PortName, $BaudRate, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$port.NewLine = "`n"
$port.ReadTimeout = 2000
$port.WriteTimeout = 5000
$port.DtrEnable = $false
$port.RtsEnable = $false

function Read-Response {
    param([string]$Expected)
    $response = $port.ReadLine().Trim()
    while ($response.Length -eq 0) {
        $response = $port.ReadLine().Trim()
    }
    if ($response -ne $Expected) {
        throw "Expected '$Expected', received '$response'"
    }
    Write-Host $response
}

try {
    Write-Host "Opening $PortName at $BaudRate baud..."
    $port.Open()
    Start-Sleep -Milliseconds 500
    $port.Write([byte[]]@(13,10), 0, 2)
    Start-Sleep -Milliseconds 100

    $ready = $false
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            $port.DiscardInBuffer()
            $port.WriteLine("PING")
            $response = $port.ReadLine().Trim()
            Write-Host $response
            if ($response -eq "PONG") {
                $ready = $true
                break
            }
        } catch {
            Write-Host "Waiting for dashboard firmware ($attempt/5)..."
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ready) {
        throw "No PONG from ESP8266. Upload dashboard_serial.ino first, or press RESET and retry."
    }

    $port.WriteLine("BEGIN $($bytes.Length)")
    Read-Response "EPD INIT"
    # E-paper cold init + white-buffer clear can take several seconds.
    $port.ReadTimeout = 20000
    Read-Response "READY"
    $port.ReadTimeout = 2000
    $chunkSize = 128
    $offset = 0
    $nextProgress = 12000
    while ($offset -lt $bytes.Length) {
        $count = [Math]::Min($chunkSize, $bytes.Length - $offset)
        $chunk = New-Object byte[] $count
        [Array]::Copy($bytes, $offset, $chunk, 0, $count)
        $port.Write($chunk, 0, $count)
        $port.BaseStream.Flush()
        $response = $port.ReadLine().Trim()
        if (-not $response.StartsWith("ACK ")) {
            throw "Expected ACK at offset $offset, received '$response'"
        }
        $ackSize = [int]$response.Substring(4)
        if ($ackSize -ne ($offset + $count)) {
            throw "ACK mismatch: expected $($offset + $count), received $ackSize"
        }
        $offset += $count
        if ($offset -ge $nextProgress -or $offset -eq $bytes.Length) {
            Write-Host ("Transfer {0:P0}" -f ($offset / $bytes.Length))
            $nextProgress += 12000
        }
    }

    Read-Response "DATA OK"
    $port.WriteLine("REFRESH")
    Read-Response "REFRESHING"

    $port.ReadTimeout = $TimeoutSeconds * 1000
    Read-Response "DONE"
    Write-Host "Dashboard refresh complete."
} finally {
    if ($port.IsOpen) {
        $port.Close()
    }
}
