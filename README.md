# Secure Messenger — Stage 1

A lightweight, secure, and real-time messaging platform built with FastAPI and Python.

## Features

- **End-to-End Encryption (E2EE)**: Messages are encrypted using **AES-256-GCM** before being stored in the database.
- **Secure Authentication**: User passwords are hashed using **Bcrypt**. Session management is handled via **JWT (JSON Web Tokens)**.
- **Real-Time Messaging**: Implements **Server-Sent Events (SSE)** for instant message delivery to connected clients.
- **Interactive CLI Client**: A feature-rich command-line interface for chatting, managing conversations, and viewing history. Supports **multi-user messaging** via comma-separated usernames.
- **Persistent Storage**: Uses **SQLite** with **SQLAlchemy ORM** for reliable data management.

## Tech Stack

- **Backend**: FastAPI, Uvicorn, SQLAlchemy, Pydantic
- **Security**: Cryptography (AES-GCM), Bcrypt, PyJWT
- **Database**: SQLite
- **Client**: Httpx (Async), Asyncio

## Project Structure

```text
.
├── client/
│   ├── client.py       # Main entry point and orchestration
│   ├── logic.py        # Core messaging and auth logic
│   ├── config.py       # Configuration and constants
│   └── __init__.py     # Package initialization
├── server/
│   ├── auth.py         # JWT and password hashing logic
│   ├── broadcaster.py  # SSE event distribution system
│   ├── crypto.py       # AES-256-GCM encryption/decryption
│   ├── main.py         # FastAPI application entry point
│   ├── models.py       # SQLAlchemy database models
│   ├── repository.py   # Database access layer
│   ├── routes.py       # API endpoint handlers
│   ├── schemas.py      # Pydantic models for request/response
│   └── services.py     # Business logic and service layer
├── requirements.txt    # Project dependencies
├── tests/              # Automated test suite
└── README.md           # This file
```

## Getting Started

### 1. Installation

Clone the repository and install the dependencies:

```bash
pip install -r requirements.txt
```

### 2. Running the Server

Start the FastAPI server using Uvicorn:

```bash
uvicorn server.main:app --reload
```

The server will be available at `http://localhost:8000`. You can access the interactive API documentation (Swagger UI) at `http://localhost:8000/docs`.

### 3. Running the Client

Launch the interactive CLI client:

```bash
python client/client.py
```

Follow the prompts to register/login and start chatting!

### 4. Running Tests

To run the automated test suite, use `pytest`:

```bash
pytest tests/ -v
```

This will execute all authentication and messaging tests to ensure everything is working correctly.

## CLI Commands

Inside the interactive chat client, you can use the following commands:

- `/to <user1, user2, ...>`: Switch the conversation to one or more users (separated by commas).
- `/list`: Show full message history with the current partner(s).
- `/help`: Display the help menu.
- `/quit` or `/exit`: Exit the application.

## Security Overview & Design Decisions

A well-layered, secure application requires deliberate technology choices. Below is the architectural rationale behind our core design decisions:

### 1. Password Hashing: Why Bcrypt?
* **The Decision:** We use **Bcrypt** for hashing user passwords rather than fast cryptographic hash algorithms like MD5, SHA-1, or SHA-256.
* **The Rationale:** 
  * MD5 and SHA-256 are designed for speed (hashing gigabytes of data per second). While great for checksums, their speed makes them highly insecure for passwords—an attacker with a cheap GPU can guess billions of combinations per second.
  * Bcrypt is an **intentionally slow algorithm** with an adjustable workload cost factor. Each hash takes ~100ms, making brute-force dictionary attacks computationally infeasible. It also handles cryptographic salt generation automatically, protecting against rainbow table attacks.
  * **Timing Oracle / Username Enumeration Mitigation:** A major security pitfall is timing leakage during `POST /login`—if the username is not found, Uvicorn would normally return instantly (~1ms), whereas a valid username triggers a Bcrypt check and takes ~100ms, exposing whether a username exists. To resolve this timing oracle risk, our server always performs a dummy Bcrypt verification using a placeholder hash whenever the user is not found, ensuring that both failed and successful logins take identical computation times.

### 2. Message Encryption: Why AES-256-GCM?
* **The Decision:** Messages are encrypted at rest in the database using **AES-256** in **Galois/Counter Mode (GCM)** instead of Cipher Block Chaining (CBC).
* **The Rationale:**
  * **Confidentiality + Authenticity (AEAD):** AES-GCM is an Authenticated Encryption with Associated Data (AEAD) cipher. It doesn't just hide the message text; it also appends a 16-byte authentication tag that acts as a secure digital signature.
  * **Tamper Protection:** If anyone tries to manually alter the encrypted database files or inject corrupted blocks, decryption fails immediately with a cryptographic exception instead of silently returning garbage data. This protects against active padding oracle and chosen-ciphertext attacks.
  * **Fresh 12-Byte Nonce:** We generate a unique `os.urandom(12)` nonce for every message. Even if Alice sends the word "hello" 10 times in a row, every stored database blob looks completely different.

### 3. Real-Time Streaming: Why Server-Sent Events (SSE) over WebSockets?
* **The Decision:** We use **Server-Sent Events (SSE)** via FastAPI's `StreamingResponse` for instant message delivery instead of WebSockets.
* **The Rationale:**
  * **HTTP Compatibility:** SSE is a lightweight protocol running entirely over standard HTTP (port 80/443). It easily passes through standard corporate firewalls, reverse proxies, and load balancers without requiring custom WebSocket configuration.
  * **Built-in Reconnection:** The browser-native `EventSource` client has automatic reconnection logic built-in. If the network drops, the browser automatically negotiates a reconnection without writing complex custom JavaScript retries.
  * **Uni-directional Efficiency:** Messaging notifications are primarily a server-to-client feed. Client-to-server operations (sending a message, logging in) are short-lived REST requests which fit perfectly as standard `POST` and `PATCH` calls.

### 4. Configuration & Persistence: What survives server restarts?
To avoid the standard pitfalls of session invalidation and data loss:
* **The Keys:** Both the JWT session signing key and the AES-256 database key are loaded dynamically from environment variables (`MESSENGER_JWT_SECRET` and `MESSENGER_ENCRYPTION_KEY`).
* **The Fallbacks:** If these variables are not set (e.g., during local development), the server writes them securely to local files (`.jwt.key` and `.messenger.key`) with restricted `0600` permissions.
* **The Guarantee:**
  * Because the keys are persistent, **database records remain decryptable** and **user sessions stay active** across server restarts.
  * If the keys were generated purely in-memory at startup, every server reboot would make all old database messages permanently unreadable and log out all active clients.

---

## Production Readiness: Known Trade-offs

For production deployments, the following trade-offs should be addressed:
1. **Single-Instance In-Memory Broadcaster:** The SSE broadcaster currently tracks active subscribers inside an in-memory dictionary. If you scale the FastAPI server horizontally to multiple instances, clients connected to Instance A won't receive messages dispatched on Instance B. In production, this should be backed by a shared pub/sub broker like **Redis**.
2. **Token in URL (`?token=<JWT>`)**: Browser EventSource limits custom headers, requiring the token to be passed as a query parameter for SSE. In a hardened environment, this should be replaced by a short-lived, single-use token or secure HTTP-only cookies.
3. **Local Key Storage:** Local key files are highly convenient for development but insecure in multi-tenant environments. A production environment should source these secrets directly from a specialized secret manager (like AWS Secrets Manager, HashiCorp Vault, or Google Cloud Secret Manager).

