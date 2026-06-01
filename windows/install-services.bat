@echo off
setlocal EnableDelayedExpansion

REM =============================================================================
REM  WaterWorks AI -- NSSM Windows Service Installer
REM =============================================================================
REM  Run as Administrator.
REM
REM  Prerequisites:
REM    1. NSSM on PATH -- https://nssm.cc/download
REM    2. Python venvs created for each component (see README quick start)
REM    3. .env configured (copy .env.example and set ANTHROPIC_API_KEY)
REM    4. Docker Engine running; start infrastructure separately:
REM         docker compose up -d
REM
REM  Services start automatically at boot. The aggregator reconnects
REM  automatically if MCP servers are slow to start -- no startup ordering
REM  required after the first manual start sequence below.
REM
REM  To remove all services: run uninstall-services.bat as Administrator
REM =============================================================================

set "ROOT=%~dp0.."
set "LOGS=C:\logs\waterworks"

if not exist "%LOGS%" mkdir "%LOGS%"

echo.
echo WaterWorks AI -- NSSM Service Installer
echo Root : %ROOT%
echo Logs : %LOGS%
echo.

REM ── 1. Simulator ─────────────────────────────────────────────────────────────
nssm install WaterWorks-Simulator "%ROOT%\simulator\.venv\Scripts\python.exe" "simulator.py"
nssm set WaterWorks-Simulator AppDirectory        "%ROOT%\simulator"
nssm set WaterWorks-Simulator AppStdout           "%LOGS%\simulator.log"
nssm set WaterWorks-Simulator AppStderr           "%LOGS%\simulator-err.log"
nssm set WaterWorks-Simulator AppRotateFiles      1
nssm set WaterWorks-Simulator AppRotateBytes      10485760
nssm set WaterWorks-Simulator Start               SERVICE_AUTO_START
echo [OK] WaterWorks-Simulator

REM ── 2. MQTT MCP server (:8001) ───────────────────────────────────────────────
nssm install WaterWorks-MqttMcp "%ROOT%\mcp-servers\mqtt-mcp\.venv\Scripts\python.exe" "server.py"
nssm set WaterWorks-MqttMcp AppDirectory        "%ROOT%\mcp-servers\mqtt-mcp"
nssm set WaterWorks-MqttMcp AppEnvironmentExtra "FASTMCP_PORT=8001"
nssm set WaterWorks-MqttMcp AppStdout           "%LOGS%\mqtt-mcp.log"
nssm set WaterWorks-MqttMcp AppStderr           "%LOGS%\mqtt-mcp-err.log"
nssm set WaterWorks-MqttMcp AppRotateFiles      1
nssm set WaterWorks-MqttMcp AppRotateBytes      10485760
nssm set WaterWorks-MqttMcp Start               SERVICE_AUTO_START
echo [OK] WaterWorks-MqttMcp

REM ── 3. OPC-UA MCP server (:8002) ─────────────────────────────────────────────
nssm install WaterWorks-OpcuaMcp "%ROOT%\mcp-servers\opcua-mcp\.venv\Scripts\python.exe" "server.py"
nssm set WaterWorks-OpcuaMcp AppDirectory        "%ROOT%\mcp-servers\opcua-mcp"
nssm set WaterWorks-OpcuaMcp AppEnvironmentExtra "FASTMCP_PORT=8002"
nssm set WaterWorks-OpcuaMcp AppStdout           "%LOGS%\opcua-mcp.log"
nssm set WaterWorks-OpcuaMcp AppStderr           "%LOGS%\opcua-mcp-err.log"
nssm set WaterWorks-OpcuaMcp AppRotateFiles      1
nssm set WaterWorks-OpcuaMcp AppRotateBytes      10485760
nssm set WaterWorks-OpcuaMcp Start               SERVICE_AUTO_START
echo [OK] WaterWorks-OpcuaMcp

REM ── 4. InfluxDB MCP server (:8003) ───────────────────────────────────────────
nssm install WaterWorks-InfluxdbMcp "%ROOT%\influxdb-mcp\.venv\Scripts\python.exe" "server.py"
nssm set WaterWorks-InfluxdbMcp AppDirectory        "%ROOT%\influxdb-mcp"
nssm set WaterWorks-InfluxdbMcp AppStdout           "%LOGS%\influxdb-mcp.log"
nssm set WaterWorks-InfluxdbMcp AppStderr           "%LOGS%\influxdb-mcp-err.log"
nssm set WaterWorks-InfluxdbMcp AppRotateFiles      1
nssm set WaterWorks-InfluxdbMcp AppRotateBytes      10485760
nssm set WaterWorks-InfluxdbMcp Start               SERVICE_AUTO_START
echo [OK] WaterWorks-InfluxdbMcp

REM ── 5. Audit MCP server (:8004) ──────────────────────────────────────────────
nssm install WaterWorks-AuditMcp "%ROOT%\audit-mcp\.venv\Scripts\python.exe" "server.py"
nssm set WaterWorks-AuditMcp AppDirectory        "%ROOT%\audit-mcp"
nssm set WaterWorks-AuditMcp AppStdout           "%LOGS%\audit-mcp.log"
nssm set WaterWorks-AuditMcp AppStderr           "%LOGS%\audit-mcp-err.log"
nssm set WaterWorks-AuditMcp AppRotateFiles      1
nssm set WaterWorks-AuditMcp AppRotateBytes      10485760
nssm set WaterWorks-AuditMcp Start               SERVICE_AUTO_START
echo [OK] WaterWorks-AuditMcp

REM ── 6. Control MCP server (:8005) ────────────────────────────────────────────
nssm install WaterWorks-ControlMcp "%ROOT%\control-mcp\.venv\Scripts\python.exe" "server.py"
nssm set WaterWorks-ControlMcp AppDirectory        "%ROOT%\control-mcp"
nssm set WaterWorks-ControlMcp AppStdout           "%LOGS%\control-mcp.log"
nssm set WaterWorks-ControlMcp AppStderr           "%LOGS%\control-mcp-err.log"
nssm set WaterWorks-ControlMcp AppRotateFiles      1
nssm set WaterWorks-ControlMcp AppRotateBytes      10485760
nssm set WaterWorks-ControlMcp Start               SERVICE_AUTO_START
echo [OK] WaterWorks-ControlMcp

REM ── 7. MCP Aggregator (:8100) ────────────────────────────────────────────────
nssm install WaterWorks-Aggregator "%ROOT%\mcp-aggregator\server\.venv\Scripts\python.exe" "server.py"
nssm set WaterWorks-Aggregator AppDirectory        "%ROOT%\mcp-aggregator\server"
nssm set WaterWorks-Aggregator AppEnvironmentExtra "BACKENDS_FILE=%ROOT%\mcp-aggregator\backends.json"
nssm set WaterWorks-Aggregator AppStdout           "%LOGS%\aggregator.log"
nssm set WaterWorks-Aggregator AppStderr           "%LOGS%\aggregator-err.log"
nssm set WaterWorks-Aggregator AppRotateFiles      1
nssm set WaterWorks-Aggregator AppRotateBytes      10485760
nssm set WaterWorks-Aggregator Start               SERVICE_AUTO_START
echo [OK] WaterWorks-Aggregator

REM ── 8. MQTT → InfluxDB Bridge ────────────────────────────────────────────────
nssm install WaterWorks-Bridge "%ROOT%\mqtt-influx-bridge\.venv\Scripts\python.exe" "bridge.py"
nssm set WaterWorks-Bridge AppDirectory        "%ROOT%\mqtt-influx-bridge"
nssm set WaterWorks-Bridge AppStdout           "%LOGS%\bridge.log"
nssm set WaterWorks-Bridge AppStderr           "%LOGS%\bridge-err.log"
nssm set WaterWorks-Bridge AppRotateFiles      1
nssm set WaterWorks-Bridge AppRotateBytes      10485760
nssm set WaterWorks-Bridge Start               SERVICE_AUTO_START
echo [OK] WaterWorks-Bridge

REM ── 9. Chat UI (:8080) ───────────────────────────────────────────────────────
nssm install WaterWorks-ChatUI "%ROOT%\chat-ui\.venv\Scripts\python.exe" "backend.py"
nssm set WaterWorks-ChatUI AppDirectory        "%ROOT%\chat-ui"
nssm set WaterWorks-ChatUI AppStdout           "%LOGS%\chat-ui.log"
nssm set WaterWorks-ChatUI AppStderr           "%LOGS%\chat-ui-err.log"
nssm set WaterWorks-ChatUI AppRotateFiles      1
nssm set WaterWorks-ChatUI AppRotateBytes      10485760
nssm set WaterWorks-ChatUI Start               SERVICE_AUTO_START
echo [OK] WaterWorks-ChatUI

echo.
echo All services installed. Start them in order the first time:
echo.
echo   docker compose up -d
echo   net start WaterWorks-Simulator
echo   net start WaterWorks-MqttMcp
echo   net start WaterWorks-OpcuaMcp
echo   net start WaterWorks-InfluxdbMcp
echo   net start WaterWorks-AuditMcp
echo   net start WaterWorks-ControlMcp
echo   net start WaterWorks-Aggregator
echo   net start WaterWorks-Bridge
echo   net start WaterWorks-ChatUI
echo.
echo After first boot, all services start automatically.
echo Logs: %LOGS%
echo.
