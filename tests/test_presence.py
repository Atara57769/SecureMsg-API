import pytest
import asyncio
from server import broadcaster

@pytest.mark.asyncio
class TestPresence:

    async def test_get_online_users(self, async_client, register_and_login_async):
        # Setup: Ensure broadcaster is clean (it's a global in the server process)
        # In pytest, the server is shared, so we should be careful.
        # But here we are using the module-level broadcaster.
        
        alice_token = await register_and_login_async(async_client, "alice", "secret123")
        
        # Initially no one is online (broadcaster-wise)
        resp = await async_client.get("/users/online", headers={"Authorization": f"Bearer {alice_token}"})
        assert resp.status_code == 200
        # Might have other users from other tests if not isolated, but let's assume isolation for now
        # or check if our specific user is there.
        assert "alice" not in resp.json()["online_users"]

        # Alice connects to stream
        q = await broadcaster.subscribe("alice")
        try:
            resp = await async_client.get("/users/online", headers={"Authorization": f"Bearer {alice_token}"})
            assert resp.status_code == 200
            assert "alice" in resp.json()["online_users"]
        finally:
            await broadcaster.unsubscribe("alice", q)

        # Alice is gone
        resp = await async_client.get("/users/online", headers={"Authorization": f"Bearer {alice_token}"})
        assert "alice" not in resp.json()["online_users"]

    async def test_presence_broadcast(self, async_client, register_and_login_async):
        alice_token = await register_and_login_async(async_client, "alice", "secret123")
        await register_and_login_async(async_client, "bob",   "secret456")

        # Alice subscribes to listen for presence
        q_alice = await broadcaster.subscribe("alice")
        
        try:
            # Bob connects
            q_bob = await broadcaster.subscribe("bob")
            
            # Alice should receive a 'user_online' event for Bob
            # Alice also receives her own 'online' event if she was first, but here she's already subscribed.
            # Actually, when Alice subscribed, she might have received her own 'online' event.
            
            async def get_presence_event(q, username, status):
                while True:
                    event = await asyncio.wait_for(q.get(), timeout=2.0)
                    if event.get("type") == "presence" and event.get("username") == username and event.get("status") == status:
                        return event

            await get_presence_event(q_alice, "bob", "online")

            # Bob disconnects
            await broadcaster.unsubscribe("bob", q_bob)

            # Alice should receive a 'user_offline' event for Bob
            await get_presence_event(q_alice, "bob", "offline")

        finally:
            await broadcaster.unsubscribe("alice", q_alice)

    async def test_multiple_connections_presence(self, async_client, register_and_login_async):
        await register_and_login_async(async_client, "alice", "secret123")
        await register_and_login_async(async_client, "bob",   "secret456")

        q_alice = await broadcaster.subscribe("alice")
        
        try:
            # Bob connects first time
            q_bob1 = await broadcaster.subscribe("bob")
            
            # Wait for Bob online event
            while True:
                ev = await asyncio.wait_for(q_alice.get(), timeout=2.0)
                if ev.get("type") == "presence" and ev.get("username") == "bob":
                    assert ev["status"] == "online"
                    break

            # Bob connects second time
            q_bob2 = await broadcaster.subscribe("bob")
            
            # Should NOT receive another presence event for Bob in a short window
            try:
                while True:
                    ev = await asyncio.wait_for(q_alice.get(), timeout=0.5)
                    if ev.get("type") == "presence" and ev.get("username") == "bob":
                        pytest.fail("Received redundant presence event")
            except asyncio.TimeoutError:
                pass

            # Bob disconnects first time
            await broadcaster.unsubscribe("bob", q_bob1)
            
            # Should NOT receive offline event yet
            try:
                while True:
                    ev = await asyncio.wait_for(q_alice.get(), timeout=0.5)
                    if ev.get("type") == "presence" and ev.get("username") == "bob":
                        pytest.fail("Received premature offline event")
            except asyncio.TimeoutError:
                pass

            # Bob disconnects second time
            await broadcaster.unsubscribe("bob", q_bob2)
            
            # Now should receive offline event
            while True:
                ev = await asyncio.wait_for(q_alice.get(), timeout=2.0)
                if ev.get("type") == "presence" and ev.get("username") == "bob":
                    assert ev["status"] == "offline"
                    break

        finally:
            await broadcaster.unsubscribe("alice", q_alice)
