#!/usr/bin/env python3
"""
client.py — Interactive CLI client for the Secure Messenger.

USAGE
  python client.py [--url http://localhost:8000]

WHAT IT DOES
  1. Prompts for your username and password, then registers OR logs in
     (it tries login first; if that fails it offers to register).
  2. Fetches the message history and prints it.
  3. Opens a persistent SSE connection to GET /stream so you see new
     messages the moment they arrive — no polling required.
  4. Reads lines from stdin so you can type  recipient: message  to send.

RUNNING TWO CLIENTS SIDE-BY-SIDE
  Terminal A:  python client.py          (log in as alice)
  Terminal B:  python client.py          (log in as bob)
  Type in A, see it appear instantly in B. That's Server-Sent Events.

DEPENDENCIES
  All dependencies are already in requirements.txt:
    httpx==0.27.0     (async HTTP client)
  No extra packages needed.

KEYBOARD SHORTCUTS
  Ctrl-C   quit
"""

import asyncio
import json
import sys
from datetime import datetime, timezone

import httpx

# ─────────────────────────────────────────────────────────────────────────────
# Colour / terminal helpers
# ─────────────────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
MAGENTA = "\033[95m"
WHITE  = "\033[97m"


def _col(code: str, text: str) -> str:
    return f"{code}{text}{RESET}"


def _ts(iso: str) -> str:
    """Convert ISO-8601 timestamp to a short HH:MM display."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%H:%M")
    except Exception:
        return "??:??"


def _banner() -> None:
    print(_col(CYAN, r"""
  ╔══════════════════════════════════════════╗
  ║   🔐  Secure Messenger  —  CLI Client   ║
  ╚══════════════════════════════════════════╝
"""))


def _prompt(label: str) -> str:
    sys.stdout.write(_col(BOLD, f"  {label}: "))
    sys.stdout.flush()
    return sys.stdin.readline().rstrip("\n")


def _info(msg: str) -> None:
    print(_col(DIM, f"  ℹ  {msg}"))


def _ok(msg: str) -> None:
    print(_col(GREEN, f"  ✔  {msg}"))


def _err(msg: str) -> None:
    print(_col(RED, f"  ✖  {msg}"))


def _print_message(sender: str, recipient: str, content: str,
                   created_at: str, me: str) -> None:
    ts = _ts(created_at)
    if sender == me:
        header = _col(YELLOW, f"  [{ts}] {sender}") + _col(DIM, f"  →  {recipient}")
        body   = _col(WHITE, f"       {content}")
    else:
        header = _col(MAGENTA, f"  [{ts}] {sender}") + _col(DIM, f"  →  {recipient}")
        body   = _col(WHITE, f"       {content}")
    print(header)
    print(body)


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _login(client: httpx.AsyncClient, base: str,
                 username: str, password: str) -> str | None:
    """Return a JWT token string, or None on failure."""
    r = await client.post(f"{base}/login",
                          json={"username": username, "password": password})
    if r.status_code == 200:
        return r.json()["access_token"]
    return None


async def _register(client: httpx.AsyncClient, base: str,
                    username: str, password: str) -> bool:
    r = await client.post(f"{base}/register",
                          json={"username": username, "password": password})
    return r.status_code == 201


# ─────────────────────────────────────────────────────────────────────────────
# Fetch history
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_history(client: httpx.AsyncClient, base: str,
                         token: str, me: str) -> None:
    r = await client.get(f"{base}/messages",
                         headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        _err(f"Could not fetch message history: {r.status_code}")
        return
    messages = r.json()
    if not messages:
        _info("No messages yet.")
        return
    _info(f"─── Message history ({len(messages)}) ───────────────────")
    for msg in messages:
        _print_message(msg["sender"], msg["recipient"],
                       msg["content"], msg["created_at"], me)
    _info("─── End of history ─────────────────────────────")


# ─────────────────────────────────────────────────────────────────────────────
# SSE listener (runs as a background asyncio task)
# ─────────────────────────────────────────────────────────────────────────────

async def _listen_stream(base: str, token: str, me: str,
                          stop_event: asyncio.Event) -> None:
    """
    Connect to GET /stream?token=<JWT> and print each incoming SSE event.

    httpx streams the response body line-by-line via async iteration.
    We manually parse the SSE wire format:
      data: <json payload>\\n
      \\n
    """
    url = f"{base}/stream?token={token}"
    _info("Connecting to live stream…")

    async with httpx.AsyncClient(timeout=None) as stream_client:
        try:
            async with stream_client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    _err(f"Stream returned {resp.status_code}")
                    stop_event.set()
                    return
                _ok("Connected — you will see new messages appear here instantly.\n")
                buffer = ""
                async for chunk in resp.aiter_text():
                    if stop_event.is_set():
                        break
                    buffer += chunk
                    # SSE events are delimited by double newlines
                    while "\n\n" in buffer:
                        event_str, buffer = buffer.split("\n\n", 1)
                        for line in event_str.splitlines():
                            if line.startswith("data:"):
                                payload = line[len("data:"):].strip()
                                try:
                                    msg = json.loads(payload)
                                    _print_message(
                                        msg["sender"], msg["recipient"],
                                        msg["content"], msg["created_at"], me,
                                    )
                                except json.JSONDecodeError:
                                    pass   # ignore malformed events
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as exc:
            if not stop_event.is_set():
                _err(f"Stream disconnected: {exc}")
        finally:
            stop_event.set()


# ─────────────────────────────────────────────────────────────────────────────
# Input loop  (runs as a background asyncio task)
# ─────────────────────────────────────────────────────────────────────────────

async def _input_loop(base: str, token: str, me: str,
                       stop_event: asyncio.Event) -> None:
    """
    Read lines from stdin and send them as messages.

    Format:  recipient: message text
    Example: bob: Hey, are you there?

    Type  /quit  or press Ctrl-C to exit.
    """
    loop = asyncio.get_running_loop()

    print()
    print(_col(CYAN, "  ┌─ How to send a message ─────────────────────────────────┐"))
    print(_col(CYAN, "  │") + "  Type:  " + _col(BOLD, "recipient: your message") + "  then press Enter")
    print(_col(CYAN, "  │") + "  Type:  " + _col(BOLD, "/quit") + "               to exit")
    print(_col(CYAN, "  └─────────────────────────────────────────────────────────┘"))
    print()

    async with httpx.AsyncClient() as send_client:
        while not stop_event.is_set():
            # Read one line without blocking the event loop
            try:
                raw = await loop.run_in_executor(None, sys.stdin.readline)
            except (EOFError, OSError):
                break

            line = raw.strip()

            if not line:
                continue

            if line in ("/quit", "/exit", "/q"):
                stop_event.set()
                break

            # Parse  recipient: message
            if ":" not in line:
                _err("Format: recipient: message   (e.g.  bob: hello)")
                continue

            recipient, _, content = line.partition(":")
            recipient = recipient.strip()
            content   = content.strip()

            if not recipient or not content:
                _err("Recipient and message cannot be empty.")
                continue

            r = await send_client.post(
                f"{base}/messages",
                json={"recipient": recipient, "content": content},
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code == 201:
                # The SSE stream will echo it back; no need to print here
                pass
            else:
                try:
                    detail = r.json().get("detail", r.text)
                except Exception:
                    detail = r.text
                _err(f"Send failed ({r.status_code}): {detail}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Secure Messenger CLI client")
    parser.add_argument("--url", default="http://localhost:8000",
                        metavar="URL", help="Base URL of the server")
    args = parser.parse_args()
    base: str = args.url.rstrip("/")

    _banner()

    # ── Authentication ──────────────────────────────────────────────────────
    async with httpx.AsyncClient() as auth_client:
        username = _prompt("Username")
        password = _prompt("Password")

        token = await _login(auth_client, base, username, password)

        if token is None:
            answer = _prompt(
                f"'{username}' not found or wrong password. Register? [y/N]"
            ).strip().lower()
            if answer == "y":
                ok = await _register(auth_client, base, username, password)
                if not ok:
                    _err("Registration failed (username may already exist).")
                    sys.exit(1)
                _ok(f"Registered as '{username}'.")
                token = await _login(auth_client, base, username, password)
                if token is None:
                    _err("Login after registration failed — this should not happen.")
                    sys.exit(1)
            else:
                _err("Login failed. Exiting.")
                sys.exit(1)

        _ok(f"Logged in as {_col(BOLD, username)}.")

    # ── History ─────────────────────────────────────────────────────────────
    async with httpx.AsyncClient() as hist_client:
        await _fetch_history(hist_client, base, token, username)

    # ── Live chat ────────────────────────────────────────────────────────────
    stop = asyncio.Event()

    listener = asyncio.create_task(
        _listen_stream(base, token, username, stop),
        name="sse-listener",
    )
    sender = asyncio.create_task(
        _input_loop(base, token, username, stop),
        name="input-loop",
    )

    # Wait until either task signals we should stop, or Ctrl-C
    try:
        await asyncio.wait(
            [listener, sender],
            return_when=asyncio.FIRST_COMPLETED,
        )
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        listener.cancel()
        sender.cancel()
        await asyncio.gather(listener, sender, return_exceptions=True)
        print()
        _info("Goodbye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
        print(_col(DIM, "  Interrupted. Goodbye."))
