"""Sending SMS.

SWAP_SMS=console  (default) prints the code in the server log: for development only.
SWAP_SMS=eskiz    sends real SMS through Eskiz.uz (needs ESKIZ_EMAIL and ESKIZ_PASSWORD).

NOT TESTED AGAINST THE REAL SERVICE: I have no Eskiz account or internet access to it.
Check the request format against https://documenter.getpostman.com/view/663428/RzfmES4z
before launch. Eskiz also requires the SMS text to be an approved template, so register
the text from auth.request_code ("SWAP: ваш код {code}. Никому его не сообщайте.") with them,
otherwise messages are rejected.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

ESKIZ_URL = "https://notify.eskiz.uz/api"


class SmsError(Exception):
    pass


class ConsoleSender:
    def send(self, phone: str, text: str) -> None:
        print(f"[SMS -> {phone}] {text}", flush=True)


class EskizSender:
    def __init__(self) -> None:
        self.email = os.environ["ESKIZ_EMAIL"]
        self.password = os.environ["ESKIZ_PASSWORD"]
        self.sender_id = os.getenv("ESKIZ_FROM", "4546")  # Eskiz default sender name
        self._token: str | None = None

    def _call(self, path: str, fields: dict, token: str | None = None) -> dict:
        req = urllib.request.Request(
            f"{ESKIZ_URL}{path}",
            data=urllib.parse.urlencode(fields).encode(),
            method="POST",
        )
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def _login(self) -> str:
        data = self._call("/auth/login", {"email": self.email, "password": self.password})
        self._token = data["data"]["token"]
        return self._token

    def send(self, phone: str, text: str) -> None:
        fields = {"mobile_phone": phone.lstrip("+"), "message": text, "from": self.sender_id}
        try:
            token = self._token or self._login()
            try:
                self._call("/message/sms/send", fields, token)
            except urllib.error.HTTPError as e:
                if e.code != 401:  # token expired: log in again once
                    raise
                self._call("/message/sms/send", fields, self._login())
        except Exception as e:
            raise SmsError("could not send SMS") from e


def get_sender():
    mode = os.getenv("SWAP_SMS", "console").lower()
    if mode == "eskiz":
        return EskizSender()
    return ConsoleSender()
