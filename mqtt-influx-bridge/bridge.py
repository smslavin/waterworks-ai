"""MQTT → InfluxDB bridge for waterworks-ai.

Subscribes to Plant/WTP/# and writes every reading as a tagged point to InfluxDB.
Topic pattern: Plant/WTP/<Type>/<Instance>/<Attribute>

InfluxDB schema
---------------
  measurement : wtp_process
  tags        : type, instance, attribute
  field       : value  (float; booleans arrive as 0/1 from the simulator)
"""

import logging
import os
import signal
import sys

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WriteOptions

load_dotenv()

MQTT_HOST       = os.environ.get("MQTT_BROKER_URL",   "localhost")
MQTT_PORT       = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
MQTT_TOPIC      = "Plant/WTP/#"
INFLUXDB_URL    = os.environ.get("INFLUXDB_URL",    "http://localhost:8086")
INFLUXDB_TOKEN  = os.environ.get("INFLUXDB_TOKEN",  "")
INFLUXDB_ORG    = os.environ.get("INFLUXDB_ORG",    "waterworks")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "waterworks")
MEASUREMENT     = "wtp_process"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

influx    = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
write_api = influx.write_api(
    write_options=WriteOptions(batch_size=100, flush_interval=2_000)
)


def parse_value(raw: str) -> float | None:
    try:
        return float(raw.strip())
    except ValueError:
        return None


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info("MQTT connected  %s:%d — subscribing to %s", MQTT_HOST, MQTT_PORT, MQTT_TOPIC)
        client.subscribe(MQTT_TOPIC)
    else:
        logger.error("MQTT connect failed  rc=%d", rc)


def on_message(client, userdata, msg):
    parts = msg.topic.split("/")
    # Expected: Plant / WTP / <Type> / <Instance> / <Attribute>
    if len(parts) != 5:
        return
    _, _, type_, instance, attribute = parts
    value = parse_value(msg.payload.decode("utf-8", errors="ignore"))
    if value is None:
        return
    point = (
        Point(MEASUREMENT)
        .tag("type",      type_)
        .tag("instance",  instance)
        .tag("attribute", attribute)
        .field("value",   value)
    )
    write_api.write(bucket=INFLUXDB_BUCKET, record=point)


def main() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    def _shutdown(sig, frame):
        logger.info("Shutting down…")
        write_api.close()
        influx.close()
        client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Connecting to MQTT broker at %s:%d", MQTT_HOST, MQTT_PORT)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    logger.info("Bridge running — writing %s → InfluxDB bucket '%s'", MQTT_TOPIC, INFLUXDB_BUCKET)
    client.loop_forever()


if __name__ == "__main__":
    main()
