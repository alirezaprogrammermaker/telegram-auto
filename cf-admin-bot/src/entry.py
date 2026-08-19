from urllib.parse import urlparse

from app.Http.Controllers.InternalAlertsController import InternalAlertsController
from app.Http.Controllers.InternalCacheController import InternalCacheController
from app.Http.Controllers.InternalLinkDirController import InternalLinkDirController
from app.Http.Controllers.InternalLoginController import InternalLoginController
from app.Http.Controllers.InternalPoolController import InternalPoolController
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
            return await WebhookController(
                self.env, getattr(self, "ctx", None)
            ).handle(request)

        if path.startswith("/internal/login/") and method == "GET":
            account_id = path[len("/internal/login/") :].strip("/")
            return await InternalLoginController(self.env).handle(
                request, account_id
            )

        if path == "/internal/pool/report" and method == "POST":
            return await InternalPoolController(self.env).handle(request)

        if path == "/internal/cache/report" and method == "POST":
            return await InternalCacheController(self.env).handle(request)

        if path == "/internal/alerts" and method == "POST":
            return await InternalAlertsController(self.env).handle(request)

        if path.startswith("/internal/linkdir/") and method in {"GET", "POST"}:
            action = path[len("/internal/linkdir/") :]
            return await InternalLinkDirController(self.env).handle(request, action)

        return Response.json(
            {"ok": False, "error": __("error.not_found")}, status=404
        )
