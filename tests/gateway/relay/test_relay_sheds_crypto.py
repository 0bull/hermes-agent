"""A normalized connector event crosses the relay without platform signing keys."""
import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.event import MessageEvent, MessageType
from gateway.relay.adapter import RelayAdapter
from gateway.relay.descriptor import CONTRACT_VERSION, CapabilityDescriptor
from gateway.session import SessionSource
from tests.gateway.relay.stub_connector import StubConnector


@pytest.mark.asyncio
async def test_normalized_event_needs_no_platform_signing_key(monkeypatch):
    for name in ("DISCORD_PUBLIC_KEY", "DISCORD_BOT_TOKEN", "TWILIO_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    descriptor = CapabilityDescriptor(CONTRACT_VERSION, "discord", "Discord", 2000,
                                      False, True, True, "discord", "chars")
    connector = StubConnector(descriptor)
    adapter = RelayAdapter(PlatformConfig(), descriptor, transport=connector)
    captured = []

    async def receive(event):
        captured.append(event)

    monkeypatch.setattr(adapter, "handle_message", receive)
    await adapter.connect()
    event = MessageEvent(text="normalized snow 雪", message_type=MessageType.TEXT,
                         source=SessionSource(platform=Platform.DISCORD, chat_id="channel",
                                              chat_type="group", user_id="user", scope_id="tenant"))
    await connector.push_inbound(event)
    assert captured == [event]
