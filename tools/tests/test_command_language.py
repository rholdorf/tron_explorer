"""The command language's tokenizer (tools/commands.py), the engine's ConParse (ltjs conparse.cpp, checked
against Tron's Lithtech.exe in docs/research/command-language.md): statements split on ';' and control
characters even inside parentheses, '(' / '"' group words, '%' escapes. Expected values are worked by
hand from the research's rules and examples.
"""
import commands


def test_statements_are_words_separated_by_spaces_and_semicolons():
    assert commands.statements("msg door1 on;msg door2 off") == [["msg", "door1", "on"], ["msg", "door2", "off"]]


def test_parentheses_make_one_word_and_only_the_outer_pair_is_dropped():
    assert commands.statements("delay 2 (msg kf (goto (k01)))") == [["delay", "2", "msg kf (goto (k01))"]]


def test_a_semicolon_splits_even_inside_parentheses():
    assert commands.statements("delay .25 (msg a (hidden 0); msg b off") == [
        ["delay", ".25", "msg a (hidden 0)"], ["msg", "b", "off"]]


def test_a_leftover_close_parenthesis_is_a_statement_of_its_own():
    assert commands.statements("delay 2.5 (msg x on;)") == [["delay", "2.5", "msg x on"], [")"]]


def test_line_breaks_end_statements_and_crlf_leaves_an_empty_one():
    assert commands.statements("msg a on\r\nmsg b on") == [["msg", "a", "on"], [], ["msg", "b", "on"]]


def test_quotes_group_like_parentheses_and_end_at_the_next_quote():
    assert commands.statements('msg "my door" on') == [["msg", "my door", "on"]]


def test_percent_escapes_the_next_character():
    assert commands.statements("msg a%;b on") == [["msg", "a;b", "on"]]


def test_a_close_parenthesis_with_nothing_open_is_kept_and_spaces_stop_splitting():
    # The depth wraps to 2^32-1: no space ends a word until a '(' brings it back to 0 (that '(' is kept).
    assert commands.statements("msg a) b c (d e") == [["msg", "a) b c (d", "e"]]


def test_an_empty_group_ends_the_whole_parse():
    assert commands.statements("msg a () ; msg b on") == [["msg", "a"]]


def test_thirty_words_end_the_statement_and_the_parse():
    words = " ".join(str(i) for i in range(32))
    assert commands.statements(words + ";msg a on") == [[str(i) for i in range(30)]]


def test_a_word_keeps_at_most_256_characters():
    assert commands.statements("x" * 300 + " y") == [["x" * 256, "y"]]


def test_a_string_runs_only_if_its_first_statement_is_a_valid_command():
    assert commands.is_valid("msg a on")
    assert commands.is_valid("DELAY 1 (msg a on)")
    assert not commands.is_valid("*msg a on")
    assert not commands.is_valid("xmsg a on; msg b on")
    assert not commands.is_valid("(FR)msg player on")
    assert not commands.is_valid("msg worry4DO")          # wrong word count
    assert not commands.is_valid(";msg a on")             # empty first statement
    assert not commands.is_valid("")
