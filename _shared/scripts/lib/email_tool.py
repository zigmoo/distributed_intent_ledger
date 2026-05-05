#!/usr/bin/env python3
"""email_tool — agent-friendly email operations via himalaya CLI.

Subcommands:
    list    [--account NAME] [--folder NAME] [--page N] [--page-size N] [--json]
    read    <id> [--account NAME] [--json]
    search  <query> [--account NAME] [--folder NAME] [--page-size N]
    send    --to ADDR --subject SUBJ [--body TEXT | --body-file PATH] [--account NAME] [--cc ADDR] [--bcc ADDR]
    reply   <id> [--body TEXT | --body-file PATH] [--account NAME] [--all]
    forward <id> --to ADDR [--body TEXT | --body-file PATH] [--account NAME]
    delete  <id> [--account NAME] [--folder NAME]
    move    <id> --to-folder NAME [--account NAME] [--folder NAME]
    flag    <id> --add|--remove FLAG [--account NAME] [--folder NAME]
    folders [--account NAME]
    accounts
    check   [--account NAME]
    setup   [account-name] [--status]
    refresh [account-name]

Output conventions:
    Pipe-delimited status line on send/reply/forward/delete/move/flag:
        OK | action | target | detail
        ERR | action | target | error message

Handles OAuth2 token refresh automatically before send/reply/forward AND read operations.
Uses himalaya for IMAP/SMTP, vanilla Python stdlib for token refresh.
"""

import subprocess
import sys
import json
import urllib.request
import urllib.parse
import os
import re
import hashlib
import base64
import secrets
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler


HIMALAYA_CONFIG = os.path.expanduser("~/.config/himalaya/config.toml")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.path.join(SCRIPT_DIR, "email_accounts.json")


def load_accounts_registry():
    with open(ACCOUNTS_FILE) as f:
        return json.load(f)


def run_himalaya(args, quiet=False, stdin_data=None):
    cmd = ["himalaya"] + args
    if quiet:
        cmd.insert(1, "--quiet")
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def clean_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*m', '', text).strip()


def get_keyring_secret(username):
    result = subprocess.run(
        ["secret-tool", "lookup",
         "service", "himalaya-cli",
         "username", username,
         "application", "rust-keyring"],
        capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def set_keyring_secret(username, value, label=None):
    if label is None:
        label = f"{username}@himalaya-cli:default (keyring v3.6.3)"
    subprocess.run(
        ["secret-tool", "store",
         "--label", label,
         "service", "himalaya-cli",
         "username", username,
         "application", "rust-keyring",
         "target", "default"],
        input=value, text=True, capture_output=True
    )


def read_config_field(account_name, field):
    try:
        in_account = False
        with open(HIMALAYA_CONFIG) as f:
            for line in f:
                stripped = line.strip()
                if stripped == f"[accounts.{account_name}]":
                    in_account = True
                elif stripped.startswith("[accounts.") and in_account:
                    break
                elif in_account and stripped.startswith(f"{field}"):
                    return stripped.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    return None


def get_from_addr(account_name):
    return read_config_field(account_name, "email") or f"{account_name}@gmail.com"


def get_client_id(account_name=None):
    try:
        with open(HIMALAYA_CONFIG) as f:
            for line in f:
                if "client-id" in line and "=" in line:
                    return line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    return None


def get_token_url(account_name=None):
    """Read OAuth2 token URL from config for the account's provider."""
    try:
        registry = load_accounts_registry()
        for acct in registry["accounts"]:
            if acct["name"] == account_name:
                provider = registry["providers"].get(acct["provider"], {})
                return provider.get("token_url")
    except (FileNotFoundError, KeyError):
        pass
    return "https://www.googleapis.com/oauth2/v3/token"


def refresh_oauth2_token(account_prefix, account_name=None):
    client_secret = get_keyring_secret(f"{account_prefix}-oauth2-client-secret")
    refresh_token = get_keyring_secret(f"{account_prefix}-oauth2-refresh-token")

    if not client_secret or not refresh_token:
        return False, "Missing client secret or refresh token in keyring"

    client_id_value = get_client_id()
    if not client_id_value:
        return False, "Could not find client-id in config"

    token_url = get_token_url(account_name)

    data = urllib.parse.urlencode({
        "client_id": client_id_value,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()

    req = urllib.request.Request(
        token_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode())
            new_access_token = body.get("access_token")
            if not new_access_token:
                return False, f"No access_token in response: {body}"
            set_keyring_secret(f"{account_prefix}-oauth2-access-token", new_access_token)
            return True, "Token refreshed"
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        return False, f"Token refresh failed ({e.code}): {error_body}"


def ensure_smtp_token(account_name):
    ok, msg = refresh_oauth2_token(f"{account_name}-smtp", account_name)
    if not ok:
        print(f"Warning: SMTP token refresh failed: {msg}", file=sys.stderr)
    return ok


def ensure_imap_token(account_name):
    ok, msg = refresh_oauth2_token(f"{account_name}-imap", account_name)
    if not ok:
        print(f"Warning: IMAP token refresh failed: {msg}", file=sys.stderr)
    return ok


def build_mime(from_addr, to_addr, subject, body, cc=None, bcc=None):
    headers = [
        f"From: {from_addr}",
        f"To: {to_addr}",
        f"Subject: {subject}",
    ]
    if cc:
        headers.append(f"Cc: {cc}")
    if bcc:
        headers.append(f"Bcc: {bcc}")
    headers.extend([
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
    ])
    return "\n".join(headers) + "\n\n" + body


def send_raw(raw_message, account=None):
    cmd = ["himalaya", "message", "send", "--quiet"]
    if account:
        cmd.extend(["--account", account])
    return subprocess.run(cmd, input=raw_message, capture_output=True, text=True)


def parse_arg(args, flag):
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            return args[i + 1]
    return None


def has_flag(args, flag):
    return flag in args


def get_account(args):
    return parse_arg(args, "--account")


def get_account_name(args):
    return get_account(args) or "maintainer"


# --- COMMANDS ---

def cmd_list(args):
    account_name = get_account_name(args)
    ensure_imap_token(account_name)
    hargs = ["envelope", "list"]
    hargs.extend(args)
    rc, out, err = run_himalaya(hargs)
    if out:
        print(out, end="")
    if rc != 0 and err:
        print(clean_ansi(err), file=sys.stderr)
    return rc


def cmd_read(args):
    if not args or args[0].startswith("-"):
        print("Usage: email_tool read <message-id> [--account NAME]", file=sys.stderr)
        return 1
    account_name = get_account_name(args)
    ensure_imap_token(account_name)
    hargs = ["message", "read"]
    hargs.extend(args)
    rc, out, err = run_himalaya(hargs)
    if out:
        print(out, end="")
    if rc != 0 and err:
        print(clean_ansi(err), file=sys.stderr)
    return rc


def cmd_search(args):
    if not args or args[0].startswith("-"):
        print("Usage: email_tool search <query> [--account NAME] [--folder NAME] [--page-size N]", file=sys.stderr)
        return 1
    query = args[0]
    remaining = args[1:]

    account_name = get_account_name(remaining)
    ensure_imap_token(account_name)

    page_size = parse_arg(remaining, "--page-size") or "100"
    hargs = ["envelope", "list", "--page-size", page_size]
    account = parse_arg(remaining, "--account")
    folder = parse_arg(remaining, "--folder")
    if account:
        hargs.extend(["--account", account])
    if folder:
        hargs.extend(["--folder", folder])

    rc, out, err = run_himalaya(hargs)
    if rc != 0:
        print(clean_ansi(err), file=sys.stderr)
        return rc

    lines = out.strip().split("\n")
    if len(lines) < 3:
        print("No results.")
        return 0
    print(lines[0])
    print(lines[1])
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    matches = [line for line in lines[2:] if pattern.search(line)]
    if matches:
        for line in matches:
            print(line)
    else:
        print("No matching messages.")
    return 0


def cmd_send(args):
    to_addr = parse_arg(args, "--to")
    subject = parse_arg(args, "--subject")
    body = parse_arg(args, "--body")
    body_file = parse_arg(args, "--body-file")
    cc = parse_arg(args, "--cc")
    bcc = parse_arg(args, "--bcc")
    account = get_account(args)
    account_name = account or "maintainer"

    if not to_addr or not subject:
        print("Usage: email_tool send --to ADDR --subject SUBJ [--body TEXT | --body-file PATH] [--cc ADDR] [--bcc ADDR] [--account NAME]", file=sys.stderr)
        return 1

    if body_file:
        with open(body_file) as f:
            body = f.read()
    if body is None:
        if not sys.stdin.isatty():
            body = sys.stdin.read()
        else:
            body = ""

    from_addr = get_from_addr(account_name)
    ensure_smtp_token(account_name)

    raw = build_mime(from_addr, to_addr, subject, body, cc=cc, bcc=bcc)
    result = send_raw(raw, account=account)

    if result.returncode == 0:
        print(f"OK | sent | {to_addr} | {subject}")
    else:
        print(f"ERR | send_failed | {to_addr} | {clean_ansi(result.stderr)}", file=sys.stderr)
    return result.returncode


def cmd_reply(args):
    if not args or args[0].startswith("-"):
        print("Usage: email_tool reply <id> --body TEXT [--body-file PATH] [--account NAME] [--all]", file=sys.stderr)
        return 1

    msg_id = args[0]
    remaining = args[1:]
    body = parse_arg(remaining, "--body")
    body_file = parse_arg(remaining, "--body-file")
    account = parse_arg(remaining, "--account")
    reply_all = has_flag(remaining, "--all")
    account_name = account or "maintainer"

    if body_file:
        with open(body_file) as f:
            body = f.read()
    if body is None and not sys.stdin.isatty():
        body = sys.stdin.read()
    if not body:
        print("Usage: email_tool reply <id> --body TEXT or --body-file PATH or pipe via stdin", file=sys.stderr)
        return 1

    ensure_imap_token(account_name)

    hargs = ["message", "read"]
    if account:
        hargs.extend(["--account", account])
    hargs.append(msg_id)
    rc, out, err = run_himalaya(hargs)
    if rc != 0:
        print(f"ERR | reply_failed | {msg_id} | Could not read original message", file=sys.stderr)
        return rc

    orig_from = None
    orig_subject = None
    orig_to = None
    orig_cc = None
    for line in out.split("\n"):
        if line.startswith("From:") and not orig_from:
            orig_from = line[5:].strip()
        elif line.startswith("Subject:") and not orig_subject:
            orig_subject = line[8:].strip()
        elif line.startswith("To:") and not orig_to:
            orig_to = line[3:].strip()
        elif line.startswith("Cc:") and not orig_cc:
            orig_cc = line[3:].strip()

    if not orig_from:
        print(f"ERR | reply_failed | {msg_id} | Could not parse From header", file=sys.stderr)
        return 1

    reply_subject = orig_subject or ""
    if not reply_subject.lower().startswith("re:"):
        reply_subject = f"Re: {reply_subject}"

    to_addr = orig_from
    email_match = re.search(r'<([^>]+)>', to_addr)
    if email_match:
        to_addr = email_match.group(1)

    from_addr = get_from_addr(account_name)
    ensure_smtp_token(account_name)

    cc_addr = None
    if reply_all and orig_cc:
        cc_addr = orig_cc

    raw = build_mime(from_addr, to_addr, reply_subject, body, cc=cc_addr)
    result = send_raw(raw, account=account)

    if result.returncode == 0:
        print(f"OK | replied | {to_addr} | {reply_subject}")
    else:
        print(f"ERR | reply_failed | {to_addr} | {clean_ansi(result.stderr)}", file=sys.stderr)
    return result.returncode


def cmd_forward(args):
    if not args or args[0].startswith("-"):
        print("Usage: email_tool forward <id> --to ADDR [--body TEXT | --body-file PATH] [--account NAME]", file=sys.stderr)
        return 1

    msg_id = args[0]
    remaining = args[1:]
    to_addr = parse_arg(remaining, "--to")
    body = parse_arg(remaining, "--body")
    body_file = parse_arg(remaining, "--body-file")
    account = parse_arg(remaining, "--account")
    account_name = account or "maintainer"

    if not to_addr:
        print("Usage: email_tool forward <id> --to ADDR", file=sys.stderr)
        return 1

    ensure_imap_token(account_name)

    hargs = ["message", "read"]
    if account:
        hargs.extend(["--account", account])
    hargs.append(msg_id)
    rc, out, err = run_himalaya(hargs)
    if rc != 0:
        print(f"ERR | forward_failed | {msg_id} | Could not read original message", file=sys.stderr)
        return rc

    orig_subject = None
    orig_from = None
    body_start = False
    orig_body_lines = []
    for line in out.split("\n"):
        if body_start:
            orig_body_lines.append(line)
        elif line.startswith("Subject:") and not orig_subject:
            orig_subject = line[8:].strip()
        elif line.startswith("From:") and not orig_from:
            orig_from = line[5:].strip()
        elif line == "":
            body_start = True

    fwd_subject = f"Fwd: {orig_subject}" if orig_subject else "Fwd:"

    if body_file:
        with open(body_file) as f:
            body = f.read()

    fwd_body = ""
    if body:
        fwd_body = body + "\n\n"
    fwd_body += f"---------- Forwarded message ----------\n"
    fwd_body += f"From: {orig_from}\n"
    fwd_body += f"Subject: {orig_subject}\n\n"
    fwd_body += "\n".join(orig_body_lines)

    from_addr = get_from_addr(account_name)
    ensure_smtp_token(account_name)

    raw = build_mime(from_addr, to_addr, fwd_subject, fwd_body)
    result = send_raw(raw, account=account)

    if result.returncode == 0:
        print(f"OK | forwarded | {to_addr} | {fwd_subject}")
    else:
        print(f"ERR | forward_failed | {to_addr} | {clean_ansi(result.stderr)}", file=sys.stderr)
    return result.returncode


def cmd_delete(args):
    if not args or args[0].startswith("-"):
        print("Usage: email_tool delete <id> [--account NAME] [--folder NAME]", file=sys.stderr)
        return 1

    msg_id = args[0]
    remaining = args[1:]
    hargs = ["message", "delete"]
    account = parse_arg(remaining, "--account")
    folder = parse_arg(remaining, "--folder")
    if account:
        hargs.extend(["--account", account])
    if folder:
        hargs.extend(["--folder", folder])
    hargs.append(msg_id)

    rc, out, err = run_himalaya(hargs)
    if rc == 0:
        print(f"OK | deleted | {msg_id}")
    else:
        print(f"ERR | delete_failed | {msg_id} | {clean_ansi(err)}", file=sys.stderr)
    return rc


def cmd_move(args):
    if not args or args[0].startswith("-"):
        print("Usage: email_tool move <id> --to-folder NAME [--account NAME] [--folder NAME]", file=sys.stderr)
        return 1

    msg_id = args[0]
    remaining = args[1:]
    to_folder = parse_arg(remaining, "--to-folder")
    account = parse_arg(remaining, "--account")
    folder = parse_arg(remaining, "--folder")

    if not to_folder:
        print("Usage: email_tool move <id> --to-folder NAME", file=sys.stderr)
        return 1

    hargs = ["message", "move"]
    if account:
        hargs.extend(["--account", account])
    if folder:
        hargs.extend(["--folder", folder])
    hargs.extend([msg_id, to_folder])

    rc, out, err = run_himalaya(hargs)
    if rc == 0:
        print(f"OK | moved | {msg_id} | {to_folder}")
    else:
        print(f"ERR | move_failed | {msg_id} | {clean_ansi(err)}", file=sys.stderr)
    return rc


def cmd_flag(args):
    if not args or args[0].startswith("-"):
        print("Usage: email_tool flag <id> --add|--remove FLAG [--account NAME] [--folder NAME]", file=sys.stderr)
        return 1

    msg_id = args[0]
    remaining = args[1:]
    add_flag = parse_arg(remaining, "--add")
    remove_flag = parse_arg(remaining, "--remove")
    account = parse_arg(remaining, "--account")
    folder = parse_arg(remaining, "--folder")

    if not add_flag and not remove_flag:
        print("Usage: email_tool flag <id> --add FLAG or --remove FLAG", file=sys.stderr)
        return 1

    if add_flag:
        hargs = ["flag", "add"]
        flag_value = add_flag
        action = "flagged"
    else:
        hargs = ["flag", "remove"]
        flag_value = remove_flag
        action = "unflagged"

    if account:
        hargs.extend(["--account", account])
    if folder:
        hargs.extend(["--folder", folder])
    hargs.extend([msg_id, flag_value])

    rc, out, err = run_himalaya(hargs)
    if rc == 0:
        print(f"OK | {action} | {msg_id} | {flag_value}")
    else:
        print(f"ERR | flag_failed | {msg_id} | {clean_ansi(err)}", file=sys.stderr)
    return rc


def cmd_folders(args):
    account_name = get_account_name(args)
    ensure_imap_token(account_name)
    hargs = ["folder", "list"]
    hargs.extend(args)
    rc, out, err = run_himalaya(hargs)
    if out:
        print(out, end="")
    if rc != 0 and err:
        print(clean_ansi(err), file=sys.stderr)
    return rc


def cmd_accounts(args):
    rc, out, err = run_himalaya(["account", "list"])
    if out:
        print(out, end="")
    if rc != 0 and err:
        print(clean_ansi(err), file=sys.stderr)
    return rc


def cmd_check(args):
    account = get_account(args)
    account_name = account or "maintainer"
    ensure_imap_token(account_name)
    hargs = ["envelope", "list", "--page-size", "5"]
    if account:
        hargs.extend(["--account", account])
    rc, out, err = run_himalaya(hargs)
    if rc != 0:
        print(f"ERR | check_failed | {clean_ansi(err)}", file=sys.stderr)
        return rc

    lines = out.strip().split("\n")
    unread = sum(1 for line in lines[2:] if "  *" in line) if len(lines) > 2 else 0
    print(f"Inbox: {unread} unread in latest 5")
    if len(lines) > 2:
        for line in lines[2:]:
            print(line)
    return 0


# --- SETUP & REFRESH ---

def generate_pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    auth_code = None

    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        OAuthCallbackHandler.auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body><h2>Authorization complete.</h2><p>You can close this tab.</p></body></html>")

    def log_message(self, format, *args):
        pass


def run_oauth2_flow(client_id, client_secret, auth_url, token_url, scope, redirect_port):
    verifier, challenge = generate_pkce()
    state = base64.urlsafe_b64encode(secrets.token_bytes(12)).rstrip(b"=").decode()
    redirect_uri = f"http://localhost:{redirect_port}"

    auth_params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
    })

    full_auth_url = f"{auth_url}?{auth_params}"
    print(f"Opening browser for authorization...")
    print(f"If browser doesn't open, visit:\n{full_auth_url}")
    webbrowser.open(full_auth_url)

    OAuthCallbackHandler.auth_code = None
    server = HTTPServer(("localhost", redirect_port), OAuthCallbackHandler)
    server.timeout = 120

    while OAuthCallbackHandler.auth_code is None:
        server.handle_request()

    server.server_close()
    auth_code = OAuthCallbackHandler.auth_code

    if not auth_code:
        return None, None, "No authorization code received"

    token_data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": verifier,
    }).encode()

    req = urllib.request.Request(
        token_url,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode())
            return body.get("access_token"), body.get("refresh_token"), None
    except urllib.error.HTTPError as e:
        return None, None, f"Token exchange failed ({e.code}): {e.read().decode()}"


def generate_account_toml(acct, provider, client_id):
    name = acct["name"]
    email = acct["email"]
    display_name = acct.get("display_name", "")
    is_default = acct.get("default", False)

    downloads_dir = os.path.expanduser(f"~/Dropbox/email/{name}__{email.split('@')[1]}/downloads")

    lines = [
        f"[accounts.{name}]",
        f'default = {"true" if is_default else "false"}',
        f'email = "{email}"',
        f'display-name = "{display_name}"',
        f'downloads-dir = "{downloads_dir}"',
        f'backend.type = "imap"',
        f'backend.host = "{provider["imap_host"]}"',
        f'backend.port = {provider["imap_port"]}',
        f'backend.login = "{email}"',
        f'backend.encryption.type = "{provider["imap_encryption"]}"',
    ]

    if provider["auth_type"] == "oauth2":
        lines.extend([
            f'backend.auth.type = "oauth2"',
            f'backend.auth.method = "{provider["auth_method"]}"',
            f'backend.auth.client-id = "{client_id}"',
            f'backend.auth.auth-url = "{provider["auth_url"]}"',
            f'backend.auth.token-url = "{provider["token_url"]}"',
            f'backend.auth.pkce = {"true" if provider.get("pkce") else "false"}',
            f'backend.auth.redirect-scheme = "{provider.get("redirect_scheme", "http")}"',
            f'backend.auth.redirect-host = "{provider.get("redirect_host", "localhost")}"',
            f'backend.auth.redirect-port = {provider.get("redirect_port", 49152)}',
            f'backend.auth.scope = "{provider["scope"]}"',
            f'backend.auth.client-secret.keyring = "{name}-imap-oauth2-client-secret"',
            f'backend.auth.access-token.keyring = "{name}-imap-oauth2-access-token"',
            f'backend.auth.refresh-token.keyring = "{name}-imap-oauth2-refresh-token"',
        ])
    else:
        lines.extend([
            f'backend.auth.type = "password"',
            f'backend.auth.raw = "PLACEHOLDER"',
        ])

    for alias, folder in provider.get("folder_aliases", {}).items():
        lines.append(f'folder.aliases.{alias} = "{folder}"')

    lines.append(f'message.send.backend.type = "smtp"')
    lines.append(f'message.send.backend.host = "{provider["smtp_host"]}"')
    lines.append(f'message.send.backend.port = {provider["smtp_port"]}')
    lines.append(f'message.send.backend.login = "{email}"')
    lines.append(f'message.send.backend.encryption.type = "{provider["smtp_encryption"]}"')

    if provider["auth_type"] == "oauth2":
        lines.extend([
            f'message.send.backend.auth.type = "oauth2"',
            f'message.send.backend.auth.method = "{provider["auth_method"]}"',
            f'message.send.backend.auth.client-id = "{client_id}"',
            f'message.send.backend.auth.auth-url = "{provider["auth_url"]}"',
            f'message.send.backend.auth.token-url = "{provider["token_url"]}"',
            f'message.send.backend.auth.pkce = {"true" if provider.get("pkce") else "false"}',
            f'message.send.backend.auth.redirect-scheme = "{provider.get("redirect_scheme", "http")}"',
            f'message.send.backend.auth.redirect-host = "{provider.get("redirect_host", "localhost")}"',
            f'message.send.backend.auth.redirect-port = {provider.get("redirect_port", 49152)}',
            f'message.send.backend.auth.scope = "{provider["scope"]}"',
            f'message.send.backend.auth.client-secret.keyring = "{name}-smtp-oauth2-client-secret"',
            f'message.send.backend.auth.access-token.keyring = "{name}-smtp-oauth2-access-token"',
            f'message.send.backend.auth.refresh-token.keyring = "{name}-smtp-oauth2-refresh-token"',
        ])
    else:
        lines.extend([
            f'message.send.backend.auth.type = "password"',
            f'message.send.backend.auth.raw = "PLACEHOLDER"',
        ])

    return "\n".join(lines)


def account_exists_in_config(account_name):
    try:
        with open(HIMALAYA_CONFIG) as f:
            return f"[accounts.{account_name}]" in f.read()
    except FileNotFoundError:
        return False


def get_op_secret(item_name, field_label):
    result = subprocess.run(
        ["op", "item", "get", item_name, "--fields", field_label, "--reveal"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def cmd_setup(args):
    if has_flag(args, "--status"):
        return cmd_setup_status(args)

    try:
        registry = load_accounts_registry()
    except FileNotFoundError:
        print(f"ERR | setup | missing registry | {ACCOUNTS_FILE}", file=sys.stderr)
        return 1

    target_name = args[0] if args and not args[0].startswith("-") else None
    accounts_to_setup = registry["accounts"]
    if target_name:
        accounts_to_setup = [a for a in accounts_to_setup if a["name"] == target_name]
        if not accounts_to_setup:
            print(f"ERR | setup | unknown account | {target_name}", file=sys.stderr)
            print(f"Available: {', '.join(a['name'] for a in registry['accounts'])}", file=sys.stderr)
            return 1

    os.makedirs(os.path.dirname(HIMALAYA_CONFIG), exist_ok=True)

    if not os.path.exists(HIMALAYA_CONFIG):
        g = registry.get("global", {})
        sig = g.get("signature", "")
        with open(HIMALAYA_CONFIG, "w") as f:
            f.write(f'display-name = "{g.get("display_name", "")}"\n')
            f.write(f'signature = """\n{sig}"""\n\n')
        print(f"OK | setup | created config | {HIMALAYA_CONFIG}")

    for acct in accounts_to_setup:
        name = acct["name"]
        provider = registry["providers"].get(acct["provider"])
        if not provider:
            print(f"ERR | setup | unknown provider | {acct['provider']}", file=sys.stderr)
            continue

        if account_exists_in_config(name):
            print(f"OK | setup | already configured | {name}")
        else:
            # Pull client ID from 1Password
            client_id = None
            client_secret = None

            if acct.get("op_item"):
                print(f"Fetching credentials from 1Password for {name}...")
                client_id = get_op_secret(acct["op_item"], acct.get("op_client_id_field", "client_id"))
                client_secret = get_op_secret(acct["op_item"], acct.get("op_client_secret_field", "client_secret"))

            if not client_id and provider["auth_type"] == "oauth2":
                print(f"ERR | setup | no client_id | Could not fetch from 1Password for {name}", file=sys.stderr)
                continue

            toml_block = generate_account_toml(acct, provider, client_id or "")

            with open(HIMALAYA_CONFIG, "a") as f:
                f.write(f"\n{toml_block}\n")
            print(f"OK | setup | config written | {name}")

            # Create downloads directory
            downloads_dir = os.path.expanduser(f"~/Dropbox/email/{name}__{acct['email'].split('@')[1]}/downloads")
            os.makedirs(downloads_dir, exist_ok=True)

            if provider["auth_type"] == "oauth2" and client_secret:
                # Seed keyring with client secret for both IMAP and SMTP
                set_keyring_secret(f"{name}-imap-oauth2-client-secret", client_secret)
                set_keyring_secret(f"{name}-smtp-oauth2-client-secret", client_secret)
                print(f"OK | setup | keyring seeded | {name} client secrets")

                # Run OAuth2 flow for IMAP tokens
                print(f"\n--- OAuth2 authorization for {name} (IMAP) ---")
                access_token, refresh_token, err = run_oauth2_flow(
                    client_id, client_secret,
                    provider["auth_url"], provider["token_url"],
                    provider["scope"], provider.get("redirect_port", 49152)
                )

                if err:
                    print(f"ERR | setup | oauth2_failed | {name} IMAP: {err}", file=sys.stderr)
                    continue

                set_keyring_secret(f"{name}-imap-oauth2-access-token", access_token)
                set_keyring_secret(f"{name}-imap-oauth2-refresh-token", refresh_token)
                print(f"OK | setup | imap tokens stored | {name}")

                # Run OAuth2 flow for SMTP tokens
                print(f"\n--- OAuth2 authorization for {name} (SMTP) ---")
                access_token2, refresh_token2, err2 = run_oauth2_flow(
                    client_id, client_secret,
                    provider["auth_url"], provider["token_url"],
                    provider["scope"], provider.get("redirect_port", 49152)
                )

                if err2:
                    print(f"ERR | setup | oauth2_failed | {name} SMTP: {err2}", file=sys.stderr)
                    continue

                set_keyring_secret(f"{name}-smtp-oauth2-access-token", access_token2)
                set_keyring_secret(f"{name}-smtp-oauth2-refresh-token", refresh_token2)
                print(f"OK | setup | smtp tokens stored | {name}")

            elif provider["auth_type"] == "password":
                print(f"Note: {name} uses password auth. Set the password in config manually or via keyring.")

        print(f"OK | setup | complete | {name}")

    return 0


def cmd_setup_status(args):
    try:
        registry = load_accounts_registry()
    except FileNotFoundError:
        print(f"ERR | status | missing registry | {ACCOUNTS_FILE}", file=sys.stderr)
        return 1

    print("email_tool account status")
    print("=" * 60)

    config_exists = os.path.exists(HIMALAYA_CONFIG)
    print(f"Config: {HIMALAYA_CONFIG} {'[exists]' if config_exists else '[MISSING]'}")
    print()

    for acct in registry["accounts"]:
        name = acct["name"]
        provider = registry["providers"].get(acct["provider"], {})
        in_config = account_exists_in_config(name) if config_exists else False

        print(f"Account: {name} ({acct['email']})")
        print(f"  Provider: {acct['provider']}")
        print(f"  In config: {'YES' if in_config else 'NO'}")

        if provider.get("auth_type") == "oauth2":
            imap_secret = get_keyring_secret(f"{name}-imap-oauth2-client-secret")
            imap_access = get_keyring_secret(f"{name}-imap-oauth2-access-token")
            imap_refresh = get_keyring_secret(f"{name}-imap-oauth2-refresh-token")
            smtp_secret = get_keyring_secret(f"{name}-smtp-oauth2-client-secret")
            smtp_access = get_keyring_secret(f"{name}-smtp-oauth2-access-token")
            smtp_refresh = get_keyring_secret(f"{name}-smtp-oauth2-refresh-token")

            def status(val):
                return "OK" if val else "MISSING"

            print(f"  IMAP keyring: secret={status(imap_secret)} access={status(imap_access)} refresh={status(imap_refresh)}")
            print(f"  SMTP keyring: secret={status(smtp_secret)} access={status(smtp_access)} refresh={status(smtp_refresh)}")

            # Test token refresh
            if imap_refresh and imap_secret:
                ok, msg = refresh_oauth2_token(f"{name}-imap", name)
                print(f"  IMAP refresh: {'OK' if ok else 'FAILED: ' + msg}")
            else:
                print(f"  IMAP refresh: SKIPPED (missing keyring entries)")

            if smtp_refresh and smtp_secret:
                ok, msg = refresh_oauth2_token(f"{name}-smtp", name)
                print(f"  SMTP refresh: {'OK' if ok else 'FAILED: ' + msg}")
            else:
                print(f"  SMTP refresh: SKIPPED (missing keyring entries)")
        else:
            print(f"  Auth: password-based (no token refresh needed)")

        downloads_dir = os.path.expanduser(f"~/Dropbox/email/{name}__{acct['email'].split('@')[1]}/downloads")
        print(f"  Downloads: {downloads_dir} {'[exists]' if os.path.isdir(downloads_dir) else '[MISSING]'}")
        print()

    return 0


def cmd_refresh(args):
    target_name = args[0] if args and not args[0].startswith("-") else None

    try:
        registry = load_accounts_registry()
    except FileNotFoundError:
        print(f"ERR | refresh | missing registry | {ACCOUNTS_FILE}", file=sys.stderr)
        return 1

    accounts_to_refresh = registry["accounts"]
    if target_name:
        accounts_to_refresh = [a for a in accounts_to_refresh if a["name"] == target_name]
        if not accounts_to_refresh:
            print(f"ERR | refresh | unknown account | {target_name}", file=sys.stderr)
            return 1

    any_failed = False
    for acct in accounts_to_refresh:
        name = acct["name"]
        provider = registry["providers"].get(acct["provider"], {})

        if provider.get("auth_type") != "oauth2":
            print(f"OK | refresh | skipped | {name} (password auth)")
            continue

        ok_imap, msg_imap = refresh_oauth2_token(f"{name}-imap", name)
        ok_smtp, msg_smtp = refresh_oauth2_token(f"{name}-smtp", name)

        if ok_imap:
            print(f"OK | refreshed | {name}-imap | {msg_imap}")
        else:
            print(f"ERR | refresh_failed | {name}-imap | {msg_imap}", file=sys.stderr)
            any_failed = True

        if ok_smtp:
            print(f"OK | refreshed | {name}-smtp | {msg_smtp}")
        else:
            print(f"ERR | refresh_failed | {name}-smtp | {msg_smtp}", file=sys.stderr)
            any_failed = True

    return 1 if any_failed else 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "list": cmd_list,
        "read": cmd_read,
        "search": cmd_search,
        "send": cmd_send,
        "reply": cmd_reply,
        "forward": cmd_forward,
        "delete": cmd_delete,
        "move": cmd_move,
        "flag": cmd_flag,
        "folders": cmd_folders,
        "accounts": cmd_accounts,
        "check": cmd_check,
        "setup": cmd_setup,
        "refresh": cmd_refresh,
    }

    if cmd not in commands:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(f"Available: {', '.join(commands.keys())}", file=sys.stderr)
        return 1

    return commands[cmd](args)


if __name__ == "__main__":
    sys.exit(main())
