""" to use standalone (on user ipython), copy this file to ~/.ipython/profile_default/startup/ipyco.py
(ofc replace profile_default if you made custom one in the past)
then on a new ipython session, you could simply run `from ipyco import copy`.
if you want to avoid needing to to import it on the startup of every ipy session,
you could uncomment the following dumb hack to inject it into the builtins on startup """
# import("builtins").copy = (copy := None) # copy will be overriden with the actual impl later in the file

import subprocess
import platform
import curses

from IPython.core.history import HistoryAccessor
from pygments.lexers import PythonLexer
from pygments.token import Token
from pygments import lex


# TODO should probably use a deque or something
selected_lines = set()


def pass_text_to_command(text: str, command: list):
    process = subprocess.Popen(command, stdin=subprocess.PIPE, text=True)
    process.communicate(text)


def copy_to_clipboard_macos(text):
    pass_text_to_command(text, ["pbcopy"])


def copy_to_clipboard_linux(text):
    # TODO for anyone not using x11, add whatever the alternative is for wayland?
    pass_text_to_command(text, ["xclip", "-selection", "c"])


def copy_to_clipboard(text):
    os_name = platform.system()
    if os_name == "Darwin":
        copy_to_clipboard_macos(text)
    elif os_name == "Linux":
        copy_to_clipboard_linux(text)
    else:
        raise NotImplementedError("Unsupported OS for clipboard functionality")


def format_selected_lines(selected_lines):
    if not selected_lines:
        return "None"

    sorted_lines = sorted(selected_lines)
    ranges = []
    start = sorted_lines[0]
    end = start

    for line in sorted_lines[1:]:
        if line == end + 1:
            end = line
        else:
            ranges.append((start, end))
            start = end = line

    ranges.append((start, end))

    formatted_ranges = []
    for start, end in ranges:
        if end - start >= 2:
            formatted_ranges.append(f"{start} - {end}")
        elif end == start:
            formatted_ranges.append(f"{start}")
        else:
            formatted_ranges.append(f"{start}, {end}")

    return ", ".join(formatted_ranges)


def setup_colors():
    """initialize curses color pairs for syntax highlighting and selection."""
    curses.start_color()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)  # Normal text
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)  # Highlighted background
    curses.init_pair(3, curses.COLOR_BLUE, curses.COLOR_BLACK)  # Keywords
    curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)  # Strings
    curses.init_pair(5, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Comments
    curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)  # Simulated gray for current block


def get_token_color(token_type):
    """Map Pygments token types to curses color pairs."""
    if token_type in Token.Keyword:
        return curses.color_pair(3)
    elif token_type in Token.Literal.String:
        return curses.color_pair(4)
    elif token_type in Token.Comment:
        return curses.color_pair(5)
    return curses.color_pair(1)


def lex_and_print_line(stdscr, y, line, lexer, max_x, is_current, line_number, show_selection_marker):
    """Lex a single line of code and print it with syntax highlighting."""
    x = 0

    if show_selection_marker:
        x = 4  # length of [X]<SPACE>
        selection_marker = "X" if line_number in selected_lines else " "

        stdscr.addstr(y, 0, "[", curses.color_pair(1))

        # special color if current
        marker_color = curses.color_pair(6) if is_current else curses.color_pair(1)

        stdscr.addstr(y, 1, selection_marker, marker_color)

        stdscr.addstr(y, 2, "]", curses.color_pair(1))

    # extra indentation for inner lines of expanded blocks
    if not show_selection_marker:
        x += 4

    for token_type, token_value in lex(line, lexer):
        color = get_token_color(token_type)
        while token_value:
            chunk = token_value[: max_x - x]
            token_value = token_value[max_x - x :]
            stdscr.addstr(y, x, chunk, color)
            x += len(chunk)
            # if the end of the screen is reached, move to the next line
            if x >= max_x:
                y += 1
                x = 4 if show_selection_marker else 0
    return y + 1


def copy():
    def _copy(stdscr):
        curses.curs_set(0)  # hide cursor
        setup_colors()

        history_accessor = HistoryAccessor()
        current_session_id = history_accessor.get_last_session_id()
        history_items = list(history_accessor.get_range(session=current_session_id))
        history_items.pop()  # last is the copy() call so we delete it
        current_index = 0
        expanded_blocks = set()  # Track expanded blocks
        if history_items and "\n" in history_items[0][2]:
            expanded_blocks.add(0)

        def copy_selected_to_clipboard():
            """Copy the selected blocks to the clipboard in chronological order."""
            selected_text = []
            for index in sorted(selected_lines):  # Ensure chronological order
                _, _, code = history_items[index]
                selected_text.append(code)
            clipboard_content = "\n".join(selected_text)
            copy_to_clipboard(clipboard_content)

        def update_display():
            stdscr.erase()  # clear the screen to geta clean update
            max_y, max_x = stdscr.getmaxyx()
            pos_y = 0

            for i, (_, _, code) in enumerate(history_items):
                is_current = i == current_index
                lines = code.splitlines()
                is_expanded = i in expanded_blocks

                for line_number, line in enumerate(lines):
                    if pos_y >= max_y:
                        break

                    show_selection_marker = line_number == 0

                    if is_current:
                        if is_expanded or line_number == 0:
                            # showing all lines if expanded
                            lex_and_print_line(
                                stdscr, pos_y, line, PythonLexer(), max_x, is_current, i, show_selection_marker
                            )
                            pos_y += 1
                        else:
                            # skipping additional lines in the current block if not expanded
                            break
                    else:
                        # for non-current blocks, always show the first line with the selection marker
                        if line_number == 0:
                            lex_and_print_line(
                                stdscr, pos_y, line, PythonLexer(), max_x, is_current, i, show_selection_marker
                            )
                            pos_y += 1

            selected_info = "Selected Indexes: " + format_selected_lines(selected_lines)
            stdscr.move(max_y - 1, 0)  # last line
            stdscr.clrtoeol()
            stdscr.addstr(max_y - 1, 0, selected_info[:max_x], curses.color_pair(1))
            stdscr.refresh()

        update_display()

        while True:
            key = stdscr.getkey()

            if key == "q":
                break

            if key == "\n":
                copy_selected_to_clipboard()
                break

            elif key == "KEY_DOWN" and current_index < len(history_items) - 1:
                current_index += 1
                if current_index not in expanded_blocks:
                    expanded_blocks.add(current_index)
                update_display()
            elif key == "KEY_UP" and current_index > 0:
                current_index -= 1
                if current_index not in expanded_blocks:
                    expanded_blocks.add(current_index)
                update_display()
            elif key == " ":  # mark/ unmark block
                if current_index in selected_lines:
                    selected_lines.remove(current_index)
                else:
                    selected_lines.add(current_index)
                update_display()
            elif key == "\t":  # expand/collapse block
                if current_index in expanded_blocks:
                    expanded_blocks.remove(current_index)
                else:
                    expanded_blocks.add(current_index)
                update_display()

    curses.wrapper(_copy)
