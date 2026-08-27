"""
Kiro Refresh Token Bulk Import to 9router

Import refresh token yang sudah di-generate oleh kiro.py ke 9router.

Input:  refresh_tokens.txt (format: refreshToken per baris)
Output: Inject ke 9router via POST /api/oauth/kiro/import
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# Force UTF-8
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── Config ──────────────────────────────────────────────
DEFAULT_ROUTER_URL = "http://localhost:20128"
DEFAULT_INPUT_FILE = "refresh_tokens.txt"


# ── Print helpers ───────────────────────────────────────
def ok(text):
    print(f"  [+]  {text}")


def fail(text):
    print(f"  [x]  {text}")


def info(text):
    print(f"  >  {text}")


def rule(char="=", width=50):
    print(f"  {char * width}")


# ── 9router Auth ────────────────────────────────────────
_auth_token: Optional[str] = None


def router_login(router_url: str, password: str) -> str:
    """Login ke 9router, return auth_token cookie."""
    global _auth_token
    if _auth_token:
        return _auth_token

    login_url = f"{router_url.rstrip('/')}/api/auth/login"
    body = json.dumps({"password": password}).encode("utf-8")
    req = urllib.request.Request(
        login_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "KiroImporter/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            for header in resp.headers.get_all("Set-Cookie") or []:
                if header.startswith("auth_token="):
                    token = header.split(";")[0].split("=", 1)[1]
                    _auth_token = token
                    return token
    except Exception as e:
        raise RuntimeError(f"Login 9router gagal: {e}")
    raise RuntimeError("Login 9router gagal: auth_token tidak ditemukan")


# ── Import Refresh Token ────────────────────────────────
def import_refresh_token(
    router_url: str,
    refresh_token: str,
) -> dict:
    """
    Import satu refresh token ke 9router via POST /api/oauth/kiro/import
    """
    global _auth_token

    import_url = f"{router_url.rstrip('/')}/api/oauth/kiro/import"
    payload = {"refreshToken": refresh_token.strip()}
    body = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "KiroImporter/1.0",
    }
    if _auth_token:
        headers["Cookie"] = f"auth_token={_auth_token}"

    req = urllib.request.Request(
        import_url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return {"success": True, "data": data}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            error_data = json.loads(error_body)
            error_msg = error_data.get("error", error_body)
        except Exception:
            error_msg = error_body
        return {"success": False, "error": f"HTTP {e.code}: {error_msg}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── File Reader ─────────────────────────────────────────
def read_tokens(file_path: str) -> list:
    """
    Baca refresh token dari file.
    Format: refreshToken (satu per baris)
    """
    tokens = []
    if not os.path.exists(file_path):
        return tokens

    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("aorAAAAAG"):
                tokens.append(line)
                continue
            print(f"  [!]  Line {line_num}: format tidak dikenali, skip")

    return tokens


# ── Duplicate Check ─────────────────────────────────────
def get_existing_connections(router_url: str) -> list:
    """Ambil daftar koneksi yang ada di 9router."""
    global _auth_token

    providers_url = f"{router_url.rstrip('/')}/api/providers"
    headers = {"User-Agent": "KiroImporter/1.0"}
    if _auth_token:
        headers["Cookie"] = f"auth_token={_auth_token}"

    req = urllib.request.Request(providers_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("connections", [])
    except Exception:
        return []


# ── Main ────────────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Bulk import Kiro Refresh Tokens ke 9router",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kiro_import.py                           # Default: refresh_tokens.txt
  python kiro_import.py tokens.txt                # Custom file
  python kiro_import.py tokens.txt 4              # 4 workers paralel
  python kiro_import.py tokens.txt 2 -p MyPass    # Dengan password 9router
  python kiro_import.py tokens.txt --url http://192.168.1.100:20128
        """,
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=DEFAULT_INPUT_FILE,
        help=f"File input (default: {DEFAULT_INPUT_FILE})",
    )
    parser.add_argument(
        "workers",
        nargs="?",
        type=int,
        default=2,
        help="Jumlah worker paralel (default: 2)",
    )
    parser.add_argument(
        "-p", "--password",
        type=str,
        default=None,
        help="Password 9router (opsional)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=DEFAULT_ROUTER_URL,
        help=f"URL 9router (default: {DEFAULT_ROUTER_URL})",
    )

    args = parser.parse_args()

    # Banner
    print()
    rule()
    print("  Kiro Refresh Token Bulk Import to 9router")
    rule()
    print()

    # Resolve file path
    file_path = args.file
    if not os.path.isabs(file_path):
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path)

    info(f"File    : {file_path}")
    info(f"9router : {args.url}")
    info(f"Workers : {args.workers}")
    print()

    # Baca tokens
    tokens = read_tokens(file_path)
    if not tokens:
        fail(f"Tidak ada token valid di {file_path}")
        return

    info(f"Total token ditemukan: {len(tokens)}")

    # Login jika ada password
    if args.password:
        try:
            router_login(args.url, args.password)
            info("Login 9router berhasil")
        except RuntimeError as e:
            fail(str(e))
            return

    # Cek duplikat
    existing = get_existing_connections(args.url)
    existing_refresh = set()
    for conn in existing:
        if conn.get("provider") == "kiro" and conn.get("refreshToken"):
            existing_refresh.add(conn["refreshToken"])

    original_count = len(tokens)
    tokens = [t for t in tokens if t not in existing_refresh]
    skipped = original_count - len(tokens)
    if skipped > 0:
        info(f"Skip duplikat: {skipped}")

    if not tokens:
        ok("Semua token sudah ada di 9router!")
        return

    info(f"Token yang akan diimport: {len(tokens)}")
    print()
    rule("-")

    # Import dengan multi-worker
    results = {"success": 0, "failed": 0, "errors": []}
    import threading
    lock = threading.Lock()

    def import_one(token):
        display = token[:30] + "..."
        result = import_refresh_token(args.url, token)
        return (display, result)

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(import_one, token): token for token in tokens}
        for future in as_completed(futures):
            display, result = future.result()
            with lock:
                if result["success"]:
                    results["success"] += 1
                    ok(f"Imported: {display}")
                else:
                    results["failed"] += 1
                    err_msg = result.get("error", "unknown")
                    results["errors"].append(f"{display}: {err_msg}")
                    fail(f"Gagal: {display} - {err_msg}")

    elapsed = time.time() - start_time

    # Ringkasan
    print()
    rule()
    print("  RINGKASAN")
    rule()
    print()
    print(f"  Total token : {len(tokens) + skipped}")
    print(f"  Berhasil    : {results['success']}")
    print(f"  Gagal       : {results['failed']}")
    if skipped > 0:
        print(f"  Skip duplikat: {skipped}")
    print(f"  Waktu       : {elapsed:.1f}s")
    print()

    if results["errors"]:
        print("  Error detail:")
        for err in results["errors"][:10]:
            print(f"    - {err}")
        if len(results["errors"]) > 10:
            print(f"    ... dan {len(results['errors']) - 10} error lainnya")
        print()

    rule()
    print("  SELESAI")
    rule()
    print()


if __name__ == "__main__":
    main()
