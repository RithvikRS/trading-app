"""Provider contract fixture for session/recovery tests; never usable at runtime."""

import json
import time
from uuid import UUID

import httpx2 as httpx

from tests.auth_support import FACTOR, PASSWORD, SETUP, SUBJECT, SupabaseStub

BACKUP = UUID("40000000-0000-4000-8000-000000000002")


class BrowserProviderStub(SupabaseStub):
    def __init__(self):
        super().__init__()
        self.primary = "password"
        self.renewals = 0
        self.password_changes = 0
        self.refresh_hook = None
        self.fail_refresh = False
        self.fail_logout = False

    def claims(self, mfa=False):
        claims = super().claims(mfa)
        if self.primary == "otp":
            claims["amr"][0]["method"] = "otp"
        return claims

    def handle(self, request):
        path = request.url.path.removeprefix("/auth/v1")
        if path in self.overrides:
            return super().handle(request)
        if path == "/token":
            self.requests.append(request)
            if request.url.query == b"grant_type=password":
                self.primary = "password"
                if json.loads(request.content)["password"] != PASSWORD.get_secret_value():
                    return httpx.Response(400)
                return httpx.Response(200, json=self.tokens())
            assert request.url.query == b"grant_type=refresh_token"
            self.renewals += 1
            if self.refresh_hook:
                self.refresh_hook()
            if self.fail_refresh:
                return httpx.Response(503)
            result = self.tokens(True)
            result["refresh_token"] += str(self.renewals)
            return httpx.Response(200, json=result)
        if path == "/logout":
            self.requests.append(request)
            assert request.url.query in {b"scope=local", b"scope=global"}
            self.discarded += 1
            return httpx.Response(503 if self.fail_logout else 204)
        if path == "/recover":
            self.requests.append(request)
            return httpx.Response(200, json={})
        if path == "/verify":
            self.requests.append(request)
            assert json.loads(request.content)["type"] == "recovery"
            if json.loads(request.content)["token"] != "654321":
                return httpx.Response(403)
            self.primary = "otp"
            return httpx.Response(200, json=self.tokens())
        if path == "/user" and request.method == "PUT":
            self.requests.append(request)
            assert set(json.loads(request.content)) == {"password"}
            self.password_changes += 1
            return httpx.Response(200, json={"id": str(SUBJECT)})
        if path == "/factors":
            self.requests.append(request)
            identifier = BACKUP if self.factors else FACTOR
            self.factors.append(dict(id=str(identifier), factor_type="totp", status="unverified"))
            return httpx.Response(
                200, json=dict(id=str(identifier), type="totp", totp=dict(secret=SETUP))
            )
        if path.startswith("/factors/"):
            self.requests.append(request)
            identifier = path.split("/")[2]
            if request.method == "DELETE":
                self.factors = [f for f in self.factors if f["id"] != identifier]
                return httpx.Response(200, json={"id": identifier})
            if path.endswith("/challenge"):
                return httpx.Response(
                    200, json=dict(id=str(FACTOR), expires_at=int(time.time()) + 300)
                )
            if path.endswith("/verify"):
                if json.loads(request.content)["code"] != "123456":
                    return httpx.Response(422)
                for factor in self.factors:
                    if factor["id"] == identifier:
                        factor["status"] = "verified"
                return httpx.Response(200, json=self.tokens(True))
        return super().handle(request)
