# Sensor Control - Command Line (PowerShell)
# Verwendet Python mit paho-mqtt

$BROKER = "mr-connection-gu0w0pjgchg.messaging.solace.cloud"
$PORT = 1883
$USERNAME = "solace-cloud-client"
$PASSWORD = "iejmgp94muv7m5ahsfe9b50dvb"
$SENSOR_ID = "TRF-MIT-042"

Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  Sensor Control - Command Line                               ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "Sensor: $SENSOR_ID" -ForegroundColor Yellow
Write-Host "Broker: $BROKER"
Write-Host ""

function Send-Command {
    param(
        [string]$Command,
        [int]$Duration = 0
    )
    
    $timestamp = [DateTimeOffset]::Now.ToUnixTimeSeconds()
    
    if ($Duration -gt 0) {
        $payload = "{`"command`":`"$Command`",`"duration`":$Duration,`"requestId`":`"req-$timestamp`"}"
    } else {
        $payload = "{`"command`":`"$Command`",`"requestId`":`"req-$timestamp`"}"
    }
    
    Write-Host "→ Sending command: $Command" -ForegroundColor Yellow
    
    # Create Python script to send command
    $pythonScript = @"
import paho.mqtt.client as mqtt
import sys

client = mqtt.Client()
client.username_pw_set('$USERNAME', '$PASSWORD')

try:
    client.connect('$BROKER', $PORT, 60)
    result = client.publish('control/sensor/$SENSOR_ID/command', '$payload', qos=1)
    if result.rc == 0:
        print('✓ Command sent successfully!')
        sys.exit(0)
    else:
        print('✗ Failed to send command')
        sys.exit(1)
except Exception as e:
    print(f'✗ Error: {e}')
    sys.exit(1)
finally:
    client.disconnect()
"@

    # Save temp Python script
    $tempFile = [System.IO.Path]::GetTempFileName() + ".py"
    $pythonScript | Out-File -FilePath $tempFile -Encoding UTF8
    
    # Execute
    python $tempFile
    
    # Cleanup
    Remove-Item $tempFile
    Write-Host ""
}

# Main menu loop
while ($true) {
    Write-Host "Commands:" -ForegroundColor Cyan
    Write-Host "  1) START sensor"
    Write-Host "  2) STOP sensor"
    Write-Host "  3) PAUSE sensor (5 minutes)"
    Write-Host "  4) Exit"
    Write-Host ""
    
    $choice = Read-Host "Choose [1-4]"
    
    switch ($choice) {
        "1" {
            Send-Command -Command "start"
        }
        "2" {
            Send-Command -Command "stop"
        }
        "3" {
            Send-Command -Command "pause" -Duration 300
        }
        "4" {
            Write-Host "Goodbye!" -ForegroundColor Green
            exit
        }
        default {
            Write-Host "Invalid choice!" -ForegroundColor Red
        }
    }
}
