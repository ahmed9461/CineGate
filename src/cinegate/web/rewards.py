from __future__ import annotations

import html
import json
import secrets
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from cinegate.domain.rewards import (
    RewardSessionExpired,
    RewardSessionNotFound,
    RewardUserMismatch,
)
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.miniapp_auth import MiniAppAuthError, validate_miniapp_user

_DEFAULT_INIT_DATA_MAX_AGE = 600
_MIN_INIT_DATA_MAX_AGE = 60
_MAX_INIT_DATA_MAX_AGE = 3600


class RewardClaimBody(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


def build_reward_router() -> APIRouter:
    router = APIRouter()

    @router.get(
        "/miniapp/reward/{session_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def reward_page(session_id: UUID, request: Request) -> HTMLResponse:
        runtime = request.app.state.runtime
        try:
            reward = await runtime.rewards.get(session_id)
        except RewardSessionNotFound as exc:
            raise HTTPException(status_code=404, detail="reward session not found") from exc
        except RewardSessionExpired as exc:
            raise HTTPException(status_code=410, detail="reward session expired") from exc

        async with runtime.database.session() as session:
            block_id = await SettingsRepository(session).get("adsgram_block_id")

        if not isinstance(block_id, str) or not block_id.strip():
            return HTMLResponse(
                _unavailable_page("لم يتم إعداد شبكة الإعلانات بعد."),
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return HTMLResponse(
            _reward_page_html(
                session_id=reward.id,
                quality=reward.quality,
                block_id=block_id.strip(),
                reward_status=reward.status,
            )
        )

    @router.post("/api/rewards/{session_id}/claim")
    async def claim_reward(
        session_id: UUID,
        body: RewardClaimBody,
        request: Request,
    ) -> JSONResponse:
        runtime = request.app.state.runtime

        async with runtime.database.session() as session:
            value = await SettingsRepository(session).get_int(
                "miniapp_init_data_max_age_seconds"
            )
        max_age = _bounded_init_data_max_age(value)

        try:
            telegram_user_id = validate_miniapp_user(
                bot_token=runtime.settings.bot_token.get_secret_value(),
                init_data=body.init_data,
                max_age_seconds=max_age,
            )
        except MiniAppAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid Telegram Mini App identity",
            ) from exc

        try:
            reward = await runtime.rewards.mark_client_completed(
                session_id=session_id,
                telegram_user_id=telegram_user_id,
            )
        except RewardSessionNotFound as exc:
            raise HTTPException(status_code=404, detail="reward session not found") from exc
        except RewardSessionExpired as exc:
            raise HTTPException(status_code=410, detail="reward session expired") from exc
        except RewardUserMismatch as exc:
            raise HTTPException(status_code=403, detail="reward user mismatch") from exc

        if reward.is_rewarded:
            delivery = await runtime.delivery.deliver(reward.id)
            response_status = (
                status.HTTP_200_OK
                if delivery.status == "delivered"
                else status.HTTP_202_ACCEPTED
            )
            return JSONResponse(
                {
                    "status": delivery.status,
                    "telegram_message_id": delivery.telegram_message_id,
                },
                status_code=response_status,
            )

        return JSONResponse(
            {"status": "waiting_provider"},
            status_code=status.HTTP_202_ACCEPTED,
        )

    @router.get(
        "/providers/adsgram/reward/{callback_secret}",
        include_in_schema=False,
    )
    async def adsgram_reward(
        request: Request,
        callback_secret: str,
        userid: int = Query(...),
    ) -> Response:
        runtime = request.app.state.runtime
        configured = runtime.settings.adsgram_callback_secret
        if configured is None:
            raise HTTPException(status_code=404, detail="provider callback disabled")

        expected = configured.get_secret_value()
        if not secrets.compare_digest(callback_secret, expected):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="invalid provider callback",
            )

        reward = await runtime.rewards.mark_provider_confirmed(
            telegram_user_id=userid,
        )
        if reward is not None and reward.is_rewarded:
            await runtime.delivery.deliver(reward.id)

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


def _bounded_init_data_max_age(value: int | None) -> int:
    if value is None:
        return _DEFAULT_INIT_DATA_MAX_AGE
    return max(_MIN_INIT_DATA_MAX_AGE, min(_MAX_INIT_DATA_MAX_AGE, value))


def _reward_page_html(
    *,
    session_id: UUID,
    quality: str,
    block_id: str,
    reward_status: str,
) -> str:
    block_id_json = _json_for_script(block_id)
    session_id_json = _json_for_script(str(session_id))
    reward_status_json = _json_for_script(reward_status)
    quality_html = html.escape(quality)

    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>CineGate Reward</title>
  <script src="https://telegram.org/js/telegram-web-app.js?63"></script>
  <script src="https://sad.adsgram.ai/js/sad.min.js"></script>
  <style>
    body {{ font-family: sans-serif; margin: 0; padding: 24px; text-align: center; }}
    button {{ width: 100%; padding: 14px; font-size: 17px; cursor: pointer; }}
    #status {{ margin-top: 18px; min-height: 24px; }}
  </style>
</head>
<body>
  <h2>الجودة المطلوبة: {quality_html}</h2>
  <p>شاهد الإعلان حتى النهاية، وبعد التحقق سيصل الفيلم تلقائيًا.</p>
  <button id="watch">مشاهدة الإعلان</button>
  <div id="status"></div>
  <script>
    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();

    const blockId = {block_id_json};
    const sessionId = {session_id_json};
    const rewardStatus = {reward_status_json};
    const button = document.getElementById("watch");
    const statusBox = document.getElementById("status");
    const needsAd = (
      rewardStatus === "pending"
      || rewardStatus === "provider_confirmed"
    );
    const controller = (
      needsAd
        ? window.Adsgram.init({{ blockId }})
        : null
    );

    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    async function claimUntilReady() {{
      for (let attempt = 0; attempt < 12; attempt += 1) {{
        const response = await fetch(
          "/api/rewards/" + sessionId + "/claim",
          {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ init_data: tg.initData }}),
          }}
        );
        const data = await response.json();

        if (response.status === 401 || response.status === 403) {{
          throw new Error("تعذر التحقق من حساب تيليجرام.");
        }}
        if (response.status === 404 || response.status === 410) {{
          throw new Error("انتهت جلسة الإعلان. ارجع إلى البوت واطلب الجودة مجددًا.");
        }}
        if (data.status === "delivered") {{
          statusBox.textContent = "✅ تم التحقق وإرسال الفيلم إلى البوت.";
          setTimeout(() => tg.close(), 1200);
          return;
        }}

        statusBox.textContent = "تمت المشاهدة، جاري التحقق والتسليم...";
        await sleep(1000);
      }}
      throw new Error("تأخر تأكيد الإعلان. ارجع للبوت وحاول فتح الطلب نفسه لاحقًا.");
    }}

    async function continueExistingReward() {{
      button.disabled = true;
      button.textContent = "استكمال الطلب";
      statusBox.textContent = "جاري التحقق والتسليم...";
      try {{
        await claimUntilReady();
      }} catch (error) {{
        statusBox.textContent = error?.message || "تعذر إكمال الطلب. حاول مرة أخرى.";
        button.disabled = false;
      }}
    }}

    if (rewardStatus === "delivered") {{
      button.hidden = true;
      statusBox.textContent = "✅ تم إرسال الفيلم بالفعل.";
    }} else if (!needsAd) {{
      continueExistingReward();
    }} else {{
      button.addEventListener("click", async () => {{
        button.disabled = true;
        statusBox.textContent = "جاري تحميل الإعلان...";
        try {{
          await controller.show();
          statusBox.textContent = "تمت المشاهدة، جاري التحقق...";
          await claimUntilReady();
        }} catch (error) {{
          statusBox.textContent = error?.message || "تعذر إكمال الإعلان. حاول مرة أخرى.";
          button.disabled = false;
        }}
      }});
    }}
  </script>
</body>
</html>"""

def _json_for_script(value: str) -> str:
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _unavailable_page(message: str) -> str:
    return (
        '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">'
        f"<body><p>{html.escape(message)}</p></body></html>"
    )
