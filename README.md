# Secure Messenger — Stage 1

A lightweight, secure, and real-time messaging platform built with FastAPI and Python.

## Features

- **End-to-End Encryption (E2EE)**: Messages are encrypted using **AES-256-GCM** before being stored in the database.
- **Secure Authentication**: User passwords are hashed using **Bcrypt**. Session management is handled via **JWT (JSON Web Tokens)**.
- **Real-Time Messaging**: Implements **Server-Sent Events (SSE)** for instant message delivery to connected clients.
- **Interactive CLI Client**: A feature-rich command-line interface for chatting, managing conversations, and viewing history.
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

- `/to <username>`: Switch the conversation to a different user.
- `/list`: Show full message history with the current partner.
- `/help`: Display the help menu.
- `/quit` or `/exit`: Exit the application.

## Security Overview

### Message Encryption
Each message is encrypted using **AES-256 in GCM mode**. A unique 12-byte nonce is generated for every message, ensuring that identical messages produce different ciphertexts. The server-wide encryption key is stored in `.messenger.key` (generated automatically on first run).

### Authentication
Passwords are never stored in plain text. They are hashed using **Bcrypt** with a salt. Authentication is stateless using **JWTs**, which are required for sending/receiving messages and connecting to the live stream.
