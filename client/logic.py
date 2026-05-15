import asyncio
import json
import sys
from datetime import datetime, timezone
import httpx
try:
    from .config import (
        RESET, BOLD, DIM, RED, GREEN, YELLOW, CYAN, MAGENTA, WHITE,
        NETWORK_ERRORS, BANNER_TEXT
    )
except ImportError:
    from config import (
        RESET, BOLD, DIM, RED, GREEN, YELLOW, CYAN, MAGENTA, WHITE,
        NETWORK_ERRORS, BANNER_TEXT
    )

class State:
    def __init__(self, recipient: str):
        self.recipient = recipient

def c(code: str, text: str) -> str:
    return f"{code}{text}{RESET}"

def banner() -> None:
    print(c(CYAN, BANNER_TEXT))

def ts(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%H:%M")
    except Exception:
        return "??:??"

def print_message(sender: str, recipient: str, content: str,
                  created_at: str, me: str, msg_id: int | None = None,
                  is_edited: bool = False, is_deleted: bool = False) -> None:
    time_str = ts(created_at)
    mine = sender == me
    colour = YELLOW if mine else MAGENTA
    arrow  = c(DIM, "→")
    
    status_suffix = ""
    if is_deleted:
        status_suffix = c(RED, " [DELETED]")
    elif is_edited:
        status_suffix = c(CYAN, " [EDITED]")

    id_str = f" #{msg_id}" if msg_id is not None else ""
    header = (f"  {c(colour, sender)} {arrow} {c(DIM, recipient)}  "
              f"{c(DIM, time_str)}{c(DIM, id_str)}{status_suffix}")
    
    if is_deleted:
        body = f"    {c(DIM, '(message deleted)')}"
    else:
        body = f"    {c(WHITE, content)}"
    print(f"\r{header}\n{body}")   # \r clears any partial input line

def info(msg: str)  -> None: print(c(DIM,   f"  ℹ  {msg}"))
def ok(msg: str)    -> None: print(c(GREEN,  f"  ✔  {msg}"))
def err(msg: str)   -> None: print(c(RED,    f"  ✖  {msg}"))
def warn(msg: str)  -> None: print(c(YELLOW, f"  ⚠  {msg}"))

def prompt(label: str) -> str:
    sys.stdout.write(c(BOLD, f"  {label}: "))
    sys.stdout.flush()
    return sys.stdin.readline().rstrip("\n")

def show_help(current_recipient: str) -> None:
    print()
    print(c(CYAN,  "  ┌─ Commands ────────────────────────────────────────────┐"))
    print(c(CYAN,  "  │") + f"  Just type a message → sent to "
          + c(BOLD, current_recipient))
    print(c(CYAN,  "  │") + "  " + c(BOLD, "/to <name1, name2, ...>")
          + "   — switch conversation partner(s)")
    print(c(CYAN,  "  │") + "  " + c(BOLD, "/list")
          + "        — show full message history")
    print(c(CYAN,  "  │") + "  " + c(BOLD, "/edit <id> <text>")
          + " — edit a message you sent")
    print(c(CYAN,  "  │") + "  " + c(BOLD, "/delete <id>")
          + "      — delete a message you sent")
    print(c(CYAN,  "  │") + "  " + c(BOLD, "/help")
          + "        — show this help")
    print(c(CYAN,  "  │") + "  " + c(BOLD, "/quit")
          + "        — exit")
    print(c(CYAN,  "  └───────────────────────────────────────────────────────┘"))
    print()

async def login(client: httpx.AsyncClient, base: str,
                username: str, password: str) -> str | None:
    """Return a JWT token on success, or None on wrong credentials / network error."""
    try:
        r = await client.post(f"{base}/login",
                               json={"username": username, "password": password})
        return r.json()["access_token"] if r.status_code == 200 else None
    except NETWORK_ERRORS as exc:
        err(f"Cannot reach server: {exc.__class__.__name__} — is the server running?")
        sys.exit(1)

async def register(client: httpx.AsyncClient, base: str,
                   username: str, password: str) -> str | None:
    """Return None on success, or an error string on failure."""
    try:
        r = await client.post(f"{base}/register",
                               json={"username": username, "password": password})
    except NETWORK_ERRORS as exc:
        err(f"Cannot reach server: {exc.__class__.__name__} — is the server running?")
        sys.exit(1)
    if r.status_code == 201:
        return None
    try:
        body = r.json()
        if "detail" in body:
            detail = body["detail"]
            if isinstance(detail, list):
                msgs = []
                for e in detail:
                    loc  = " → ".join(str(x) for x in e.get("loc", []) if x != "body")
                    msg  = e.get("msg", "invalid")
                    msgs.append(f"{loc}: {msg}" if loc else msg)
                return "; ".join(msgs)
            return str(detail)
    except Exception:
        pass
    return f"Server returned {r.status_code}"

async def fetch_history(client: httpx.AsyncClient, base: str,
                        token: str, me: str,
                        filter_username: str | None = None) -> None:
    r = await client.get(f"{base}/messages",
                         headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        err(f"Could not fetch message history: {r.status_code}")
        return
    messages = r.json()

    if filter_username:
        # Support multiple recipients separated by commas
        targets = {name.strip() for name in filter_username.split(",")}
        messages = [m for m in messages
                    if (m["sender"] == me and m["recipient"] in targets)
                    or (m["recipient"] == me and m["sender"] in targets)]

    if not messages:
        info("No messages yet.")
        return

    label = f"with {filter_username}" if filter_username else "all"
    info(f"─── History ({label}, {len(messages)} messages) ─────────────")
    for msg in messages:
        print_message(msg["sender"], msg["recipient"],
                      msg["content"], msg["created_at"], me,
                      msg_id=msg.get("id"),
                      is_edited=msg.get("updated_at") is not None,
                      is_deleted=msg.get("is_deleted", False))
    info("─── End of history ──────────────────────────────────────")

async def listen_stream(base: str, token: str, me: str,
                         stop: asyncio.Event) -> None:
    url = f"{base}/stream?token={token}"
    info("Connecting to live stream…")

    while not stop.is_set():
        try:
            async with httpx.AsyncClient(timeout=None) as sc:
                async with sc.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        err(f"Stream returned {resp.status_code} — retrying in 5 s…")
                        await asyncio.sleep(5)
                        continue

                    ok("Connected — new messages will appear here instantly.\n")
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
                                        data = json.loads(payload)
                                        event_type = data.get("type", "message")
                                        
                                        if event_type == "presence":
                                            username = data.get("username")
                                            status = data.get("status")
                                            info(f"User {c(BOLD, username)} is now {c(CYAN, status)}")
                                        elif event_type == "edit":
                                            info(f"Message #{data['id']} was edited by {data['sender']}")
                                            print_message(
                                                data["sender"], data["recipient"],
                                                data["content"], data["created_at"],
                                                me, msg_id=data["id"], is_edited=True
                                            )
                                        elif event_type == "delete":
                                            info(f"Message #{data['id']} was deleted by {data['sender']}")
                                            print_message(
                                                data["sender"], data["recipient"],
                                                "", data.get("created_at", "now"),
                                                me, msg_id=data["id"], is_deleted=True
                                            )
                                        else:
                                            # Regular message or unknown event type
                                            print_message(
                                                data["sender"], data["recipient"],
                                                data["content"], data["created_at"],
                                                me, msg_id=data.get("id")
                                            )
                                    except json.JSONDecodeError:
                                        pass

        except (httpx.RemoteProtocolError, httpx.ReadError,
                httpx.ConnectError, httpx.TimeoutException) as exc:
            if stop.is_set():
                return
            warn(f"Stream lost ({exc.__class__.__name__}) — reconnecting in 3 s…")
            await asyncio.sleep(3)

    stop.set()

async def input_loop(base: str, token: str, me: str,
                      state: State, stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    show_help(state.recipient)
    info(f"Currently chatting with: {c(BOLD, state.recipient)}")
    print()

    async with httpx.AsyncClient() as send_client:
        while not stop.is_set():
            sys.stdout.write(
                c(DIM, f"  [{me}→{state.recipient}] ") + c(BOLD, "")
            )
            sys.stdout.flush()

            try:
                raw = await loop.run_in_executor(None, sys.stdin.readline)
            except (EOFError, OSError):
                break

            line = raw.strip()
            if not line:
                continue

            if line.startswith("/"):
                parts = line.split(maxsplit=1)
                cmd   = parts[0].lower()

                if cmd in ("/quit", "/exit", "/q"):
                    stop.set()
                    break

                elif cmd == "/to":
                    if len(parts) < 2 or not parts[1].strip():
                        err("Usage: /to <username1, username2, ...>")
                    else:
                        new_partner = parts[1].strip()
                        state.recipient = new_partner
                        ok(f"Switched — now chatting with {c(BOLD, new_partner)}")
                        info(f"Fetching history with {new_partner}…")
                        await fetch_history(send_client, base, token,
                                             me, filter_username=new_partner)
                        print()

                elif cmd == "/list":
                    partner = parts[1].strip() if len(parts) > 1 else state.recipient
                    await fetch_history(send_client, base, token,
                                         me, filter_username=partner)

                elif cmd == "/help":
                    show_help(state.recipient)

                elif cmd == "/edit":
                    if len(parts) < 2:
                        err("Usage: /edit <id> <new text>")
                    else:
                        edit_parts = parts[1].split(maxsplit=1)
                        if len(edit_parts) < 2:
                            err("Usage: /edit <id> <new text>")
                        else:
                            msg_id, new_text = edit_parts
                            r = await send_client.patch(
                                f"{base}/messages/{msg_id}",
                                json={"content": new_text},
                                headers={"Authorization": f"Bearer {token}"},
                            )
                            if r.status_code == 200:
                                ok(f"Message #{msg_id} updated.")
                            else:
                                err(f"Edit failed ({r.status_code}): {r.text}")

                elif cmd == "/delete":
                    if len(parts) < 2:
                        err("Usage: /delete <id>")
                    else:
                        msg_id = parts[1].strip()
                        r = await send_client.delete(
                            f"{base}/messages/{msg_id}",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        if r.status_code == 200:
                            ok(f"Message #{msg_id} deleted.")
                        else:
                            err(f"Delete failed ({r.status_code}): {r.text}")

                else:
                    err(f"Unknown command '{cmd}'. Type /help for options.")

                continue

            recipients = [r.strip() for r in state.recipient.split(",") if r.strip()]
            if not recipients:
                continue
                
            r = await send_client.post(
                f"{base}/messages",
                json={"recipients": recipients, "content": line},
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code != 201:
                try:
                    detail = r.json().get("detail", r.text)
                except Exception:
                    detail = r.text
                err(f"Send failed ({r.status_code}): {detail}")
