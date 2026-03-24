import time
import board
import busio
from adafruit_pn532.i2c import PN532_I2C
from adafruit_pn532.adafruit_pn532 import (
    MIFARE_CMD_AUTH_A,
    MIFARE_CMD_AUTH_B,
    _COMMAND_GETGENERALSTATUS,  # 注意：这是内部常量，你已经在看源码了，可以直接用
)
DEFAULT_KEY = b"\xFF\xFF\xFF\xFF\xFF\xFF"  # 最常见默认钥匙

pn532 = None

# 初始化 I2C 总线和 PN532
i2c = busio.I2C(board.SCL, board.SDA)

# 如果你接了 reset / req 引脚，在这里改成对应的 GPIO
# 比如:
# reset_pin = DigitalInOut(board.D6)
# req_pin = DigitalInOut(board.D12)
# 现在假设你没接，就传 None
reset_pin = None
req_pin = None

pn532 = PN532_I2C(i2c, debug=False, reset=reset_pin, req=req_pin)

# 调用 SAM_configuration()，进入正常读卡模式
pn532.SAM_configuration()

# 读取固件版本
ic, ver, rev, support = pn532.firmware_version
print(f"PN532 firmware: IC=0x{ic:02X}, Ver={ver}.{rev}, Support=0x{support:02X}")


# ===========================
def is_trailer_block(block):
    return block == 0 or (block + 1) % 4 == 0  # 0, 3,7,11,15, ...

def get_uid(timeout=10):
    """读取卡片 UID"""
    print("轮询读卡...")
    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout:
        uid = pn532.read_passive_target(timeout=0.5)  # 最多等 0.5 秒
        if uid is None:
            continue

        print("发现一张卡，UID:", uid.hex())
        return uid

    print("在指定时间内未找到卡片。")
    return None

def read_block(block_number: int, key: bytes = DEFAULT_KEY, key_type: int = MIFARE_CMD_AUTH_A):
    """读取 MIFARE Classic 块数据"""
    uid = get_uid()
    if uid is None:
        return None

    # 认证块
    if not pn532.mifare_classic_authenticate_block(uid, block_number, key_type, key):
        raise Exception(f"块 {block_number} 认证失败！")


    # 读取块
    block_data = pn532.mifare_classic_read_block(block_number)
    if block_data is None:
        raise Exception(f"块 {block_number} 读取失败！")


    # print(f"块 {block_number} 数据:", block_data.hex())
    return block_data

def write_block(block_number: int, data: str, key: bytes = DEFAULT_KEY, key_type: int = MIFARE_CMD_AUTH_A):
    """
    写入 MIFARE Classic 块数据
    data: 必须是 16 字节字符串
    """
    if is_trailer_block(block_number):
        raise Exception(f"块 {block_number} 是 sector trailer，禁止写入！")
    uid = get_uid()
    if uid is None:
        return False

    if len(data) != 16:
        raise ValueError("数据长度必须是 16 字节！")

    data = data.encode()

    # 认证块
    if not pn532.mifare_classic_authenticate_block(uid, block_number, key_type, key):
        raise Exception(f"块 {block_number} 认证失败！")


    # 写入块
    if not pn532.mifare_classic_write_block(block_number, data):
        raise Exception(f"块 {block_number} 写入失败！")

    print(f"块 {block_number} 写入成功。")
    return True

def fmt_value_block(block_number: int, initial_value: int = 0, address_block: int = None,
                    key: bytes = DEFAULT_KEY, key_type: int = MIFARE_CMD_AUTH_A):
    """格式化 MIFARE Classic 块为 value block"""
    if is_trailer_block(block_number):
        raise Exception(f"块 {block_number} 是 sector trailer，禁止写入！")
    uid = get_uid()
    if uid is None:
        return False

    # 认证块
    if not pn532.mifare_classic_authenticate_block(uid, block_number, key_type, key):
        raise Exception(f"块 {block_number} 认证失败！")


    # 格式化为 value block
    if not pn532.mifare_classic_fmt_value_block(block_number, initial_value, address_block or block_number):
        raise Exception(f"块 {block_number} 格式化为 value block 失败！")

    print(f"块 {block_number} 格式化为 value block 成功。")
    return True

def fmt_data_block(block_number: int, initial_data: str = "\x00" * 16,
                   key: bytes = DEFAULT_KEY, key_type: int = MIFARE_CMD_AUTH_A):
    """格式化 MIFARE Classic 块为全 0 初始数据块"""
    if is_trailer_block(block_number):
        raise Exception(f"块 {block_number} 是 sector trailer，禁止写入！")

    uid = get_uid()
    if uid is None:
        return False

    # 认证块
    if not pn532.mifare_classic_authenticate_block(uid, block_number, key_type, key):
        raise Exception(f"块 {block_number} 认证失败！")

    # 格式化为普通数据块
    if not pn532.mifare_classic_write_block(block_number, initial_data.encode()):
        raise Exception(f"块 {block_number} 格式化为数据块失败！")
    print(f"块 {block_number} 格式化为数据块成功。")
    return True

def key_A_testRead():
    """
    对 sector 2 的 trailer（block 11）做一个小测试：
    1. 读当前 trailer
    2. 把 Key A 改成一个新值（例如 01 02 03 04 05 06）
    3. 用新 Key A 测试认证 sector2 的数据块（block 8）
    4. 再把 Key A 改回 FF FF FF FF FF FF
    """
    SECTOR2_TRAILER_BLOCK = 11
    SECTOR2_DATABLOCK = 8  # 用来测试认证的普通数据块

    KEY_FFFF = b"\xFF" * 6

    uid = get_uid()
    if uid is None:
        return

    block_trailer = SECTOR2_TRAILER_BLOCK
    test_block = SECTOR2_DATABLOCK

    print("\n=== 第一步：用 KeyB=FF.. 认证 sector2 trailer 并读取 ===")
    # 用 Key A = FF FF FF FF FF FF 认证 trailer
    if not pn532.mifare_classic_authenticate_block(uid, block_trailer, MIFARE_CMD_AUTH_A, KEY_FFFF):
        print("认证失败")
        return

    trailer_before = pn532.mifare_classic_read_block(block_trailer)
    if trailer_before is None:
        print("读取 trailer 失败。")
        return

    print(f"原始 trailer (block 11): {trailer_before.hex()}")

    # 按结构拆开：注意 Key A 虽然读出来是 00..，但这只是屏蔽值，不是真实 key
    key_a_masked = trailer_before[0:6]
    access_bits_gpb = trailer_before[6:10]  # FF 07 80 69 这 4 字节
    key_b_real = trailer_before[10:16]

    print("（读到的）Key A 字节:", key_a_masked.hex(), "(可能被屏蔽为 00..)")
    print("Access Bits + GPB:", access_bits_gpb.hex())
    print("Key B 字节:", key_b_real.hex())

    # --- 构造一个新的 Key A（测试用），比如 01 02 03 04 05 06 ---
    new_key_a = b"\x01\x02\x03\x04\x05\x06"

    # 构造新的 trailer：KeyA(new) + AccessBits+GPB(原样) + KeyB(原样)
    new_trailer = new_key_a + access_bits_gpb + key_b_real
    print("\n=== 第二步：写入新的 Key A（01 02 03 04 05 06）到 sector2 trailer ===")
    print("准备写入的 trailer 数据:", new_trailer.hex())

    # 写入前还是用原始key A 认证
    if not pn532.mifare_classic_authenticate_block(uid, block_trailer, MIFARE_CMD_AUTH_A, KEY_FFFF):
        print("认证失败 2")
        return

    if not pn532.mifare_classic_write_block(block_trailer, new_trailer):
        print("写入新的 Key A 失败！（mifare_classic_write_block 返回 False）")
        return

    print("新的 Key A 已写入（注意读取时仍然会被屏蔽）。")

    # 这里用新 key A 认证
    if pn532.mifare_classic_authenticate_block(uid, block_trailer, MIFARE_CMD_AUTH_A, new_key_a):
        trailer_mid = pn532.mifare_classic_read_block(block_trailer)
        print("修改 Key A 后读取到的 trailer:", trailer_mid.hex())

    # --- 把 Key A 改回 FF FF FF FF FF FF ---
    print("\n=== 第三步：把 Key A 改回 FF FF FF FF FF FF ===")
    orig_key_a = KEY_FFFF  # 你想恢复成全 FF

    restore_trailer = orig_key_a + access_bits_gpb + key_b_real
    print("准备写回的 trailer:", restore_trailer.hex())

    # 再次用新 key A 认证 trailer，然后写回
    if not pn532.mifare_classic_authenticate_block(uid, block_trailer, MIFARE_CMD_AUTH_A, new_key_a):
        print("认证失败 3")
        return

    if not pn532.mifare_classic_write_block(block_trailer, restore_trailer):
        print("写回原始 Key A 失败！")
        return

    print("Key A 已恢复为 FF FF FF FF FF FF。")

    # 验证一下：用 KeyA=FF.. 去认证 sector2 的数据块
    print("\n=== 第四步：用 KeyA=FF.. 再次认证 block 8 测试 ===")
    if pn532.mifare_classic_authenticate_block(uid, test_block, MIFARE_CMD_AUTH_A, KEY_FFFF):
        print(f"恢复后使用 KeyA=FF.. 认证 block {test_block} 成功。")
        data2 = pn532.mifare_classic_read_block(test_block)
        print(f"block {test_block} 当前数据: {data2.hex() if data2 else None}")
    else:
        print(f"恢复后使用 KeyA=FF.. 认证 block {test_block} 失败，说明恢复过程有问题。")





def little_test():
    dataTest = read_block(4)
    print("读取到的数据:", dataTest)
    writeResult = write_block(4, "1234567890ABCDEF")
    print("写入结果:", writeResult)
    dataTest2 = read_block(4)
    print("重新读取到的数据:", dataTest2)
    print()

    if pn532.mifare_classic_check_value_block(5):
        print("块 5 是一个有效的 value block。")
    else:
        print("块 5 不是一个有效的 value block。")

    fmtResult = fmt_value_block(5, initial_value=50)
    print("格式化结果:", fmtResult)

    if pn532.mifare_classic_check_value_block(5):
        print("块 5 是一个有效的 value block。")
        value = pn532.mifare_classic_get_value_block(5)
        print("块 5 的值为:", value)
    else:
        print("块 5 不是一个有效的 value block。")



def dump_mifare_1k_card():
    """
    读取整张 MIFARE Classic 1K 卡：
    - 对每个扇区只认证一次
    - 认证成功后读取 4 个 block（含 trailer）
    返回一个 dict:
    {
        sector_number: {
            "auth": {
                "ok": True/False,
                "key_type": MIFARE_CMD_AUTH_A/B or None,
                "key": b"...",
                "label": "KeyA_FF" ...
            },
            "blocks": {
                block_number: bytes 或 "AUTH_FAIL"/"READ_FAIL"
            }
        },
        ...
    }
    """
    card_data = {}
    uid = get_uid()
    if uid is None:
        return card_data

    for sector in range(16):  # MIFARE Classic 1K 有 16 个扇区
        sector_info = {"auth": None, "blocks": {}}
        block_start = sector * 4
        block_trailer = block_start + 3

        # 先尝试用 Key A 认证
        if pn532.mifare_classic_authenticate_block(uid, block_trailer, MIFARE_CMD_AUTH_A, DEFAULT_KEY):
            sector_info["auth"] = {
                "ok": True,
                "key_type": MIFARE_CMD_AUTH_A,
                "key": DEFAULT_KEY,
                "label": "KeyA_FF"
            }
        # 再尝试用 Key B 认证
        elif pn532.mifare_classic_authenticate_block(uid, block_trailer, MIFARE_CMD_AUTH_B, DEFAULT_KEY):
            sector_info["auth"] = {
                "ok": True,
                "key_type": MIFARE_CMD_AUTH_B,
                "key": DEFAULT_KEY,
                "label": "KeyB_FF"
            }
        else:
            sector_info["auth"] = {
                "ok": False,
                "key_type": None,
                "key": None,
                "label": None
            }

        # 读取该扇区的 4 个块
        for block_offset in range(4):
            block_number = block_start + block_offset
            if sector_info["auth"]["ok"]:
                block_data = pn532.mifare_classic_read_block(block_number)
                if block_data is not None:
                    sector_info["blocks"][block_number] = block_data
                else:
                    sector_info["blocks"][block_number] = "READ_FAIL"
            else:
                sector_info["blocks"][block_number] = "AUTH_FAIL"

        card_data[sector] = sector_info

    return card_data
def print_mifare_dump(card):
    """
    以美观格式打印 dump_mifare_1k_card() 的结果
    """

    print("\n==================== MIFARE Classic 1K Dump ====================\n")

    for sector, info in card.items():
        auth = info["auth"]

        # —— Sector Header ——————————————————————————————
        print(f"● Sector {sector:02d}")
        print("  Auth Status :", "OK" if auth["ok"] else "FAILED")
        if auth["ok"]:
            key_name = "Key A" if auth["key_type"] == MIFARE_CMD_AUTH_A else "Key B"
            key_hex = auth["key"].hex()
            print(f"  Used Key    : {key_name}  ({key_hex})")
        print("")

        # —— Blocks ——————————————————————————————
        for block_num, data in info["blocks"].items():

            is_trailer = ((block_num + 1) % 4 == 0)
            block_label = "TRAILER" if is_trailer else "DATA   "

            if isinstance(data, bytearray):
                # 转为更易读的格式："xx xx xx ..."
                hex_data = " ".join(f"{b:02X}" for b in data)
            else:
                # AUTH_FAIL / READ_FAIL
                hex_data = data

            print(f"    Block {block_num:02d}  [{block_label}] : {hex_data}")

        print("\n----------------------------------------------------------------\n")
card = dump_mifare_1k_card()
print_mifare_dump(card)


# key_A_testRead()

