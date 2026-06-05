#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Remove all WaterWorks AI Windows services.
.DESCRIPTION
    Stops and removes all WaterWorks AI services installed by install-services.ps1.
    Does not affect InfluxDB, Grafana, or the shared MQTT broker.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$services = @(
    "WaterWorks Simulator",
    "WaterWorks MqttMcp",
    "WaterWorks OpcuaMcp",
    "WaterWorks InfluxdbMcp",
    "WaterWorks AuditMcp",
    "WaterWorks ControlMcp",
    "WaterWorks Aggregator",
    "WaterWorks Bridge",
    "WaterWorks ChatUI"
)

Write-Host "`nRemoving WaterWorks AI services ..." -ForegroundColor Cyan

foreach ($name in $services) {
    $existing = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.Status -eq "Running") { nssm stop $name confirm }
        nssm remove $name confirm
        Write-Host "  [removed] $name" -ForegroundColor Green
    } else {
        Write-Host "  [skip]    $name (not installed)"
    }
}

Write-Host "`nDone. InfluxDB, Grafana, and MQTT broker not affected." -ForegroundColor Green
