from datetime import datetime as dt

from colorama import init, Fore


init()
prefices = {
    "": ("", 1),
    "con": (" ++", 1),
    "dcon": ("-X ", 1),
    "diff": ("*- ", 2),
    "err": ("x!x", 2),
    "info": ("(!)", 4),
    "recv": ("-->", 3),
    "send": ("<--", 3),
    "tab": ("   ", 3),
}


class _Printer:
    def __init__(self, verbosity=2):
        self.verbosity = verbosity
        self.startup = dt.utcnow()

    def emit(self, prefix, text, pri=4):
        if pri <= self.verbosity:
            print(
                "".join(
                    [
                        "<",
                        # str(dt.utcnow() - self.startup)[:-7],
                        str(dt.utcnow())[11:-7],
                        "> ",
                        Fore.WHITE,
                        prefix,
                        Fore.RESET,
                        " ",
                        str(text),
                    ]
                )
            )


P = _Printer()


def echo(etype: str, text: str):
    if not text:
        P.emit("?? ", etype, 4)
    etype_, pri = prefices.get(etype, ("?? ", 4))
    P.emit(etype_, text, pri)


def err(text: str):
    echo("err", text)


def set_verbosity(n: int):
    P.verbosity = n
