# Stage 1 — The Foundation

## What You Are Building

A secured REST API for private messaging.
By the end of Stage 1, users can register, login, send encrypted messages, and read them back.
No real-time yet — that is Stage 2. Just a solid, secure backend.

---

## The Story of a Message

Imagine a **post office run by a very careful security guard**.

---

### Step 1 — A user registers: `POST /register`

Alice walks in for the first time.
She says: "My name is Alice, my password is `secret123`."

The guard does something important: he **does not write down `secret123`**.
Instead, he runs it through a one-way machine — a **bcrypt hasher** — and writes down the result:
`$2b$12$eImiTXuWVxfM...`

This is a **fingerprint** of the password, not the password itself.
There is no way to reverse it back to `secret123`.
Even the guard cannot read the original password. It is gone.

Alice's record in the database:
```
username:      alice
password_hash: $2b$12$eImiTXuWVxfM...   ← fingerprint only
```

---

### Step 2 — A user logs in: `POST /login`

Alice comes back the next day. She says: "I'm Alice, password `secret123`."

The guard runs `secret123` through the **same one-way machine** and compares
the output to the stored fingerprint. If they match — she's in.

He hands her a **badge (JWT token)**:
```
eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbGljZSIsImV4cCI6...
```

This badge is **signed** — if anyone tampers with it, the signature breaks.
It contains Alice's username and an expiry time, readable but unforgeable.

Alice must show this badge for every future action.
The guard can verify it is genuine **without looking anything up in a database** —
the math of the signature is enough.

---

### Step 3 — A user sends a message: `POST /messages`

Alice shows her badge. It's valid. She writes:
> "To: Bob. Message: Can we meet at 3pm?"

Before filing it, the guard puts it in a **sealed envelope using AES-256-GCM**:
```
ciphertext: aGVsbG8gd29ybGQ...  (unreadable gibberish)
```

This envelope goes into the archive. The guard cannot read it.
A thief who steals the archive cannot read it.
Only someone with the encryption key can open it — and the key never leaves the server's memory.

The database row:
```
sender:     alice
recipient:  bob
ciphertext: aGVsbG8gd29ybGQ...  ← AES encrypted, never plain text
```

---

### Step 4 — A user reads messages: `GET /messages`

Bob shows his badge. The guard pulls his envelopes from the archive,
**opens each one**, and hands Bob the readable letters.
The envelopes go back sealed. The archive is untouched.

Bob sees:
```json
{ "sender": "alice", "content": "Can we meet at 3pm?", ... }
```

---

## The Two Types of Hashing — A Critical Distinction

```
bcrypt (passwords)          AES (messages)
────────────────────────    ────────────────────────────────
ONE-WAY. No reverse.        TWO-WAY. Reversible with the key.
"secret123" → fingerprint   "hello" → locked blob → "hello"
Used to VERIFY identity.    Used to STORE and RETRIEVE data.
The original is gone.       The original is recoverable.
```

This distinction is fundamental. Never mix them up:
- Never encrypt a password (you do not need to recover it, ever)
- Never hash a message (you need to read it back)

---

## What Lives in the Database

| Table    | Column          | What is actually stored        | Can a thief read it?       |
|----------|-----------------|--------------------------------|----------------------------|
| users    | username        | `alice`                        | Yes — but it is not secret |
| users    | password_hash   | `$2b$12$eImiTXuW...`           | No — one-way fingerprint   |
| messages | sender          | `alice`                        | Yes — but it is not secret |
| messages | recipient       | `bob`                          | Yes — but it is not secret |
| messages | ciphertext      | `aGVsbG8gd29ybGQ...`           | No — AES encrypted         |

---

## What the API Exposes to Whom

| Who                        | What they can see                    |
|----------------------------|--------------------------------------|
| Unauthenticated caller     | HTTP 401 or 403. Nothing else.       |
| Authenticated user         | Their own messages, decrypted        |
| Someone who steals the DB  | Fingerprints and gibberish only      |
| Server administrator       | The encryption key (limitation — see Stage 2 discussion) |

---

## AES-GCM in One Paragraph

AES is a **lock**. You give it a key and a message, it gives you a locked box.
GCM is the mechanism that makes the lock **tamper-evident** — if anyone flips
even one bit inside the box, it refuses to open and raises an exception.
Every time you lock a message, a fresh random number (nonce) is generated,
so even identical messages produce completely different locked boxes.
Without the key, the content is indistinguishable from random noise.

---

## Your Files

| File             | Status             | Your job                                    |
|------------------|--------------------|---------------------------------------------|
| `crypto.py`      | Complete — given   | Read it, understand it, use it              |
| `schemas.py`     | Complete — given   | Read it, understand it, use it              |
| `main.py`        | Complete — given   | Read it, understand it, do not change it    |
| `models.py`      | Skeleton           | Define the two database tables              |
| `auth.py`        | Skeleton           | Implement hashing + JWT functions           |
| `routes.py`      | Skeleton           | Implement the four routes                   |
| `tests/test_app.py` | Partial         | Complete the two TODO tests                 |

---

## How to Know You Are Done

Start the server:
```bash
uvicorn server.main:app --reload
```

Open `http://localhost:8000/docs` and complete this sequence without errors:

```
1.  POST /register      { "username": "alice", "password": "secret123" }
                        → 201 Created

2.  POST /register      { "username": "alice", "password": "secret123" }
                        → 400 Bad Request  ("username already taken")

3.  POST /login         { "username": "alice", "password": "secret123" }
                        → 200 OK, token received

4.  GET  /messages      (no token)
                        → 403 Forbidden

5.  GET  /messages      (with fake token)
                        → 401 Unauthorized

6.  POST /messages      { "content": "hello bob", "recipient": "bob" }  (with valid token)
                        → 201 Created, content returned decrypted

7.  GET  /messages      (with valid token)
                        → 200 OK, content is readable plain text

8.  Open messenger.db   → ciphertext column is unreadable gibberish

9.  Run pytest tests/ -v
                        → all tests pass
```

All 9 pass → you are ready for Stage 2.

---

## Stage 2 Preview — What Comes Next

Stage 1 is a REST API: the client asks, the server answers.

Stage 2 adds **real-time broadcasting**. Here is the question it answers:

> If Alice sends a message to Bob, does Bob need to repeatedly ask
> "any new messages?" every few seconds?

No. That would be wasteful and slow. Instead, Bob opens **one persistent
connection** to the server (`GET /stream`) and keeps it open silently.
The moment Alice's message is saved, the server **pushes** it to Bob
through that open connection — instantly, without Bob asking.

This mechanism is called **Server-Sent Events (SSE)**.
Think of it as a radio: you tune in once and receive whatever is broadcast.
You never have to ask "is there a song playing?"

Stage 2 also adds a CLI client (`client.py`) — a Python terminal program
that sends messages and listens to the SSE stream simultaneously,
making the chat feel live with multiple terminals side by side.
