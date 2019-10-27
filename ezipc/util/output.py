"""Module defining functions for printing to the Console."""

from datetime import datetime as dt
from logging import DEBUG, Formatter, getLogger, StreamHandler
from typing import Callable, Dict, List, Tuple, Union


NOCOLOR = lambda s: s


class Fake:
    def __getattr__(self, attr):
        return NOCOLOR


try:
    from blessings import Terminal
except ImportError:
    Terminal = Fake

T = Terminal()
Color = T
colors: Dict[str, Tuple[Callable[[str], str], str, int]] = {}

fmt = Formatter("<%(asctime)s.%(msecs)d> :: %(name)s // %(levelname)s: %(message)s", "%H:%M:%S")

ch = StreamHandler()
ch.setFormatter(fmt)

fmt.msec_format = "%s.%02d"

def newLogger(name: str = ""):
    logger = getLogger(name.upper())
    logger.addHandler(ch)
    logger.setLevel(DEBUG)
    return logger


def set_colors(use_real: bool):
    global Color
    global colors

    Color = T if use_real else Fake()
    colors = {
        "": (Color.white, "", 1),
        "con": (Color.white, " ++", 1),
        "dcon": (Color.bright_black, "X- ", 1),
        "win": (Color.bright_green, "\o/", 1),
        "diff": (Color.white, "*- ", 2),
        "err": (Color.magenta, "x!x", 1),
        "recv": (Color.white, "-->", 3),
        "send": (Color.bright_black, "<--", 3),
        "tab": (Color.white, "   ", 3),
        "warn": (Color.magenta, "(!)", 3),
        "info": (Color.cyan, "(!)", 2),
    }


set_colors(True)


class _Printer:
    def __init__(self, verbosity: int = 2):
        self.file = None
        self.output_line = print
        self.startup: dt = dt.utcnow()
        self.verbosity: int = verbosity

    def emit(self, etype: str, text: str, color=None):
        now = dt.utcnow()
        p_color, prefix, pri = colors.get(etype) or (Color.white, etype, 4)
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
                    p_color(prefix),
                    (color or NOCOLOR)(str(text)),
                )
            )


P = _Printer()


def echo(etype: str, text: Union[str, List[str]] = None, color=""):
    if text is None:
        etype, text = "info", etype

    if type(text) == list:
        for line in text:
            P.emit(etype, line, color)
    else:
        P.emit(etype, text, color)


def err(text: str, exc: BaseException = None):
    if exc is not None:
        text += " {} - {}".format(type(exc).__name__, exc)
    echo("err", text, Color.red)


def warn(text: str):
    echo("warn", text, Color.bright_yellow)


def set_verbosity(n: int):
    P.verbosity = n
