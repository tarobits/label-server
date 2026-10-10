"""Cookie/CSRF authentication for the bundled standard-library API clients."""

import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request

_sessions: dict[str, tuple[urllib.request.OpenerDirector, str]] = {}


def open_authenticated(request: urllib.request.Request, timeout: float = 30):
    username = os.environ.get("LABEL_API_USERNAME")
    password = os.environ.get("LABEL_API_PASSWORD")
    if not username and not password:
        # The server still enforces authentication; retaining this transport path
        # also supports test transports and external authenticated proxies.
        return urllib.request.urlopen(request, timeout=timeout)
    if not username or not password:
        raise SystemExit("Set both LABEL_API_USERNAME and LABEL_API_PASSWORD")
    url = urllib.parse.urlsplit(request.full_url)
    server = urllib.parse.urlunsplit((url.scheme, url.netloc, "", "", ""))
    if server not in _sessions:
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        login = urllib.request.Request(
            server + "/api/auth/login",
            data=json.dumps({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with opener.open(login, timeout=timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise SystemExit(
                "API sign-in failed; check the configured account credentials"
            ) from error
        _sessions[server] = opener, result["csrf_token"]
    opener, csrf = _sessions[server]
    request.add_header("X-CSRF-Token", csrf)
    return opener.open(request, timeout=timeout)
