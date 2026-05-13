import pytest
import asyncio
import json
from datetime import datetime, timedelta, timezone
from server import broadcaster
from server.main import app

@pytest.mark.asyncio
class TestSSEStream:

    async def test_sse_stream_receives_broadcast(self, async_client, register_and_login_async):
        alice_token = await register_and_login_async(async_client, "alice", "secret123")
        await register_and_login_async(async_client, "bob",   "secret456")

        # Directly subscribe to the broadcaster to verify real-time delivery
        q = broadcaster.subscribe("bob")
        try:
            await async_client.post(
                "/messages",
                json={"content": "sse test", "recipients": ["bob"]},
                headers={"Authorization": f"Bearer {alice_token}"},
            )

            # Wait for the message in the queue (direct verification)
            result = await asyncio.wait_for(q.get(), timeout=2.0)
            assert result["content"] == "sse test"
            assert result["sender"] == "alice"
        finally:
            broadcaster.unsubscribe("bob", q)


@pytest.mark.asyncio
class TestSSEConcurrent:

    async def test_concurrent_clients(self, async_client, register_and_login_async):
        alice_token = await register_and_login_async(async_client, "alice", "secret123")
        bob_token   = await register_and_login_async(async_client, "bob",   "secret456")

        # Subscribe both users
        q_alice = broadcaster.subscribe("alice")
        q_bob   = broadcaster.subscribe("bob")
        
        try:
            # Send messages
            await async_client.post(
                "/messages", 
                json={"content": "hi bob", "recipients": ["bob"]}, 
                headers={"Authorization": f"Bearer {alice_token}"}
            )
            await async_client.post(
                "/messages", 
                json={"content": "hi alice", "recipients": ["alice"]}, 
                headers={"Authorization": f"Bearer {bob_token}"}
            )

            # Verify both received their respective messages
            # Note: Each user also receives their own sent messages as a broadcast
            
            async def find_msg(q, content):
                while True:
                    m = await asyncio.wait_for(q.get(), timeout=2.0)
                    if m["content"] == content:
                        return m

            res_bob   = await find_msg(q_bob, "hi bob")
            res_alice = await find_msg(q_alice, "hi alice")

            assert res_bob["content"] == "hi bob"
            assert res_alice["content"] == "hi alice"
        finally:
            broadcaster.unsubscribe("alice", q_alice)
            broadcaster.unsubscribe("bob", q_bob)


@pytest.mark.asyncio
class TestSSEAuthEnforcement:

    async def test_stream_rejects_expired_token(self, async_client):
        from jose import jwt
        from server.auth import SECRET_KEY, ALGORITHM
        
        expired_payload = {
            "sub": "alice", 
            "exp": datetime.now(timezone.utc) - timedelta(hours=1)
        }
        token = jwt.encode(expired_payload, SECRET_KEY, algorithm=ALGORITHM)
        response = await async_client.get("/stream", params={"token": token})
        assert response.status_code == 401

    async def test_stream_rejects_tampered_token(self, async_client, register_and_login_async):
        token = await register_and_login_async(async_client, "alice", "secret123")
        tampered = token[:-5] + "XXXXX"
        response = await async_client.get("/stream", params={"token": tampered})
        assert response.status_code == 401
