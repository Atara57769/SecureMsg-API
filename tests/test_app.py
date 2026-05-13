import pytest
import asyncio
from server.crypto import encrypt, decrypt

# Note: Common fixtures like fresh_db, async_client, broadcaster, and app setup
# are now located in tests/conftest.py

# ===========================================================================
# 1. Authentication tests
# ===========================================================================

class TestAuthentication:

    @pytest.mark.asyncio
    async def test_register_success(self, async_client):
        response = await async_client.post("/register", json={"username": "alice", "password": "secret123"})
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self, async_client):
        await async_client.post("/register", json={"username": "alice", "password": "secret123"})
        response = await async_client.post("/register", json={"username": "alice", "password": "other-password"})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_login_success(self, async_client):
        await async_client.post("/register", json={"username": "alice", "password": "secret123"})
        response = await async_client.post("/login", json={"username": "alice", "password": "secret123"})
        assert response.status_code == 200
        assert "access_token" in response.json()

    @pytest.mark.asyncio
    async def test_messages_require_token(self, async_client):
        response = await async_client.get("/messages")
        assert response.status_code in (401, 403)


# ===========================================================================
# 2. Encryption tests
# ===========================================================================

class TestEncryption:

    def test_encrypt_is_not_plain_text(self):
        assert encrypt("hello world") != "hello world"

    def test_decrypt_round_trip(self):
        original = "this is a secret message"
        assert decrypt(encrypt(original)) == original

    @pytest.mark.asyncio
    async def test_messages_are_stored_encrypted(self, async_client, register_and_login_async, auth_helper, db_session):
        from server.models import Message
        token = await register_and_login_async(async_client, "alice", "secret123")
        await register_and_login_async(async_client, "bob", "secret456")
        
        await async_client.post(
            "/messages",
            json={"content": "my secret message", "recipients": ["bob"]},
            headers=auth_helper(token)
        )
        
        row = db_session.query(Message).first()
        ciphertext = row.ciphertext
        
        assert ciphertext != "my secret message"
        assert decrypt(ciphertext) == "my secret message"


# ===========================================================================
# 3. Messaging tests
# ===========================================================================

class TestMessaging:

    @pytest.mark.asyncio
    async def test_send_message_success(self, async_client, register_and_login_async, auth_helper):
        alice_token = await register_and_login_async(async_client, "alice", "secret123")
        await register_and_login_async(async_client, "bob", "secret456")

        response = await async_client.post(
            "/messages",
            json={"content": "hello bob", "recipients": ["bob"]},
            headers=auth_helper(alice_token),
        )
        assert response.status_code == 201
        assert response.json()[0]["content"] == "hello bob"

    @pytest.mark.asyncio
    async def test_user_sees_only_their_messages(self, async_client, register_and_login_async, auth_helper):
        alice_token = await register_and_login_async(async_client, "alice", "secret123")
        bob_token   = await register_and_login_async(async_client, "bob",   "secret456")
        charlie_token = await register_and_login_async(async_client, "charlie", "secret789")

        await async_client.post("/messages", json={"content": "for bob", "recipients": ["bob"]}, headers=auth_helper(alice_token))
        await async_client.post("/messages", json={"content": "for bob again", "recipients": ["bob"]}, headers=auth_helper(charlie_token))
        
        alice_msgs = (await async_client.get("/messages", headers=auth_helper(alice_token))).json()
        assert len(alice_msgs) == 1
        
        bob_msgs = (await async_client.get("/messages", headers=auth_helper(bob_token))).json()
        assert len(bob_msgs) == 2