import httpx

# Terminal colors
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

# Default configuration
DEFAULT_BASE_URL = "http://localhost:8000"

# Network-related exceptions to catch
NETWORK_ERRORS = (
    httpx.ReadTimeout,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.RemoteProtocolError,
    httpx.HTTPStatusError,
)

# Display templates
BANNER_TEXT = """
  ╔══════════════════════════════════════════╗
  ║   🔐  Secure Messenger  —  CLI Client   ║
  ╚══════════════════════════════════════════╝
"""
