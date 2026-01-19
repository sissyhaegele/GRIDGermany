# Start Remote-Controlled Sensor für Solace Cloud Broker
# PowerShell Version

Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  Remote-Controlled Powerline Sensor - Quick Start           ║" -ForegroundColor Cyan
Write-Host "║  Berliner Stadtwerke                                         ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Solace Broker Configuration
$env:SOLACE_HOST = "mr-connection-gu0w0pjgchg.messaging.solace.cloud"
$env:SOLACE_PORT = "1883"
$env:SOLACE_USERNAME = "solace-cloud-client"
$env:SOLACE_PASSWORD = "iejmgp94muv7m5ahsfe9b50dvb"

# Sensor ID (kann überschrieben werden)
if (-not $env:SENSOR_ID) {
    $env:SENSOR_ID = "TRF-MIT-042"
}

Write-Host "✓ Configuration:" -ForegroundColor Green
Write-Host "  Broker:    $env:SOLACE_HOST`:$env:SOLACE_PORT"
Write-Host "  Username:  $env:SOLACE_USERNAME"
Write-Host "  Sensor ID: $env:SENSOR_ID"
Write-Host ""
Write-Host "Starting sensor..." -ForegroundColor Yellow
Write-Host ""

# Start sensor
python remote_controlled_sensor.py
