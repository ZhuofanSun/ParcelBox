from typing import List, Dict, Any

def convert_number(value, from_base, to_base):
    """
    进制转换函数（支持格式化输出）

    输入:
        value (str | int): 输入数字，允许包含空格
        from_base (int): 原进制（2 / 10 / 16）
        to_base (int): 目标进制（2 / 10 / 16）

    输出:
        str: 格式化后的字符串
    """

    # ---------- 1. 预处理输入 ----------
    # 转成字符串，并去掉所有空格
    value_str = str(value).replace(" ", "")

    # ---------- 2. 转成十进制 ----------
    decimal_value = int(value_str, from_base)

    # ---------- 3. 转成目标进制 ----------
    if to_base == 10:
        # 十进制：直接返回，不加空格
        return str(decimal_value)

    elif to_base == 2:
        # 二进制：去掉 '0b'
        bin_str = bin(decimal_value)[2:]

        # 从右往左，每 4 位一组
        groups = []
        while bin_str:
            groups.insert(0, bin_str[-4:])
            bin_str = bin_str[:-4]

        return " ".join(groups)

    elif to_base == 16:
        # 十六进制：去掉 '0x'，转大写
        hex_str = hex(decimal_value)[2:].upper()

        # 如果长度是奇数，前面补 0（保证两位一组）
        if len(hex_str) % 2 == 1:
            hex_str = "0" + hex_str

        # 每 2 位一组
        groups = []
        while hex_str:
            groups.append(hex_str[:2])
            hex_str = hex_str[2:]

        return " ".join(groups)

    else:
        raise ValueError("只支持 2 / 10 / 16 进制")


def split_binary(bin_str: str, segments: list[int]) -> list[str]:
    """
    按给定的位宽列表，从高位开始切分二进制字符串

    参数:
        bin_str (str): 二进制字符串，允许包含空格
        segments (list[int]): 每一段要切的位数（从高位开始）

    返回:
        list[str]: 切分后的二进制字符串列表（4 位一组空格）

    异常:
        ValueError: 位数不匹配或输入非法
    """

    # ---------- 1. 输入预处理 ----------
    # 去掉所有空格
    clean_bin = bin_str.replace(" ", "")

    # 校验是否只包含 0 / 1
    if not all(c in "01" for c in clean_bin):
        raise ValueError("输入包含非二进制字符")

    total_len = len(clean_bin)

    # ---------- 2. 校验位数是否匹配 ----------
    if sum(segments) != total_len:
        raise ValueError(
            f"位数不匹配：二进制长度为 {total_len}，"
            f"但 segments 总和为 {sum(segments)}"
        )

    # ---------- 3. 从高位开始切分 ----------
    result = []
    idx = 0

    for seg_len in segments:
        part = clean_bin[idx: idx + seg_len]
        idx += seg_len

        # ---------- 4. 格式化输出（4 位一组） ----------
        groups = []
        while part:
            groups.insert(0, part[-4:])
            part = part[:-4]

        result.append(" ".join(groups))

    return result

def length(num: str) -> int:
    return len(num.replace(" ", ""))

def pad_binary_zeros(bin_str: str, target_bits: int) -> str:
    """
    给二进制字符串左侧补 0，使其达到指定总位数（按去空格后的长度计算）

    参数:
        bin_str (str): 二进制字符串，允许包含空格
        target_bits (int): 期望补零后总位数（必须 >= 当前位数）

    返回:
        str: 补零后的二进制字符串（4 位一组空格）

    异常:
        ValueError: 输入非法 / target_bits 小于当前位数
    """

    # ---------- 1. 预处理输入 ----------
    clean = bin_str.replace(" ", "")

    # 校验只含 0/1
    if not all(c in "01" for c in clean):
        raise ValueError("输入包含非二进制字符")

    if target_bits < 0:
        raise ValueError("target_bits 不能为负数")

    cur_len = len(clean)

    # ---------- 2. 校验位数 ----------
    if target_bits < cur_len:
        raise ValueError(f"目标位数 {target_bits} 小于当前位数 {cur_len}")

    # ---------- 3. 左侧补 0 ----------
    padded = "0" * (target_bits - cur_len) + clean

    # ---------- 4. 格式化输出：从右往左每 4 位一组 ----------
    groups = []
    while padded:
        groups.insert(0, padded[-4:])
        padded = padded[:-4]

    return " ".join(groups)




def function_test():
    print(split_binary("1001 1100 1010 1111", [4, 8, 4]))


# 测试代码
if __name__ == "__main__":
    card_hex = "9e 00 00 1f c9 c4 ff 00 01 dc 38 10"
    card_bin = convert_number(card_hex, 16, 2)
    card_dec = convert_number(card_hex, 16, 10)

    target_dec = 11102851138
    target_bin = convert_number(target_dec, 10, 2)

    if target_bin.replace(" ", "") not in card_bin.replace(" ", ""):
        print(f"Target BIN {target_bin} not found in Card BIN {card_bin}")
    else:
        print(f"Target BIN {target_bin} found in Card BIN {card_bin}")


    print("Card HEX:", card_hex.upper())
    print("Card BIN:", card_bin)
    print("Card DEC:", card_dec)
    print(f"Card HEX Length: {length(card_hex)}")
    print(f"Card BIN Length: {length(card_bin)}")



