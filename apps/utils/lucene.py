import re
from dataclasses import dataclass, asdict
from typing import List
from collections import Counter, deque

from luqum.exceptions import ParseSyntaxError, IllegalCharacterError
from luqum.visitor import TreeTransformer
from luqum.parser import parser, lexer
from luqum.auto_head_tail import auto_head_tail
from luqum.utils import UnknownOperationResolver
from django.utils.translation import ugettext_lazy as _

from apps.constants import (
    FULL_TEXT_SEARCH_FIELD_NAME,
    DEFAULT_FIELD_OPERATOR,
    FIELD_GROUP_OPERATOR,
    NOT_OPERATOR,
    PLUS_OPERATOR,
    PROHIBIT_OPERATOR,
    LOW_CHAR,
    HIGH_CHAR,
    LuceneSyntaxEnum,
    WORD_RANGE_OPERATORS,
    BRACKET_DICT,
    MAX_RESOLVE_TIMES,
)

from apps.exceptions import UnknownLuceneOperatorException


def get_node_lucene_syntax(node):
    """获取该节点lucene语法类型"""
    return node.__class__.__name__


@dataclass
class LuceneField(object):
    """Lucene解析出的Field类"""

    pos: int = 0
    name: str = ""
    type: str = ""
    operator: str = DEFAULT_FIELD_OPERATOR
    value: str = ""


class LuceneParser(object):
    """lucene语法的解析类"""

    def __init__(self, keyword: str) -> None:
        self.keyword = keyword

    def parsing(self) -> List[LuceneField]:
        """解析lucene语法入口函数"""
        tree = parser.parse(self.keyword, lexer=lexer)
        fields = self._get_method(tree)
        if isinstance(fields, list):
            # 以下逻辑为同名字段增加额外标识符
            names = Counter([field.name for field in fields])
            if not names:
                return fields
            for name, cnt in names.items():
                if cnt > 1:
                    number = 1
                    for field in fields:
                        if field.name == name:
                            field.name = f"{name}({number})"
                            number += 1
            return fields

        return [fields]

    def _get_method(self, node):
        """获取解析方法"""
        node_type = get_node_lucene_syntax(node)
        method_name = "parsing_{}".format(node_type.lower())
        return getattr(self, method_name)(node)

    def parsing_word(self, node):
        """解析单词"""
        field = LuceneField(
            pos=node.pos,
            name=FULL_TEXT_SEARCH_FIELD_NAME,
            operator="~=",
            type=LuceneSyntaxEnum.WORD,
            value=node.value,
        )
        match = re.search(WORD_RANGE_OPERATORS, node.value)
        if match:
            operator = match.group(0)
            field.operator = operator
            field.value = node.value.split(operator)[-1]
        return field

    def parsing_phrase(self, node):
        """解析短语"""
        field = LuceneField(
            pos=node.pos,
            name=FULL_TEXT_SEARCH_FIELD_NAME,
            operator="=",
            type=LuceneSyntaxEnum.PHRASE,
            value=node.value,
        )
        return field

    def parsing_searchfield(self, node):
        """解析搜索字段"""
        field = LuceneField(pos=node.pos, name=node.name, type=LuceneSyntaxEnum.SEARCH_FIELD)
        new_field = self._get_method(node.expr)
        field.type = new_field.type
        field.operator = new_field.operator
        field.value = new_field.value
        return field

    def parsing_fieldgroup(self, node):
        """解析字段组"""
        field = LuceneField(
            pos=node.pos,
            type=LuceneSyntaxEnum.FIELD_GROUP,
            operator=FIELD_GROUP_OPERATOR,
            value="({})".format(str(node.expr)),
        )
        return field

    def parsing_group(self, node):
        """"""
        fields = []
        for children in node.children:
            children_fields = self._get_method(children)
            if isinstance(children_fields, list):
                fields.extend(children_fields)
            else:
                fields.append(children_fields)
        return fields

    def parsing_range(self, node):
        """"""
        field = LuceneField(pos=node.pos, type=LuceneSyntaxEnum.RANGE, value=str(node))
        field.operator = "{}{}".format(LOW_CHAR[node.include_low], HIGH_CHAR[node.include_high])
        return field

    def parsing_fuzzy(self, node):
        """"""
        field = LuceneField(pos=node.pos, operator=DEFAULT_FIELD_OPERATOR, type=LuceneSyntaxEnum.FUZZY, value=str(node))
        return field

    def parsing_regex(self, node):
        """"""
        field = LuceneField(pos=node.pos, operator=DEFAULT_FIELD_OPERATOR, type=LuceneSyntaxEnum.REGEX, value=str(node))
        return field

    def parsing_proximity(self, node):
        """"""
        field = LuceneField(
            pos=node.pos,
            name=FULL_TEXT_SEARCH_FIELD_NAME,
            operator=DEFAULT_FIELD_OPERATOR,
            type=LuceneSyntaxEnum.PROXIMITY,
            value=str(node),
        )
        return field

    def parsing_oroperation(self, node):
        """解析或操作"""
        fields = []
        for operand in node.operands:
            operand_fields = self._get_method(operand)
            if isinstance(operand_fields, list):
                fields.extend(operand_fields)
            else:
                fields.append(operand_fields)
        return fields

    def parsing_andoperation(self, node):
        """"""
        fields = []
        for operand in node.operands:
            operand_fields = self._get_method(operand)
            if isinstance(operand_fields, list):
                fields.extend(operand_fields)
            else:
                fields.append(operand_fields)
        return fields

    def parsing_not(self, node):
        """"""
        field = LuceneField(
            pos=node.pos,
            name=FULL_TEXT_SEARCH_FIELD_NAME,
            operator=NOT_OPERATOR,
            type=LuceneSyntaxEnum.NOT,
            value=self._get_method(node.a).value,
        )
        return field

    def parsing_plus(self, node):
        """"""
        field = LuceneField(
            pos=node.pos,
            name=FULL_TEXT_SEARCH_FIELD_NAME,
            operator=PLUS_OPERATOR,
            type=LuceneSyntaxEnum.PLUS,
            value=self._get_method(node.a).value,
        )
        return field

    def parsing_prohibit(self, node):
        """解析减号"""
        field = LuceneField(
            pos=node.pos,
            name=FULL_TEXT_SEARCH_FIELD_NAME,
            operator=PROHIBIT_OPERATOR,
            type=LuceneSyntaxEnum.PROHIBIT,
            value=self._get_method(node.a).value,
        )
        return field

    def parsing_unknownoperation(self, node):
        """解析未知操作"""
        raise UnknownLuceneOperatorException()


class LuceneTransformer(TreeTransformer):
    """Lucene语句转换器"""

    def visit_search_field(self, node, context):
        """SEARCH_FIELD 类型转换"""
        if node.pos == context["pos"]:
            name, value = node.name, context["value"]
            if get_node_lucene_syntax(node.expr) == LuceneSyntaxEnum.WORD:
                operator = LuceneParser(keyword=str(node)).parsing()[0].operator
                if operator in WORD_RANGE_OPERATORS:
                    node = parser.parse(f"{name}: {operator}{value}", lexer=lexer)
                else:
                    node = parser.parse(f"{name}: {value}", lexer=lexer)
            else:
                node = parser.parse(f"{name}: {value}", lexer=lexer)

        yield from self.generic_visit(node, context)

    def visit_word(self, node, context):
        """WORD 类型转换"""
        if node.pos == context["pos"]:
            node.value = str(context["value"])
        yield from self.generic_visit(node, context)

    def transform(self, keyword: str, params: list) -> str:
        """转换Lucene语句"""
        query_tree = parser.parse(keyword, lexer=lexer)
        for param in params:
            query_tree = self.visit(query_tree, param)
        return str(auto_head_tail(query_tree))


@dataclass
class InspectResult(object):
    is_legal: bool = True
    message: str = ""


class BaseInspector(object):
    """检查器基类"""

    syntax_error_message = ""

    def __init__(self, keyword: str):
        self.keyword = keyword
        self.result = InspectResult()

    def get_result(self):
        return self.result

    def set_illegal(self):
        """设置检查结果为非法"""
        self.result.is_legal = False
        self.result.message = self.syntax_error_message

    def inspect(self):
        """检查"""
        raise NotImplementedError

    def remove_unexpected_character(self, match):
        """根据RE match来移除异常字符"""
        unexpect_word_len = len(match[1])
        position = int(str(match[2]))
        self.keyword = self.keyword[:position] + self.keyword[position + unexpect_word_len :]

    def replace_unexpected_character(self, pos: int, char: str):
        """替换字符"""
        self.keyword[pos] = char


class ChinesePunctuationInspector(BaseInspector):
    """中文引号转换"""

    syntax_error_message = _("中文标点异常")

    chinese_punctuation_re = r"(“.*?”)"

    def inspect(self):
        p = re.compile(self.chinese_punctuation_re)
        match_groups = [m for m in p.finditer(self.keyword)]
        if not match_groups:
            return
        for m in p.finditer(self.keyword):
            self.replace_unexpected_character(m.start(), '"')
            self.replace_unexpected_character(m.end(), '"')
        self.set_illegal()


class IllegalCharacterInspector(BaseInspector):
    """非法字符检查"""

    syntax_error_message = _("异常字符")

    # 非法字符正则
    illegal_character_re = r"Illegal character '(.*)' at position (\d+)"
    # 非预期字符正则
    unexpect_word_re = r"Syntax error in input : unexpected  '(.*)' at position (\d+)"

    def inspect(self):
        try:
            parser.parse(self.keyword, lexer=lexer)
        except IllegalCharacterError as e:
            match = re.search(self.illegal_character_re, str(e))
            if match:
                self.remove_unexpected_character(match)
                self.set_illegal()
        except ParseSyntaxError as e:
            match = re.search(self.unexpect_word_re, str(e))
            if match:
                self.remove_unexpected_character(match)
                self.set_illegal()
        except Exception:
            return


class IllegalRangeSyntaxInspector(BaseInspector):
    """非法RANGE语法检查"""

    syntax_error_message = _("非法RANGE语法")

    # 非预期字符正则
    unexpect_word_re = r"Syntax error in input : unexpected  '(.*)' at position (\d+)"

    # RANGE语法正则
    range_re = r"(\[.*?TO.*?\])"
    single_range_re = r"\[(.*)TO(.*)\]"

    def inspect(self):
        try:
            parser.parse(self.keyword, lexer=lexer)
        except ParseSyntaxError as e:
            match = re.search(self.unexpect_word_re, str(e))
            if match and match.group(1) == "TO":
                p = re.compile(self.range_re)
                match_groups = [[m.start(), m.end()] for m in p.finditer(self.keyword)]
                if not match_groups:
                    return
                self.resolve(match_groups)
                self.set_illegal()
        except Exception:
            return

    def resolve(self, match_groups: list):
        remain_keyword = []
        for i in range(len(match_groups)):
            if i == 0:
                remain_keyword.append(self.keyword[: match_groups[i][0]])
            else:
                remain_keyword.append(self.keyword[match_groups[i - 1][1] : match_groups[i][0]])
            # 进行单个Range语法的修复
            match = re.search(self.single_range_re, self.keyword[match_groups[i][0] : match_groups[i][1]])
            if match:
                start = match.group(1).strip()
                end = match.group(2).strip()
                if start and end:
                    continue
                if not start:
                    start = "*"
                if not end:
                    end = "*"
                remain_keyword.append(f"[{start} TO {end}]")

            if i == len(match_groups) - 1:
                remain_keyword.append(self.keyword[match_groups[i][1] :])

        self.keyword = "".join(remain_keyword)


class IllegalBracketInspector(BaseInspector):
    """修复括号不匹配"""

    syntax_error_message = _("括号不匹配")
    # 非预期语法re
    unexpect_unmatched_re = (
        "Syntax error in input : unexpected end of expression (maybe due to unmatched parenthesis) at the end!"
    )

    def inspect(self):
        try:
            parser.parse(self.keyword, lexer=lexer)
        except ParseSyntaxError as e:
            if str(e) == self.unexpect_unmatched_re:
                s = deque()
                for index in range(len(self.keyword)):
                    symbol = self.keyword[index]
                    # 左括号入栈
                    if symbol in BRACKET_DICT.keys():
                        s.append({"symbol": symbol, "index": index})
                        continue
                    if symbol in BRACKET_DICT.values():
                        if s and symbol == BRACKET_DICT.get(s[-1]["symbol"], ""):
                            # 右括号出栈
                            s.pop()
                            continue
                        s.append({"symbol": symbol, "index": index})
                        # 如果栈首尾匹配, 则异常的括号是栈顶向下第二个
                        if s[-1]["symbol"] == BRACKET_DICT.get(s[0]["symbol"], ""):
                            self.keyword = self.keyword[: s[-2]["index"]] + self.keyword[s[-2]["index"] + 1 :]
                        # 否则异常的括号是栈顶元素
                        else:
                            self.keyword = self.keyword[: s[-1]["index"]] + self.keyword[s[-1]["index"] + 1 :]
                        self.set_illegal()
                        return
                if not s:
                    return
                self.keyword = self.keyword[: s[-1]["index"]] + self.keyword[s[-1]["index"] + 1 :]
                self.set_illegal()
        except Exception:
            return


class IllegalColonInspector(BaseInspector):
    """修复冒号不匹配"""

    syntax_error_message = _("多余的冒号")
    # 非预期语法re
    unexpect_unmatched_re = (
        "Syntax error in input : unexpected end of expression (maybe due to unmatched parenthesis) at the end!"
    )

    def inspect(self):
        try:
            parser.parse(self.keyword, lexer=lexer)
        except ParseSyntaxError as e:
            if str(e) == self.unexpect_unmatched_re:
                if self.keyword.find(":") == len(self.keyword) - 1:
                    self.keyword = self.keyword[:-1]
                    self.set_illegal()
        except Exception:
            return


class UnknownOperatorInspector(BaseInspector):
    """修复未知运算符"""

    syntax_error_message = _("未知操作符")

    def inspect(self):
        try:
            parser.parse(self.keyword, lexer=lexer)
        except UnknownLuceneOperatorException:
            resolver = UnknownOperationResolver()
            self.keyword = str(resolver(parser.parse(self.keyword, lexer=lexer)))
            self.set_illegal()
        except Exception:
            return


class DefaultInspector(BaseInspector):
    """默认检查器, 用于最后检查语法错误是否被修复"""

    syntax_error_message = _("未知异常")

    def inspect(self):
        try:
            parser.parse(self.keyword, lexer=lexer)
            LuceneParser(keyword=self.keyword).parsing()
        except Exception:
            self.set_illegal()


class LuceneSyntaxResolver(object):
    """lucene语法检查以及修复器"""

    REGISTERED_INSPECTORS = [
        ChinesePunctuationInspector,
        # IllegalRangeInspector得放在前面是因为 RANGE 的语法会和 IllegalCharacterInspector 中的 TO 冲突
        IllegalRangeSyntaxInspector,
        IllegalCharacterInspector,
        IllegalColonInspector,
        IllegalBracketInspector,
        UnknownOperatorInspector,
        DefaultInspector,
    ]

    def __init__(self, keyword: str):
        self.keyword = keyword
        self.messages = []

    def inspect(self):
        messages = []
        for inspector_class in self.REGISTERED_INSPECTORS:
            inspector = inspector_class(self.keyword)
            inspector.inspect()
            self.keyword = inspector.keyword
            result = inspector.get_result()
            if not result.is_legal:
                messages.append(str(asdict(result)["message"]))
        if not messages:
            return True
        self.messages.extend(messages)

    def resolve(self):
        is_resolved = False
        for i in range(MAX_RESOLVE_TIMES):
            if self.inspect():
                is_resolved = True
                break
        self.messages = set(self.messages)
        if is_resolved and str(DefaultInspector.syntax_error_message) in self.messages:
            self.messages.remove(str(DefaultInspector.syntax_error_message))
        return {
            "is_legal": False if self.messages else True,
            "is_resolved": is_resolved,
            "message": "\n".join(self.messages),
            "keyword": self.keyword,
        }
