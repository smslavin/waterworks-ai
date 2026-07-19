#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Install the waterworks-ai stack as Windows services via NSSM.

.DESCRIPTION
    Installs nine services:
      WaterWorks Simulator      — MQTT + OPC-UA publisher, fault/setpoint control (:8090)
      WaterWorks InfluxdbMcp    — InfluxDB MCP server    (:8003)
      WaterWorks AuditMcp       — Audit query MCP server (:8004)
      WaterWorks ControlMcp     — Control write MCP server (:8005)
      WaterWorks MemoryMcp      — Memory MCP server      (:8006)
      WaterWorks TopologyBuilder — Topology builder MCP server (:8007)
      WaterWorks Aggregator     — MCP aggregator         (:8110 by default)
      WaterWorks Bridge         — MQTT → InfluxDB bridge
      WaterWorks ChatUI         — Chat UI backend        (:8082 by default)

    mqtt-mcp/opcua-mcp are no longer separate services — they're Rust binaries
    (fieldworks-adapters) the aggregator spawns itself as stdio subprocesses.
    Install them once, outside this script, and make sure they're on the
    service account's PATH:
      cargo install --git https://github.com/fieldworks-build/fieldworks-adapters mqtt-mcp opcua-mcp
    Since they no longer bind their own port, the graccess-mcp offset-port
    concern that used to apply to them (8011/8012) no longer exists.

    Default ports are offset from waterworks defaults (8080, 8100) to avoid
    conflicts with graccess-mcp running on the same host. Adjust the port
    variables in the Configuration block if not co-hosting.

    MQTT broker is shared with graccess — no separate Mosquitto service.
    InfluxDB and Grafana must be installed natively (not via Docker):
      InfluxDB: https://docs.influxdata.com/influxdb/v2/install/?t=Windows
      Grafana:  https://grafana.com/docs/grafana/latest/setup-grafana/installation/windows/

    NSSM pre-release build required (2.24-NNN-gHASH):
      https://nssm.cc/download  (use the pre-release zip, not the 2.24 stable release)

.EXAMPLE
    # Edit the Configuration block below if needed, then:
    .\install-services.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Configuration ──────────────────────────────────────────────────────────────

$WaterworksRoot = Resolve-Path "$PSScriptRoot\.."

# Ports — offset from waterworks defaults to coexist with graccess-mcp.
# If running standalone (no graccess), change these back to 8080, 8100.
$InfluxdbMcpPort = "8003"
$AuditMcpPort         = "8004"
$ControlMcpPort       = "8005"
$MemoryMcpPort        = "8006"
$TopologyBuilderPort  = "8007"
$AggregatorPort       = "8110"
$ChatUIPort      = "8082"
$SimControlPort  = "8090"   # simulator fault/setpoint HTTP

# MQTT — shared broker with graccess
$MqttBrokerUrl   = "localhost"
$MqttBrokerPort  = "1883"

# OPC-UA (graccess uses 4841; waterworks uses 4840 — no conflict)
$OpcuaPort       = "4840"
$PublishInterval = "2.0"

# InfluxDB (native Windows install)
$InfluxdbUrl     = "http://localhost:8086"

# Backends file — use the Windows-specific one with offset ports
$BackendsFile    = Resolve-Path "$WaterworksRoot\windows\backends.windows.json"

# Log directory
$LogDir          = "C:\logs\waterworks"

# ── End Configuration ──────────────────────────────────────────────────────────

function Resolve-AbsPath($Base, $Relative) {
    [System.IO.Path]::GetFullPath((Join-Path $Base $Relative))
}

# Verify NSSM is available and is the pre-release build
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Error "nssm not found on PATH. Download from https://nssm.cc/download and add to PATH."
}
$nssmVer = (nssm version 2>&1) -join " "
if ($nssmVer -notmatch "2\.\d+-\d+-g[0-9a-f]+") {
    Write-Error "NSSM pre-release build required for AppTimestampLog support.`nFound: $nssmVer`nDownload the pre-release zip from https://nssm.cc/download"
}

# Create log directory
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# ── Service definitions ────────────────────────────────────────────────────────

$Services = @(
    @{
        Name    = "WaterWorks Simulator"
        Exe     = Resolve-AbsPath $WaterworksRoot "simulator\.venv\Scripts\python.exe"
        Args    = "simulator.py"
        WorkDir = Resolve-AbsPath $WaterworksRoot "simulator"
        LogOut  = Join-Path $LogDir "simulator.log"
        LogErr  = Join-Path $LogDir "simulator-err.log"
        Env     = @(
            "MQTT_BROKER_URL=$MqttBrokerUrl"
            "MQTT_BROKER_PORT=$MqttBrokerPort"
            "OPCUA_PORT=$OpcuaPort"
            "PUBLISH_INTERVAL=$PublishInterval"
            "CONTROL_PORT=$SimControlPort"
        )
        Desc    = "WaterWorks AI — MQTT + OPC-UA simulator with fault injection (port $SimControlPort)"
    },
    @{
        Name    = "WaterWorks InfluxdbMcp"
        Exe     = Resolve-AbsPath $WaterworksRoot "influxdb-mcp\.venv\Scripts\python.exe"
        Args    = "server.py"
        WorkDir = Resolve-AbsPath $WaterworksRoot "influxdb-mcp"
        LogOut  = Join-Path $LogDir "influxdb-mcp.log"
        LogErr  = Join-Path $LogDir "influxdb-mcp-err.log"
        Env     = @(
            "FASTMCP_PORT=$InfluxdbMcpPort"
            "INFLUXDB_URL=$InfluxdbUrl"
        )
        Desc    = "WaterWorks AI — InfluxDB MCP server (port $InfluxdbMcpPort)"
    },
    @{
        Name    = "WaterWorks AuditMcp"
        Exe     = Resolve-AbsPath $WaterworksRoot "audit-mcp\.venv\Scripts\python.exe"
        Args    = "server.py"
        WorkDir = Resolve-AbsPath $WaterworksRoot "audit-mcp"
        LogOut  = Join-Path $LogDir "audit-mcp.log"
        LogErr  = Join-Path $LogDir "audit-mcp-err.log"
        Env     = @(
            "FASTMCP_PORT=$AuditMcpPort"
        )
        Desc    = "WaterWorks AI — Audit query MCP server (port $AuditMcpPort)"
    },
    @{
        Name    = "WaterWorks ControlMcp"
        Exe     = Resolve-AbsPath $WaterworksRoot "control-mcp\.venv\Scripts\python.exe"
        Args    = "server.py"
        WorkDir = Resolve-AbsPath $WaterworksRoot "control-mcp"
        LogOut  = Join-Path $LogDir "control-mcp.log"
        LogErr  = Join-Path $LogDir "control-mcp-err.log"
        Env     = @(
            "FASTMCP_PORT=$ControlMcpPort"
            "SIMULATOR_URL=http://localhost:$SimControlPort"
        )
        Desc    = "WaterWorks AI — Control write MCP server (port $ControlMcpPort)"
    },
    @{
        Name    = "WaterWorks MemoryMcp"
        Exe     = Resolve-AbsPath $WaterworksRoot "memory-mcp\.venv\Scripts\python.exe"
        Args    = "server.py"
        WorkDir = Resolve-AbsPath $WaterworksRoot "memory-mcp"
        LogOut  = Join-Path $LogDir "memory-mcp.log"
        LogErr  = Join-Path $LogDir "memory-mcp-err.log"
        Env     = @(
            "MEMORY_MCP_PORT=$MemoryMcpPort"
            "LADYBUG_DB_PATH=$(Resolve-AbsPath $WaterworksRoot 'data\ladybugdb\fieldworks.db')"
            "DUCKDB_PATH=$(Resolve-AbsPath $WaterworksRoot 'data\duckdb\analytical.duckdb')"
            "SPECIALIST_MEMORY_DIR=$(Resolve-AbsPath $WaterworksRoot 'data\specialist-memory')"
            "INFLUXDB_URL=$InfluxdbUrl"
        )
        Desc    = "WaterWorks AI — Memory MCP server (port $MemoryMcpPort)"
    },
    @{
        Name    = "WaterWorks TopologyBuilder"
        Exe     = Resolve-AbsPath $WaterworksRoot "topology-builder\.venv\Scripts\python.exe"
        Args    = "server.py"
        WorkDir = Resolve-AbsPath $WaterworksRoot "topology-builder"
        LogOut  = Join-Path $LogDir "topology-builder.log"
        LogErr  = Join-Path $LogDir "topology-builder-err.log"
        Env     = @(
            "TOPOLOGY_BUILDER_PORT=$TopologyBuilderPort"
            "MEMORY_MCP_URL=http://localhost:$MemoryMcpPort"
            "MQTT_BROKER_URL=$MqttBrokerUrl"
            "MQTT_BROKER_PORT=$MqttBrokerPort"
        )
        Desc    = "WaterWorks AI — Topology builder MCP server (port $TopologyBuilderPort)"
    },
    @{
        Name    = "WaterWorks Aggregator"
        Exe     = Resolve-AbsPath $WaterworksRoot "mcp-aggregator\server\.venv\Scripts\python.exe"
        Args    = "server.py"
        WorkDir = Resolve-AbsPath $WaterworksRoot "mcp-aggregator\server"
        LogOut  = Join-Path $LogDir "aggregator.log"
        LogErr  = Join-Path $LogDir "aggregator-err.log"
        Env     = @(
            "AGGREGATOR_PORT=$AggregatorPort"
            "BACKENDS_FILE=$BackendsFile"
        )
        Desc    = "WaterWorks AI — MCP aggregator (port $AggregatorPort)"
    },
    @{
        Name    = "WaterWorks Bridge"
        Exe     = Resolve-AbsPath $WaterworksRoot "mqtt-influx-bridge\.venv\Scripts\python.exe"
        Args    = "bridge.py"
        WorkDir = Resolve-AbsPath $WaterworksRoot "mqtt-influx-bridge"
        LogOut  = Join-Path $LogDir "bridge.log"
        LogErr  = Join-Path $LogDir "bridge-err.log"
        Env     = @(
            "MQTT_BROKER_URL=$MqttBrokerUrl"
            "MQTT_BROKER_PORT=$MqttBrokerPort"
            "INFLUXDB_URL=$InfluxdbUrl"
        )
        Desc    = "WaterWorks AI — MQTT to InfluxDB bridge"
    },
    @{
        Name    = "WaterWorks ChatUI"
        Exe     = Resolve-AbsPath $WaterworksRoot "chat-ui\.venv\Scripts\python.exe"
        Args    = "backend.py"
        WorkDir = Resolve-AbsPath $WaterworksRoot "chat-ui"
        LogOut  = Join-Path $LogDir "chat-ui.log"
        LogErr  = Join-Path $LogDir "chat-ui-err.log"
        Env     = @($(
            # Read .env to pick up ANTHROPIC_API_KEY and other runtime config
            $envFile = Resolve-AbsPath $WaterworksRoot ".env"
            if (Test-Path $envFile) {
                Get-Content $envFile | Where-Object { $_ -match '^\s*[^#][^=]+=.+$' }
            } else {
                Write-Warning ".env not found — ChatUI will start without API keys. Copy .env.example to .env and set ANTHROPIC_API_KEY."
            }
            "CHAT_PORT=$ChatUIPort"
            "MCP_AGGREGATOR_URL=http://localhost:$AggregatorPort/sse"
        ))
        Desc    = "WaterWorks AI — Chat UI backend (port $ChatUIPort)"
    }
)

# ── Install ────────────────────────────────────────────────────────────────────

foreach ($svc in $Services) {
    $name = $svc.Name
    Write-Host "`nInstalling $name ..." -ForegroundColor Cyan

    $existing = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  Removing existing $name"
        if ($existing.Status -eq "Running") { nssm stop $name confirm }
        nssm remove $name confirm
    }

    nssm install $name $svc.Exe $svc.Args
    nssm set $name AppDirectory  $svc.WorkDir
    nssm set $name Description   $svc.Desc
    nssm set $name AppStdout     $svc.LogOut
    nssm set $name AppStderr     $svc.LogErr
    nssm set $name AppStdoutCreationDisposition 4   # append
    nssm set $name AppStderrCreationDisposition 4   # append
    nssm set $name AppRotateFiles  1
    nssm set $name AppRotateBytes  10485760           # 10 MB
    nssm set $name AppTimestampLog 1
    nssm set $name AppExit Default Restart
    nssm set $name AppRestartDelay 60000
    nssm set $name Start SERVICE_AUTO_START

    $envBlock = $svc.Env -join "`n"
    nssm set $name AppEnvironmentExtra $envBlock

    Write-Host "  $name installed OK" -ForegroundColor Green
}

# ── Start ──────────────────────────────────────────────────────────────────────

Write-Host "`nStarting services ..." -ForegroundColor Cyan

$startOrder = @(
    "WaterWorks Simulator",
    "WaterWorks InfluxdbMcp",
    "WaterWorks AuditMcp",
    "WaterWorks ControlMcp",
    "WaterWorks MemoryMcp",
    "WaterWorks TopologyBuilder",
    "WaterWorks Aggregator",
    "WaterWorks Bridge",
    "WaterWorks ChatUI"
)

foreach ($name in $startOrder) {
    nssm start $name
    Start-Sleep -Milliseconds 500
    $status = (Get-Service -Name $name).Status
    Write-Host "  $name — $status"
}

Write-Host "`nDone." -ForegroundColor Green
Write-Host "  UI:   http://localhost:$ChatUIPort"
Write-Host "  Logs: $LogDir"
Write-Host "`nServices start automatically at boot."
Write-Host "To remove: .\uninstall-services.ps1"
