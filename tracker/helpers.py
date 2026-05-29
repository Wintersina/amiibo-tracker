import os
import requests

import inspect
import json
import logging
import uuid
from functools import partialmethod
from importlib import import_module
from pathlib import Path


class HelperMixin:

    @property
    def get_env(self) -> str:
        env = os.getenv("ENV_NAME")
        return env

    @property
    def is_development(self) -> bool:
        return self.get_env == "development"


def import_string(dotted_path):
    module_path, class_name = dotted_path.rsplit(".", 1)

    return getattr(import_module(module_path), class_name)


def _client_ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def check_rate_limit(
    request,
    bucket: str,
    per_ip_max: int,
    per_ip_window: int,
    global_max: int,
    global_window: int,
):
    """Tiny cache-backed rate limiter.

    Returns None when the request is allowed, or a string describing the
    violation when it should be rejected with HTTP 429. Counters live in
    the Django cache, so they're per-process — multiple Cloud Run
    instances each get their own bucket, which is fine for shedding load.

    The check/increment isn't atomic; under heavy concurrency the cap may
    overshoot by a handful. Not worth a distributed lock for our scale.
    """
    from django.core.cache import cache

    ip = _client_ip(request)
    ip_key = f"ratelimit:{bucket}:ip:{ip}"
    global_key = f"ratelimit:{bucket}:global"

    ip_count = cache.get(ip_key, 0)
    if ip_count >= per_ip_max:
        return f"per-ip limit reached ({per_ip_max} per {per_ip_window}s)"

    global_count = cache.get(global_key, 0)
    if global_count >= global_max:
        return f"global limit reached ({global_max} per {global_window}s)"

    cache.set(ip_key, ip_count + 1, per_ip_window)
    cache.set(global_key, global_count + 1, global_window)
    return None


class LoggingMixin(object):
    """
    Common tools for class OOP logging
    """

    @property
    def logger(self):
        if not getattr(self, "proc_ref", None):
            self.proc_ref = uuid.uuid1().hex

        if not hasattr(self, "__logger"):
            self.__logger = logging.getLogger(self.__class__.__name__)

        return self.__logger

    def log(self, msg, *args, **extra):
        level = extra.pop("level", "info")
        log_fn = getattr(self.logger, level)

        log_extra = {**extra, "proc_ref": self.proc_ref}

        if args and all(isinstance(arg, dict) for arg in args):
            for dct in args:
                log_extra.update(dct)
            log_args = ()
        else:
            log_args = args

        for key, value in log_extra.items():
            if isinstance(value, uuid.UUID):
                log_extra[key] = str(value)

        context = {k: v for k, v in log_extra.items() if v is not None}
        if context:
            msg = f"{msg} | context={json.dumps(context, default=str, sort_keys=True)}"

        return log_fn(msg, *log_args, extra=log_extra)

    def log_action(self, event: str, request=None, level: str = "info", **context):
        from tracker.observability import hash_email

        caller = inspect.stack()[1].function
        user_context = {}

        if request is not None:
            email = request.session.get("user_email")
            user_context = {
                "event": event,
                "user_hash": hash_email(email),
                "authenticated": bool(email),
            }
        else:
            user_context = {"event": event}

        # Raw emails/names must not reach the log pipeline.
        context.pop("user_email", None)
        context.pop("user_name", None)

        # Stable marker so the daily DAU report can find every user-action event
        # with a single LogQL filter, regardless of which code path emitted it.
        user_context["kind"] = "user-action"
        user_context["action"] = event
        if request is not None:
            user_context.setdefault("path", getattr(request, "path", ""))
            user_context.setdefault("method", getattr(request, "method", ""))

        message = f"{caller}[{event}]"
        merged_context = {**user_context, **context}

        return self.log(message, merged_context, level=level)

    # An alternative to log_info that can be used for temporary logs.
    # Allows us to easily differentiate between logs that should be cleaned
    # up after a short time and logs that should remain in the codebase.
    log_info_temp = partialmethod(log, level="info")
    log_info = partialmethod(log, level="info")
    log_warning = partialmethod(log, level="warning")
    log_error = partialmethod(log, level="exception")


class AmiiboRemoteFetchMixin:
    def _fetch_remote_amiibos(self) -> list[dict]:
        api_url = "https://amiiboapi.org/api/amiibo/"

        try:
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            amiibos = data.get("amiibo", [])
            return amiibos if isinstance(amiibos, list) else []
        except (requests.RequestException, ValueError) as error:
            if hasattr(self, "log_warning"):
                self.log_warning(
                    "remote-amiibo-fetch-failed",
                    error=str(error),
                    api_url=api_url,
                )
            return []


class AmiiboLocalFetchMixin:
    def _fetch_local_amiibos(self) -> list[dict]:
        database_path = Path(__file__).parent / "data" / "amiibo_database.json"
        try:
            with database_path.open(encoding="utf-8") as database_file:
                data = json.load(database_file)
                amiibos = data.get("amiibo", [])
                return amiibos if isinstance(amiibos, list) else []
        except (FileNotFoundError, json.JSONDecodeError) as error:
            if hasattr(self, "log_error"):
                self.log_error(
                    "local-amiibo-fetch-failed",
                    error=str(error),
                    path=str(database_path),
                )
            return []
