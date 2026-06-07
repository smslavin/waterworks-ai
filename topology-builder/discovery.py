"""MQTT and OPC-UA crawlers for topology discovery."""

import asyncio

import paho.mqtt.client as mqtt

CRAWL_DURATION = 10.0


class MQTTCrawler:
    """Subscribe to # and collect all topics seen during the crawl window."""

    def __init__(self, broker_url: str, duration: float = CRAWL_DURATION):
        self.host, self.port = _parse_broker_url(broker_url)
        self.duration = duration

    async def crawl(self) -> dict[str, str]:
        """Returns {topic: last_value_str}."""
        topics: dict[str, str] = {}

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_message = lambda c, u, msg: topics.update(
            {msg.topic: msg.payload.decode(errors="replace")}
        )
        client.connect(self.host, self.port, 60)
        client.subscribe("#")
        client.loop_start()
        await asyncio.sleep(self.duration)
        client.loop_stop()
        client.disconnect()
        return topics


class OPCUACrawler:
    """Browse OPC-UA node tree and return all leaf node browse paths."""

    def __init__(self, opcua_url: str):
        self.url = opcua_url

    async def crawl(self) -> list[str]:
        """Returns list of node path strings."""
        try:
            from asyncua import Client as OPCUAClient
        except ImportError:
            return []

        paths: list[str] = []
        try:
            async with OPCUAClient(url=self.url) as client:
                root = client.nodes.root
                await _browse_recursive(root, "", paths)
        except Exception:
            pass
        return paths


async def _browse_recursive(node, prefix: str, out: list[str]) -> None:
    try:
        children = await node.get_children()
        for child in children:
            name = (await child.read_browse_name()).Name
            path = f"{prefix}/{name}" if prefix else name
            grandchildren = await child.get_children()
            if not grandchildren:
                out.append(path)
            else:
                await _browse_recursive(child, path, out)
    except Exception:
        pass


def _parse_broker_url(url: str) -> tuple[str, int]:
    url = url.replace("mqtt://", "")
    parts = url.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 1883
    return host, port
