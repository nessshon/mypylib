from typing import ClassVar


class Colors:
    """ANSI escape-code constants and helper methods for colored output."""

    red = "\033[31m"
    green = "\033[32m"
    yellow = "\033[33m"
    blue = "\033[34m"
    magenta = "\033[35m"
    cyan = "\033[36m"
    endc = "\033[0m"
    bold = "\033[1m"
    underline = "\033[4m"
    default = "\033[39m"

    DEBUG = magenta
    INFO = blue
    OKGREEN = green
    WARNING = yellow
    ERROR = red
    ENDC = endc
    BOLD = bold
    UNDERLINE = underline

    @staticmethod
    def get_args(*args: object) -> str:
        """Concatenate *args* into a single string, skipping ``None``.

        :param args: Values to concatenate.
        :return: Concatenated string.
        """
        return "".join(str(item) for item in args if item is not None)

    @staticmethod
    def _wrap(color: str, *args: object) -> str:
        """Wrap concatenated *args* with *color* and reset escape codes."""
        return color + Colors.get_args(*args) + Colors.endc

    @staticmethod
    def magenta_text(*args: object) -> str:
        """Wrap text in magenta ANSI codes.

        :param args: Values to colorize.
        :return: Colored string.
        """
        return Colors._wrap(Colors.magenta, *args)

    @staticmethod
    def blue_text(*args: object) -> str:
        """Wrap text in blue ANSI codes.

        :param args: Values to colorize.
        :return: Colored string.
        """
        return Colors._wrap(Colors.blue, *args)

    @staticmethod
    def green_text(*args: object) -> str:
        """Wrap text in green ANSI codes.

        :param args: Values to colorize.
        :return: Colored string.
        """
        return Colors._wrap(Colors.green, *args)

    @staticmethod
    def yellow_text(*args: object) -> str:
        """Wrap text in yellow ANSI codes.

        :param args: Values to colorize.
        :return: Colored string.
        """
        return Colors._wrap(Colors.yellow, *args)

    @staticmethod
    def cyan_text(*args: object) -> str:
        """Wrap text in cyan ANSI codes.

        :param args: Values to colorize.
        :return: Colored string.
        """
        return Colors._wrap(Colors.cyan, *args)

    @staticmethod
    def red_text(*args: object) -> str:
        """Wrap text in red ANSI codes.

        :param args: Values to colorize.
        :return: Colored string.
        """
        return Colors._wrap(Colors.red, *args)

    @staticmethod
    def bold_text(*args: object) -> str:
        """Wrap text in bold ANSI codes.

        :param args: Values to stylize.
        :return: Bold string.
        """
        return Colors._wrap(Colors.bold, *args)

    @staticmethod
    def underline_text(*args: object) -> str:
        """Wrap text in underline ANSI codes.

        :param args: Values to stylize.
        :return: Underlined string.
        """
        return Colors._wrap(Colors.underline, *args)

    colors: ClassVar[dict[str, str]] = {
        "red": red,
        "green": green,
        "yellow": yellow,
        "blue": blue,
        "magenta": magenta,
        "cyan": cyan,
        "endc": endc,
        "bold": bold,
        "underline": underline,
    }


def color_text(text: str) -> str:
    """Replace ``{color}`` placeholders with ANSI escape codes.

    :param text: Input string with placeholders like ``{red}``.
    :return: String with ANSI codes substituted.
    """
    for cname in Colors.colors:
        item = "{" + cname + "}"
        if item in text:
            text = text.replace(item, Colors.colors[cname])
    return text


def color_print(text: str) -> None:
    """Print *text* after substituting color placeholders.

    :param text: Input string with ``{color}`` placeholders.
    """
    text = color_text(text)
    print(text)


bcolors = Colors
