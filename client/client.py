#!/usr/bin/env python3
import asyncio
import sys
import argparse
import httpx
try:
    from .config import DEFAULT_BASE_URL, BOLD, DIM
    from .logic import (
        banner, prompt, login, register, ok, err, info, c, State,
        fetch_history, listen_stream, input_loop
    )
except ImportError:
    from config import DEFAULT_BASE_URL, BOLD, DIM
    from logic import (
        banner, prompt, login, register, ok, err, info, c, State,
        fetch_history, listen_stream, input_loop
    )

async def main() -> None:
    parser = argparse.ArgumentParser(description="Secure Messenger CLI client")
    parser.add_argument("--url", default=DEFAULT_BASE_URL,
                        metavar="URL", help="Base URL of the server")
    args = parser.parse_args()
    base: str = args.url.rstrip("/")

    banner()

    # ── Auth ────────────────────────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=30.0) as auth_client:
        username = prompt("Username")
        password = prompt("Password")

        token = await login(auth_client, base, username, password)

        if token is None:
            answer = prompt(
                f"'{username}' not found or wrong password. Register? [y/N]"
            ).strip().lower()
            if answer != "y":
                err("Login failed. Exiting.")
                sys.exit(1)

            while True:
                registration_error = await register(auth_client, base, username, password)
                if registration_error is None:
                    break
                err(f"Registration failed: {registration_error}")
                info("Please try again (username ≥ 3 chars, password ≥ 6 chars).")
                username = prompt("Username").strip()
                password = prompt("Password").strip()

            ok(f"Registered as '{username}'.")
            token = await login(auth_client, base, username, password)
            if token is None:
                err("Login after registration failed.")
                sys.exit(1)

        ok(f"Logged in as {c(BOLD, username)}.")

    # ── Choose conversation partner ──────────────────────────────────────────
    print()
    recipient = prompt("Chat with (username)").strip()
    while not recipient:
        err("Please enter a username.")
        recipient = prompt("Chat with (username)").strip()

    state = State(recipient)

    # ── History for this conversation ────────────────────────────────────────
    async with httpx.AsyncClient() as hist_client:
        await fetch_history(hist_client, base, token, username,
                             filter_username=recipient)

    # ── Start live chat ──────────────────────────────────────────────────────
    stop = asyncio.Event()

    listener = asyncio.create_task(
        listen_stream(base, token, username, stop),
        name="sse-listener",
    )
    sender = asyncio.create_task(
        input_loop(base, token, username, state, stop),
        name="input-loop",
    )

    try:
        await asyncio.wait([listener, sender],
                           return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        listener.cancel()
        sender.cancel()
        await asyncio.gather(listener, sender, return_exceptions=True)
        print()
        info("Goodbye.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
        print(c(DIM, "  Interrupted. Goodbye."))
