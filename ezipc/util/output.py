"""Module defining functions for printing to the Console."""

from datetime import datetime as dt
from typing import List, Union


class Fake:
    BLACK = ""
    RED = ""
    GREEN = ""
    YELLOW = ""
    BLUE = ""
    MAGENTA = ""
    CYAN = ""
    WHITE = ""
    RESET = ""
    LIGHTBLACK_EX = ""
    LIGHTRED_EX = ""
    LIGHTGREEN_EX = ""
    LIGHTYELLOW_EX = ""
    LIGHTBLUE_EX = ""
    LIGHTMAGENTA_EX = ""
    LIGHTCYAN_EX = ""
    LIGHTWHITE_EX = ""


try:
    from colorama import init, Fore

    init()
except ImportError:
    init = lambda: None
    Fore = Fake

Color = Fore
prefices = {}


def set_colors(use_real: bool):
    global Color
    global prefices

    Color = Fore if use_real else Fake
    prefices = {
        "": (Color.WHITE, "", 1),
        "con": (Color.WHITE, " ++", 1),
        "dcon": (Color.LIGHTBLACK_EX, "X- ", 1),
        "win": (Color.LIGHTGREEN_EX, "\o/", 1),
        "diff": (Color.WHITE, "*- ", 2),
        "err": (Color.MAGENTA, "x!x", 1),
        "recv": (Color.WHITE, "-->", 3),
        "send": (Color.LIGHTBLACK_EX, "<--", 3),
        "tab": (Color.WHITE, "   ", 3),
        "warn": (Color.MAGENTA, "(!)", 3),
        "info": (Color.CYAN, "(!)", 2),
    }


set_colors(True)


class _Printer:
    def __init__(self, verbosity: int = 2):
        self.file = None
        self.output_line = print
        self.startup: dt = dt.utcnow()
        self.verbosity: int = verbosity

    def emit(self, etype: str, text: str, color: str = ""):
        now = dt.utcnow()
        p_color, prefix, pri = prefices.get(etype) or (Color.WHITE, etype, 4)
        if self.file:
            print(
                "<{}> {} {}".format(now.isoformat(sep=" ")[:-3], prefix, str(text)),
                file=self.file,
                flush=True,
            )
        if pri <= self.verbosity:
            self.output_line(
                # TODO: Decide which of these is better
                "<{}> {} {}".format(  # One Time format
                    # "<{} | {}> {} {}".format(  # Two Times format
                    str(now)[11:-4],  # Current Time
                    # str(now - self.startup)[:-7],  # Server Uptime
                    p_color + prefix,
                    (color or Color.RESET) + str(text) + Color.RESET,
                )
            )


P = _Printer()


def echo(etype: str, text: Union[str, List[str]], color=""):
    if type(text) == list:
        for line in text:
            P.emit(etype, line, color)
    else:
        P.emit(etype, text, color)


def err(text: str, exc: Exception = None):
    if exc:
        text += " {} - {}".format(type(exc).__name__, exc)
    echo("err", text, Color.RED)


def warn(text: str):
    echo("warn", text, Color.LIGHTYELLOW_EX)


def set_verbosity(n: int):
    P.verbosity = n
