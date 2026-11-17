"""中文 ASR 评测的文本归一化。

为什么必须归一化
----------------
识别结果与参考文本之间存在**纯格式性**的差异：句尾多一个句号、
中间的停顿被识别成逗号、中英文之间多一个空格。

这些差异与"识别得准不准"毫无关系，但用严格相等判定会让准确率恒为 0 ——
实测曾出现"逐字全对、只多一个句号"却判 0% 的情况。

所有中文 ASR 评测的标准做法都是先归一化再比对。本模块把归一化规则
显式写出来并用测试钉住，避免"归一化规则随实现漂移"导致指标不可比。

归一化做三件事
--------------
1. 全角字符转半角；
2. 去掉标点（中英文常见标点）；
3. 去掉所有空白。

**不做的事**：不转繁简、不纠错别字、不做同义词归一 ——
那些属于"识别错了"，必须计入错误，否则评测就失去了意义。
"""

from __future__ import annotations

import re

# 中英文常见标点。逐个列出而不是用 Unicode 类别 ——
# Unicode 的 ``P`` 类别还包含连接符等"不该删"的符号，
# 删掉它们会把"3-4层"变成"34层"，制造出参考文本自身就没有的错误。
PUNCTUATION_PATTERN = re.compile(
    r"[,.;:!?、，。；：！？…—·「」『』《》（）()\[\]{}【】\"'"
    r"“”‘’～~`@#$%\^&\*_+=|<>/\\]"
)

# 空白字符。全角空格也在内 —— 中文里全角空格很常见。
WHITESPACE_PATTERN = re.compile(r"\s+")

# 全角 ASCII 字符转半角的偏移量。
FULLWIDTH_ASCII_OFFSET = 0xFEE0

# 全角空格对应的半角空格。
FULLWIDTH_SPACE = 0x3000

# 中文数字到阿拉伯数字的对照。只收口语中真正读作数字的字。
CHINESE_DIGITS: dict[str, int] = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

# 中文数字单位。单位本身也有读音（三号线 / 十元 / 二十三）。
CHINESE_UNITS: dict[str, int] = {
    "十": 10, "百": 100, "千": 1000,
}

# 大单位。单独处理，用于跨节累加。
CHINESE_SECTIONS: dict[str, int] = {
    "万": 10_000, "亿": 100_000_000,
}

# 数字字符集合（用于识别"数词串"）。
CHINESE_NUMBER_CHARS = set(CHINESE_DIGITS) | set(CHINESE_UNITS) | set(CHINESE_SECTIONS)

# 可跟在数词后面的量词/单位标记。
#
# **为什么必须有这些标记**：中文里"一"极常用作序数或虚指
# （"一下"、"一直"、"不一样"）。无条件地把"一"换成"1"，
# 会把这些词改坏，归一化反而制造出参考文本自身没有的错误。
# 要求数词后面跟着明确的量词，才能确定它读作数字。
QUANTIFIER_AFTER_NUMBER = "点号线层楼天年月日号次倍成万亿"

# 数词串（至少两个字符）直接判作数字。
#
# 长度下限为 2：单字情况交给上面的量词规则判断，
# 避免"一直""一下"被误判。
CHINESE_NUMBER_SEQUENCE = re.compile(
    r"[零〇一二三四五六七八九十百千万亿两]{2,}"
)

# 数词 + 量词标记。
CHINESE_NUMBER_WITH_QUANTIFIER = re.compile(
    r"[零〇一二三四五六七八九十百千万亿两]+[" + QUANTIFIER_AFTER_NUMBER + r"]"
)

# "第" + 数词（序数）。
CHINESE_ORDINAL = re.compile(r"第[零〇一二三四五六七八九十百千万亿两]+")


def to_half_width(text: str) -> str:
    """把全角 ASCII 字符转成半角。

    @param text 待转换文本
    @return 转换后的文本
    """
    return "".join(
        chr(ord(char) - FULLWIDTH_ASCII_OFFSET)
        if 0xFF01 <= ord(char) <= 0xFF5E
        else char
        for char in text
    )


def chinese_number_to_int(text: str) -> int | None:
    """把中文数字串转成整数。

    支持"十""二十三""一百五十""三万二"这类写法。

    @param text 中文数字串
    @return 数值；无法解析时返回 None
    """
    if not text:
        return None

    total = 0
    section = 0
    number = 0

    for char in text:
        if char in CHINESE_DIGITS:
            number = CHINESE_DIGITS[char]
            continue
        if char in CHINESE_UNITS:
            unit = CHINESE_UNITS[char]
            # "十五"：前面没有数字时，单位自身就是基数（十 = 10）。
            section += (number if number else 1) * unit
            number = 0
            continue
        if char in CHINESE_SECTIONS:
            section = (section + number) * CHINESE_SECTIONS[char]
            total += section
            section = 0
            number = 0
            continue
        # 出现非数字字符（如"两"之外的助词），整串放弃。
        return None

    return total + section + number


def normalize_chinese_numbers(text: str) -> str:
    """把中文数字转成阿拉伯数字。

    **为什么要做**：ASR 输出的数字形式不稳定 ——
    同一句话可能识别成"地铁三号线"或"地铁3号线"。
    两者读音完全相同，写作形式不同，把它们算成识别错误是评测口径的缺陷，
    不是模型能力的缺陷。

    **为什么保守**：中文里"一"极常用作虚指或序数（"一下""一直""不一样"）。
    无条件转换会把这些词改坏。因此只转换两种可确定的情形：
    连续两个及以上的中文数字字符，或中文数字后紧跟明确的量词标记。

    @param text 待转换文本
    @return 转换后的文本
    """
    if not text:
        return text

    def replace_sequence(match: re.Match) -> str:
        value = chinese_number_to_int(match.group(0))
        return str(value) if value is not None else match.group(0)

    def replace_with_quantifier(match: re.Match) -> str:
        # 把末尾的量词标记剥离出来，只转换数字部分。
        body = match.group(0)
        quantifier = body[-1]
        value = chinese_number_to_int(body[:-1])
        if value is None:
            return body
        return f"{value}{quantifier}"

    def replace_ordinal(match: re.Match) -> str:
        body = match.group(0)
        value = chinese_number_to_int(body[1:])
        return f"第{value}" if value is not None else body

    result = CHINESE_ORDINAL.sub(replace_ordinal, text)
    result = CHINESE_NUMBER_WITH_QUANTIFIER.sub(replace_with_quantifier, result)
    result = CHINESE_NUMBER_SEQUENCE.sub(replace_sequence, result)
    return result


def normalize_text(text: str) -> str:
    """归一化识别文本与参考文本。

    @param text 待归一化文本
    @return 归一化后的文本
    """
    if not text:
        return ""

    # 全角空格先转半角，否则它会被当成普通空白删掉（结果相同，但顺序更清晰）。
    converted = text.replace(chr(FULLWIDTH_SPACE), " ")
    converted = to_half_width(converted)

    without_punctuation = PUNCTUATION_PATTERN.sub("", converted)
    compact = WHITESPACE_PATTERN.sub("", without_punctuation)
    return normalize_chinese_numbers(compact)


def is_exact_match(reference: str, hypothesis: str) -> bool:
    """判定识别结果与参考文本是否一致（按归一化口径）。

    @param reference 参考文本
    @param hypothesis 识别文本
    @return 归一化后相等时为 True
    """
    return normalize_text(reference) == normalize_text(hypothesis)
