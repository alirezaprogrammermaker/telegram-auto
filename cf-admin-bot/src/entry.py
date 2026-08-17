from urllib.parse import urlparse

from app.Http.Controllers.InternalLoginController import InternalLoginController
from app.Http.Controllers.WebhookController import WebhookController
from app.Support.Lang import __
from workers import Response, WorkerEntrypoint


class Default(WorkerEntrypoint):
    """Thin Worker entry — routing only."""

    async def fetch(self, request):
        url = urlparse(request.url)
        method = request.method.upper()
        path = url.path.rstrip("/") or "/"

        if path in {"/", "/health"} and method == "GET":
            return Response.json(
                {
                    "ok": True,
                    "service": "telegram-admin-bot",
                    "hint": __("health.hint"),
                }
            )

        if path == "/webhook" and method == "POST":
            return await WebhookController(self.env).handle(request)

        if path.startswith("/internal/login/") and method == "GET":
            account_id = path[len("/internal/login/") :].strip("/")
            return await InternalLoginController(self.env).handle(
                request, account_id
            )

        return Response.json(
            {"ok": False, "error": __("error.not_found")}, status=404
        )
