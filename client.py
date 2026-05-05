#!/usr/bin/env python3
"""
client.py — Interactive CLI client for the Secure Messenger.

USAGE
  python client.py [--url http://localhost:8000]

FLOW
  1. Enter username + password  (register on first run)
  2. Choose who to chat with
  3. Just type your message and hit Enter  — no "recipient:" prefix needed
  4. Commands:
       /to <name>   — switch conversation partner
       /list        — print message history
       /quit        — exit

RUNNING TWO CLIENTS SIDE-BY-SIDE
  Terminal A:  python client.py   (log in as alice, chat with bob)
  Terminal B:  python client.py   (log in as bob,   chat with alice)
  Type in A → message appears instantly in B.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone

import httpx

# ─────────────────────────────────────────────────────────────────────────────
# Terminal colours
# ─────────────────────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RED     = "\033[91m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
CYAN    = "\033[96m"
MAGENTA = "\033[95m"
WHITE   = "\033[97m"
BLUE    = "\033[94m"


def _c(code: str, text: str) -> str:
    return f"{code}{text}{RESET}"


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

def _banner() -> None:
    print(_c(CYAN, """
  ╔══════════════════════════════════════════╗
  ║   🔐  Secure Messenger  —  CLI Client   ║
  ╚══════════════════════════════════════════╝
"""))


def _ts(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%H:%M")
    except Exception:
        return "??:??"


def _print_message(sender: str, recipient: str, content: str,
                   created_at: str, me: str) -> None:
    ts   = _ts(created_at)
    mine = sender == me
    colour = YELLOW if mine else MAGENTA
    arrow  = _c(DIM, "→")
    header = (f"  {_c(colour, sender)} {arrow} {_c(DIM, recipient)}  "
              f"{_c(DIM, ts)}")
    body   = f"    {_c(WHITE, content)}"
    print(f"\r{header}\n{body}")   # \r clears any partial input line


def _info(msg: str)  -> None: print(_c(DIM,   f"  ℹ  {msg}"))
def _ok(msg: str)    -> None: print(_c(GREEN,  f"  ✔  {msg}"))
def _err(msg: str)   -> None: print(_c(RED,    f"  ✖  {msg}"))
def _warn(msg: str)  -> None: print(_c(YELLOW, f"  ⚠  {msg}"))


def _prompt(label: str) -> str:
    sys.stdout.write(_c(BOLD, f"  {label}: "))
    sys.stdout.flush()
    return sys.stdin.readline().rstrip("\n")


def _show_help(current_recipient: str) -> None:
    print()
    print(_c(CYAN,  "  ┌─ Commands ────────────────────────────────────────────┐"))
    print(_c(CYAN,  "  │") + f"  Just type a message → sent to "
          + _c(BOLD, current_recipient))
    print(_c(CYAN,  "  │") + "  " + _c(BOLD, "/to <name>")
          + "   — switch conversation partner")
    print(_c(CYAN,  "  │") + "  " + _c(BOLD, "/list")
          + "        — show full message history")
    print(_c(CYAN,  "  │") + "  " + _c(BOLD, "/help")
          + "        — show this help")
    print(_c(CYAN,  "  │") + "  " + _c(BOLD, "/quit")
          + "        — exit")
    print(_c(CYAN,  "  └───────────────────────────────────────────────────────┘"))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

# All network-related exceptions we want to catch and show cleanly
_NETWORK_ERRORS = (
    httpx.ReadTimeout,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.RemoteProtocolError,
    httpx.HTTPStatusError,
)


async def _login(client: httpx.AsyncClient, base: str,
                 username: str, password: str) -> str | None:
    """Return a JWT token on success, or None on wrong credentials / network error."""
    try:
        r = await client.post(f"{base}/login",
                              json={"username": username, "password": password})
        return r.json()["access_token"] if r.status_code == 200 else None
    except _NETWORK_ERRORS as exc:
        _err(f"Cannot reach server: {exc.__class__.__name__} — is the server running?")
        sys.exit(1)


async def _register(client: httpx.AsyncClient, base: str,
                    username: str, password: str) -> str | None:
    """Return None on success, or an error string on failure."""
    try:
        r = await client.post(f"{base}/register",
                              json={"username": username, "password": password})
    except _NETWORK_ERRORS as exc:
        _err(f"Cannot reach server: {exc.__class__.__name__} — is the server running?")
        sys.exit(1)
    if r.status_code == 201:
        return None
    # Extract a human-readable reason from the server response
    try:
        body = r.json()
        if "detail" in body:
            detail = body["detail"]
            # Pydantic validation errors come as a list
            if isinstance(detail, list):
                msgs = []
                for err in detail:
                    loc  = " → ".join(str(x) for x in err.get("loc", []) if x != "body")
                    msg  = err.get("msg", "invalid")
                    msgs.append(f"{loc}: {msg}" if loc else msg)
                return "; ".join(msgs)
            return str(detail)
    except Exception:
        pass
    return f"Server returned {r.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# Message history
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_history(client: httpx.AsyncClient, base: str,
                         token: str, me: str,
                         filter_username: str | None = None) -> None:
    r = await client.get(f"{base}/messages",
                         headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        _err(f"Could not fetch message history: {r.status_code}")
        return
    messages = r.json()

    if filter_username:
        messages = [m for m in messages
                    if m["sender"] == filter_username
                    or m["recipient"] == filter_username]

    if not messages:
        _info("No messages yet.")
        return

    label = f"with {filter_username}" if filter_username else "all"
    _info(f"─── History ({label}, {len(messages)} messages) ─────────────")
    for msg in messages:
        _print_message(msg["sender"], msg["recipient"],
                       msg["content"], msg["created_at"], me)
    _info("─── End of history ──────────────────────────────────────")


# ─────────────────────────────────────────────────────────────────────────────
# SSE listener — auto-reconnects on disconnect
# ─────────────────────────────────────────────────────────────────────────────

async def _listen_stream(base: str, token: str, me: str,
                          stop: asyncio.Event) -> None:
    url = f"{base}/stream?token={token}"
    _info("Connecting to live stream…")

    while not stop.is_set():
        try:
            async with httpx.AsyncClient(timeout=None) as sc:
                async with sc.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        _err(f"Stream returned {resp.status_code} — retrying in 5 s…")
                        await asyncio.sleep(5)
                        continue

                    _ok("Connected — new messages will appear here instantly.\n")
                    buffer = ""
                    async for chunk in resp.aiter_text():
                        if stop.is_set():
                            return
                        buffer += chunk
                        while "\n\n" in buffer:
                            event_str, buffer = buffer.split("\n\n", 1)
                            for line in event_str.splitlines():
                                if line.startswith("data:"):
                                    payload = line[len("data:"):].strip()
                                    try:
                                        msg = json.loads(payload)
                                        _print_message(
                                            msg["sender"], msg["recipient"],
                                            msg["content"], msg["created_at"],
                                            me,
                                        )
                                    except json.JSONDecodeError:
                                        pass

        except (httpx.RemoteProtocolError, httpx.ReadError,
                httpx.ConnectError, httpx.TimeoutException) as exc:
            if stop.is_set():
                return
            _warn(f"Stream lost ({exc.__class__.__name__}) — reconnecting in 3 s…")
            await asyncio.sleep(3)

    stop.set()


# ─────────────────────────────────────────────────────────────────────────────
# Shared mutable state for current recipient
# ─────────────────────────────────────────────────────────────────────────────

class _State:
    def __init__(self, recipient: str):
        self.recipient = recipient


# ─────────────────────────────────────────────────────────────────────────────
# Input loop
# ─────────────────────────────────────────────────────────────────────────────

async def _input_loop(base: str, token: str, me: str,
                       state: _State, stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    _show_help(state.recipient)
    _info(f"Currently chatting with: {_c(BOLD, state.recipient)}")
    print()

    async with httpx.AsyncClient() as send_client:
        while not stop.is_set():
            # Render a lightweight prompt showing current partner
            sys.stdout.write(
                _c(DIM, f"  [{me}→{state.recipient}] ") + _c(BOLD, "")
            )
            sys.stdout.flush()

            try:
                raw = await loop.run_in_executor(None, sys.stdin.readline)
            except (EOFError, OSError):
                break

            line = raw.strip()
            if not line:
                continue

            # ── Commands ────────────────────────────────────────────────────
            if line.startswith("/"):
                parts = line.split(maxsplit=1)
                cmd   = parts[0].lower()

                if cmd in ("/quit", "/exit", "/q"):
                    stop.set()
                    break

                elif cmd == "/to":
                    if len(parts) < 2 or not parts[1].strip():
                        _err("Usage: /to <username>")
                    else:
                        new_partner = parts[1].strip()
                        state.recipient = new_partner
                        _ok(f"Switched — now chatting with {_c(BOLD, new_partner)}")
                        _info(f"Fetching history with {new_partner}…")
                        await _fetch_history(send_client, base, token,
                                             me, filter_username=new_partner)
                        print()

                elif cmd == "/list":
                    partner = parts[1].strip() if len(parts) > 1 else state.recipient
                    await _fetch_history(send_client, base, token,
                                         me, filter_username=partner)

                elif cmd == "/help":
                    _show_help(state.recipient)

                else:
                    _err(f"Unknown command '{cmd}'. Type /help for options.")

                continue

            # ── Send plain message to current recipient ──────────────────────
            r = await send_client.post(
                f"{base}/messages",
                json={"recipient": state.recipient, "content": line},
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code != 201:
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

    # ── Auth ────────────────────────────────────────────────────────────────
    # 30 s timeout: bcrypt password hashing can take a few seconds server-side
    async with httpx.AsyncClient(timeout=30.0) as auth_client:
        username = _prompt("Username")
        password = _prompt("Password")

        token = await _login(auth_client, base, username, password)

        if token is None:
            answer = _prompt(
                f"'{username}' not found or wrong password. Register? [y/N]"
            ).strip().lower()
            if answer != "y":
                _err("Login failed. Exiting.")
                sys.exit(1)

            # Re-prompt until registration succeeds
            while True:
                err = await _register(auth_client, base, username, password)
                if err is None:
                    break
                _err(f"Registration failed: {err}")
                _info("Please try again (username ≥ 3 chars, password ≥ 6 chars).")
                username = _prompt("Username").strip()
                password = _prompt("Password").strip()

            _ok(f"Registered as '{username}'.")
            token = await _login(auth_client, base, username, password)
            if token is None:
                _err("Login after registration failed.")
                sys.exit(1)

        _ok(f"Logged in as {_c(BOLD, username)}.")

    # ── Choose conversation partner ──────────────────────────────────────────
    print()
    recipient = _prompt("Chat with (username)").strip()
    while not recipient:
        _err("Please enter a username.")
        recipient = _prompt("Chat with (username)").strip()

    state = _State(recipient)

    # ── History for this conversation ────────────────────────────────────────
    async with httpx.AsyncClient() as hist_client:
        await _fetch_history(hist_client, base, token, username,
                             filter_username=recipient)

    # ── Start live chat ──────────────────────────────────────────────────────
    stop = asyncio.Event()

    listener = asyncio.create_task(
        _listen_stream(base, token, username, stop),
        name="sse-listener",
    )
    sender = asyncio.create_task(
        _input_loop(base, token, username, state, stop),
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
        _info("Goodbye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
        print(_c(DIM, "  Interrupted. Goodbye."))
