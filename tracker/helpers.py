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

        return log_fn(msg, *log_args, extra=log_extra)

    # An alternative to log_info that can be used for temporary logs.
    # Allows us to easily differentiate between logs that should be cleaned
    # up after a short time and logs that should remain in the codebase.
    log_info_temp = partialmethod(log, level="info")
    log_info = partialmethod(log, level="info")
    log_warning = partialmethod(log, level="warning")
    log_error = partialmethod(log, level="exception")
