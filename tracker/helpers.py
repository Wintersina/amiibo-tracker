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
        caller = inspect.stack()[1].function
        user_context = {}

        if request is not None:
            user_context = {
                "session_user_name": request.session.get("user_name"),
                "session_user_email": request.session.get("user_email"),
            }

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
        database_path = Path(__file__).parent / "amiibo_database.json"
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
