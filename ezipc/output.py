from datetime import datetime as dt

from colorama import init, Fore


init()
prefices = {
    "": ("", 4),
    "con": (" ++", 4),
    "dcon": ("-X ", 4),
    "diff": ("*- ", 3),
    "err": ("x!x", 3),
    "info": ("(!)", 1),
    "recv": ("-->", 2),
    "send": ("<--", 2),
    "tab": ("   ", 2),
}


class _Printer:
    def __init__(self, verbosity=4):
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
    # if not text:
    #     text = str(etype)
    #     etype = ""
    etype_, pri = prefices.get(etype, ("    ", 4))
    # print(text)
    P.emit(etype_, text, pri)


def err(text: str):
    echo("err", text)
