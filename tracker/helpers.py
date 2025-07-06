import os

import logging
import uuid
from functools import partialmethod
from importlib import import_module


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
        level = extra.get("level", "info")
        log_fn = getattr(self.logger, level)

        for dct in args:
            extra.update(dct)

        extra["proc_ref"] = self.proc_ref
        for key, value in extra.items():
            if isinstance(value, uuid.UUID):
                extra[key] = str(value)

        return log_fn(msg, extra=extra)

    # An alternative to log_info that can be used for temporary logs.
    # Allows us to easily differentiate between logs that should be cleaned
    # up after a short time and logs that should remain in the codebase.
    log_info_temp = partialmethod(log, level="info")
    log_info = partialmethod(log, level="info")
    log_warning = partialmethod(log, level="warning")
    log_error = partialmethod(log, level="exception")
