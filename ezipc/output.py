from datetime import datetime as dt

from colorama import init, Fore


init()
prefices = {
    "": (Fore.WHITE, "", 1),
    "con": (Fore.WHITE, " ++", 1),
    "dcon": (Fore.WHITE, "X- ", 1),
    "win": (Fore.LIGHTGREEN_EX, "\o/", 2),
    "diff": (Fore.WHITE, "*- ", 2),
    "err": (Fore.MAGENTA, "x!x", 3),
    "recv": (Fore.WHITE, "-->", 3),
    "send": (Fore.LIGHTBLACK_EX, "<--", 3),
    "tab": (Fore.WHITE, "   ", 3),
    "warn": (Fore.MAGENTA, "(!)", 3),
    "info": (Fore.CYAN, "(!)", 4),
}


class _Printer:
    def __init__(self, verbosity=2):
        self.verbosity = verbosity
        self.startup = dt.utcnow()

    def emit(self, etype, text, color=Fore.RESET):
        p_color, prefix, pri = prefices.get(etype) or (Fore.WHITE, etype, 4)
        if pri <= self.verbosity:
            print(
                # TODO: Decide which of these is better
                # "<{}> {} {}".format(  # One Time format
                # Fore.RESET +
                "<{} | {}> {} {}".format(  # Two Times format
                    str(dt.utcnow())[11:-4],  # Current Time
                    str(dt.utcnow() - self.startup)[:-7],  # Server Uptime
                    p_color + prefix,
                    color + str(text) + Fore.RESET,
                    )
                # + Fore.LIGHTRED_EX
            )


P = _Printer()


def echo(etype: str, text: str):
    P.emit(etype, text)


def err(text: str, exc: Exception = None):
    if exc:
        text += " {} - {}".format(type(exc).__name__, exc)
    echo("err", Fore.RED + text)


def warn(text: str):
    echo("warn", Fore.LIGHTYELLOW_EX + text)


def set_verbosity(n: int):
    P.verbosity = n
