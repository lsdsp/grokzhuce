"""
注册机配件
"""
from importlib import import_module

_EXPORTS = {
    "EmailService": "email_service",
    "TurnstileService": "turnstile_service",
    "UserAgreementService": "user_agreement_service",
    "NsfwSettingsService": "nsfw_service",
}


def __getattr__(name):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(globals().keys()) + list(_EXPORTS.keys()))

__all__ = ['EmailService', 'TurnstileService', 'UserAgreementService', 'NsfwSettingsService']
