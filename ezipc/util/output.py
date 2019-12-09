"""Module defining functions for printing to the Console."""

from datetime import datetime as dt
from logging import DEBUG, Formatter, getLogger, StreamHandler
from typing import Callable, Dict, List, overload, Tuple, Union


NOCOLOR = lambda s: s


try:
    # noinspection PyPackageRequirements
    from blessings import Terminal
except ImportError:

    class Terminal:
        def __getattr__(self, attr):
            return NOCOLOR


T = Terminal()

fmt = Formatter(
    "<%(asctime)s.%(msecs)d> :: %(name)s // %(levelname)s: %(message)s", "%H:%M:%S"
)
fmt.msec_format = "%s.%02d"
ch = StreamHandler()
ch.setFormatter(fmt)


def newLogger(name: str = ""):
    logger = getLogger(name.upper())
    logger.addHandler(ch)
    logger.setLevel(DEBUG)
    return logger


colors: Dict[str, Tuple[Callable[[str], str], str, int]] = {
    "": (T.white, "", 1),

    "con": (T.bold_cyan, " ++", 1),
    "dcon": (T.bold_red, "X- ", 1),
    "win": (T.bold_green, "\o/", 1),
    "err": (T.bold_magenta, "x!x", 1),

    "diff": (T.white, "*- ", 2),
    "tab": (T.white, "   ", 2),
    "warn": (T.bold_yellow, "<!>", 2),
    "info": (T.cyan, "(!)", 2),

    "recv": (T.white, "-->", 3),
    "send": (T.bold_black, "<--", 3),
    "cast": (T.bold_white, "#=-", 3),
    "dbug": (T.yellow, "[!]", 3),
}


hl_method = T.bold_yellow
hl_remote = T.bold_magenta
hl_rtype = T.underline

res_bad = T.red
res_good = T.green


class _Printer:
    def __init__(self, verbosity: int = 2):
        self.file = None
        self.output_line = print
        self.startup: dt = dt.utcnow()
        self.verbosity: int = verbosity

    def emit(self, etype: str, text: str, color=None):
        now = dt.utcnow()
        p_color, prefix, pri, *tc = colors.get(etype) or (T.white, etype, 4)
        if tc:
            tc = tc[0]

        if self.file:
            print(
                "<{}> {} {}".format(now.isoformat(sep=" ")[:-3], prefix, text),
                file=self.file,
                # flush=True,
            )
        if pri <= self.verbosity:
            self.output_line(
                # f"<{str(now)[11:-4]}> {p_color(prefix)} {(color or tc or NOCOLOR)(text)}"
                f"<{now:%T}> {p_color(prefix)} {(color or tc or NOCOLOR)(text)}"
            )


P = _Printer()


@overload
def echo(text: Union[str, List[str]], color=""):
    ...


@overload
def echo(etype: str, text: Union[str, List[str]], color=""):
    ...


def echo(etype: str, text: Union[str, List[str]] = None, color=""):
    if text is None:
        etype, text = "info", etype

    if isinstance(text, list):
        for line in text:
            P.emit(etype, line, color)
    else:
        P.emit(etype, text, color)


def err(text: str, exc: BaseException = None):
    if exc is not None:
        text += f" {type(exc).__name__}: {exc}"
    echo("err", text, T.red)


def warn(text: str, exc: BaseException = None):
    if exc is not None:
        text += f" {type(exc).__name__}: {exc}"
    echo("warn", text, T.bright_yellow)


def set_verbosity(n: int):
    P.verbosity = n
