"""KakaoTalk "나에게 보내기" (memo API). The access token is refreshed every run.

Links must be on a domain registered in the Kakao app (플랫폼 > Web > 사이트 도메인),
so messages link to the feed page, not to each deal.
"""
from __future__ import annotations

import json

from common import HttpError, http_request
from notifiers.base import Message, Notifier

TEXT_LIMIT = 200  # Kakao text template limit


class KakaoTokenError(Exception):
    """refresh_token expired or revoked; notify.py alerts the other channels."""


class Kakao(Notifier):
    type = "kakao"
    label = "카카오톡 나에게 보내기"
    required_env = ("DEALBOT_KAKAO_REST_KEY", "DEALBOT_KAKAO_REFRESH_TOKEN")
    _access_token: str | None = None

    def render(self, msg: Message) -> dict:
        lines = [msg.header]
        if msg.body:
            lines.append(msg.body)
        lines += [f"• {it['title']}" for it in msg.items]
        text = "\n".join(lines)
        if len(text) > TEXT_LIMIT:
            text = text[: TEXT_LIMIT - 1] + "…"
        link = self.fmt.get("feed_url") or ""
        return {"object_type": "text", "text": text,
                "link": {"web_url": link, "mobile_web_url": link}, "button_title": "피드 보기"}

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        form = {"grant_type": "refresh_token", "client_id": self.env("DEALBOT_KAKAO_REST_KEY"),
                "refresh_token": self.env("DEALBOT_KAKAO_REFRESH_TOKEN")}
        if self.env("DEALBOT_KAKAO_CLIENT_SECRET"):
            form["client_secret"] = self.env("DEALBOT_KAKAO_CLIENT_SECRET")
        try:
            raw = http_request("POST", "https://kauth.kakao.com/oauth/token", form=form)
        except HttpError as e:
            if e.status in (400, 401):
                raise KakaoTokenError(f"카카오 토큰 갱신 실패: {e}") from None
            raise
        data = json.loads(raw)
        if data.get("refresh_token"):
            # Kakao rotates the refresh token when it is within a month of expiry.
            print("kakao: 새 refresh_token이 발급됐습니다. DEALBOT_KAKAO_REFRESH_TOKEN 시크릿을 교체하세요.")
        self._access_token = data["access_token"]
        return self._access_token

    def deliver(self, payload: dict) -> None:
        headers = {"Authorization": f"Bearer {self._token()}"}
        http_request("POST", "https://kapi.kakao.com/v2/api/talk/memo/default/send",
                     form={"template_object": json.dumps(payload, ensure_ascii=False)},
                     headers=headers)
