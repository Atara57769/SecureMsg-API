import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_duplicate_login_invalidates_old_token(async_client: AsyncClient, auth_helper):
    # 1. Register a user
    await async_client.post("/register", json={"username": "alice", "password": "secret123"})
    
    # 2. Login the first time -> Token 1
    resp1 = await async_client.post("/login", json={"username": "alice", "password": "secret123"})
    token1 = resp1.json()["access_token"]
    
    # Verify Token 1 works
    resp_verify1 = await async_client.get("/messages", headers=auth_helper(token1))
    assert resp_verify1.status_code == 200
    
    # 3. Login a second time -> Token 2
    resp2 = await async_client.post("/login", json={"username": "alice", "password": "secret123"})
    token2 = resp2.json()["access_token"]
    
    # Verify Token 2 works
    resp_verify2 = await async_client.get("/messages", headers=auth_helper(token2))
    assert resp_verify2.status_code == 200
    
    # 4. Attempt to use Token 1 again -> Should be 401
    resp_old = await async_client.get("/messages", headers=auth_helper(token1))
    assert resp_old.status_code == 401
    assert resp_old.json()["detail"] == "Session invalidated (logged in elsewhere)"

@pytest.mark.asyncio
async def test_sse_stream_invalidated_on_relogin(async_client: AsyncClient):
    # 1. Register and login
    await async_client.post("/register", json={"username": "bob", "password": "secret123"})
    resp1 = await async_client.post("/login", json={"username": "bob", "password": "secret123"})
    token1 = resp1.json()["access_token"]
    
    # 2. Login again to invalidate Token 1
    await async_client.post("/login", json={"username": "bob", "password": "secret123"})
    
    # 3. Token 1 should now fail for new stream connections
    # We use a regular GET because it should return 401 immediately
    response = await async_client.get(f"/stream?token={token1}")
    assert response.status_code == 401
    assert response.json()["detail"] == "Session invalidated (logged in elsewhere)"

