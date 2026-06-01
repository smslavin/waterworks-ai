@echo off

REM =============================================================================
REM  WaterWorks AI -- NSSM Windows Service Uninstaller
REM =============================================================================
REM  Run as Administrator.
REM  Stops and removes all WaterWorks AI services. Does not touch Docker,
REM  venvs, data, or logs.
REM =============================================================================

echo.
echo WaterWorks AI -- Removing NSSM services
echo.

for %%S in (
    WaterWorks-Simulator
    WaterWorks-MqttMcp
    WaterWorks-OpcuaMcp
    WaterWorks-InfluxdbMcp
    WaterWorks-AuditMcp
    WaterWorks-ControlMcp
    WaterWorks-Aggregator
    WaterWorks-Bridge
    WaterWorks-ChatUI
) do (
    nssm stop %%S 2>nul
    nssm remove %%S confirm
    echo [removed] %%S
)

echo.
echo Done. Docker infrastructure (Mosquitto, InfluxDB, Grafana) not affected.
echo To stop Docker: docker compose down
echo.
