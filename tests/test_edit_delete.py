import pytest
import asyncio
from httpx import AsyncClient

@pytest.mark.asyncio
class TestEditDelete:

    async def test_edit_message_success(self, async_client, register_and_login_async, auth_helper):
        alice_token = await register_and_login_async(async_client, "alice", "secret123")
        await register_and_login_async(async_client, "bob", "secret456")

        # Send a message
        send_resp = await async_client.post(
            "/messages",
            json={"content": "original content", "recipients": ["bob"]},
            headers=auth_helper(alice_token),
        )
        msg_id = send_resp.json()[0]["id"]

        # Edit the message
        edit_resp = await async_client.patch(
            f"/messages/{msg_id}",
            json={"content": "edited content"},
            headers=auth_helper(alice_token),
        )
        assert edit_resp.status_code == 200
        assert edit_resp.json()["content"] == "edited content"
        assert edit_resp.json()["updated_at"] is not None

        # Verify in history
        history_resp = await async_client.get("/messages", headers=auth_helper(alice_token))
        assert history_resp.json()[0]["content"] == "edited content"

    async def test_delete_message_success(self, async_client, register_and_login_async, auth_helper):
        alice_token = await register_and_login_async(async_client, "alice", "secret123")
        await register_and_login_async(async_client, "bob", "secret456")

        # Send a message
        send_resp = await async_client.post(
            "/messages",
            json={"content": "to be deleted", "recipients": ["bob"]},
            headers=auth_helper(alice_token),
        )
        msg_id = send_resp.json()[0]["id"]

        # Delete the message
        del_resp = await async_client.delete(
            f"/messages/{msg_id}",
            headers=auth_helper(alice_token),
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["is_deleted"] is True

        # Verify it's gone from history
        history_resp = await async_client.get("/messages", headers=auth_helper(alice_token))
        assert len(history_resp.json()) == 0

    async def test_edit_delete_permission_denied(self, async_client, register_and_login_async, auth_helper):
        alice_token = await register_and_login_async(async_client, "alice", "secret123")
        bob_token = await register_and_login_async(async_client, "bob", "secret456")

        # Alice sends a message to Bob
        send_resp = await async_client.post(
            "/messages",
            json={"content": "alice message", "recipients": ["bob"]},
            headers=auth_helper(alice_token),
        )
        msg_id = send_resp.json()[0]["id"]

        # Bob tries to edit Alice's message
        edit_resp = await async_client.patch(
            f"/messages/{msg_id}",
            json={"content": "bob hack"},
            headers=auth_helper(bob_token),
        )
        assert edit_resp.status_code == 403

        # Bob tries to delete Alice's message
        del_resp = await async_client.delete(
            f"/messages/{msg_id}",
            headers=auth_helper(bob_token),
        )
        assert del_resp.status_code == 403

    async def test_broadcast_edit_delete(self, async_client, register_and_login_async, auth_helper):
        alice_token = await register_and_login_async(async_client, "alice", "secret123")
        bob_token = await register_and_login_async(async_client, "bob", "secret456")

        # Alice sends a message
        send_resp = await async_client.post(
            "/messages",
            json={"content": "hello", "recipients": ["bob"]},
            headers=auth_helper(alice_token),
        )
        msg_id = send_resp.json()[0]["id"]

        # Bob listens to the stream
        # We'll use a mock subscriber queue since we can't easily test SSE stream with httpx in this environment 
        # without complex async setup. Actually, let's try to subscribe directly to broadcaster.
        from server import broadcaster
        bob_queue = await broadcaster.subscribe("bob")
        
        try:
            # Alice edits the message
            await async_client.patch(
                f"/messages/{msg_id}",
                json={"content": "hello edited"},
                headers=auth_helper(alice_token),
            )

            # Check Bob's queue for the edit event (skip presence events)
            while True:
                event = await asyncio.wait_for(bob_queue.get(), timeout=1.0)
                if event.get("type") != "presence":
                    break
            
            assert event["type"] == "edit"
            assert event["id"] == msg_id
            assert event["content"] == "hello edited"

            # Alice deletes the message
            await async_client.delete(
                f"/messages/{msg_id}",
                headers=auth_helper(alice_token),
            )

            # Check Bob's queue for the delete event
            event = await asyncio.wait_for(bob_queue.get(), timeout=1.0)
            assert event["type"] == "delete"
            assert event["id"] == msg_id
            assert event["is_deleted"] is True
        finally:
            await broadcaster.unsubscribe("bob", bob_queue)
