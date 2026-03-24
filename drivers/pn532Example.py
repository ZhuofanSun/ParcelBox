import time
import struct

import board
import busio
from digitalio import DigitalInOut, Direction

from adafruit_pn532.i2c import PN532_I2C
from adafruit_pn532.adafruit_pn532 import (
    MIFARE_CMD_AUTH_A,
    MIFARE_CMD_AUTH_B,
    _COMMAND_GETGENERALSTATUS,  # 注意：这是内部常量，你已经在看源码了，可以直接用
)


# ===========================
# 1. 初始化 PN532
# ===========================

def init_pn532():
    """初始化 I2C 总线和 PN532，对应你之前的用法。"""
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

    return pn532


# ===========================
# 2. 简单轮询读卡（read_passive_target）
# ===========================

def demo_read_uid(pn532):
    """最简单的读 UID 示例，使用 read_passive_target()."""
    print("== Demo 1: 简单轮询读卡 ==")
    print("放卡...")
    while True:
        uid = pn532.read_passive_target(timeout=0.5)  # 最多等 0.5 秒
        if uid is None:
            time.sleep(0.5)
            continue

        print("发现一张卡，UID:", uid.hex())
        break  # 只读一次就退出示例


# ===========================
# 3. 分步读卡（listen_for_passive_target + get_passive_target）
#    方便以后配合 IRQ 使用
# ===========================

def demo_listen_and_get(pn532):
    """
    演示 listen_for_passive_target + get_passive_target 的用法。
    read_passive_target就是这两个函数的封装。
    """
    print("\n== Demo 2: 分步寻卡（listen_for_passive_target + get_passive_target） ==")

    # 第一步：让 PN532 进入“监听模式”
    ok = pn532.listen_for_passive_target(timeout=1.0)
    if not ok:
        print("发送 InListPassiveTarget 命令失败（可能忙/超时）")
        return

    print("已经开始监听，请把卡放到天线附近，1 秒内有效...")

    # 第二步：等待响应（这里用轮询，之后你可以改成 IRQ 触发）
    uid = pn532.get_passive_target(timeout=1.0)
    if uid is None:
        print("在 timeout 时间内没等到卡。")
        return

    print("get_passive_target 得到 UID:", uid.hex())


# ===========================
# 4. Mifare Classic：Value Block 示例
#    包含：认证 + 格式化为 value block + 读写 value + 普通 block 读写
# ===========================

DEFAULT_KEY = b"\xFF\xFF\xFF\xFF\xFF\xFF"  # 最常见默认钥匙


def demo_mifare_value_block(pn532):
    print("\n== Demo 3: Mifare Classic Value Block 示例 ==")
    print("请将一张 Mifare Classic 卡放在天线附近...")

    uid = pn532.read_passive_target(timeout=2.0)
    if uid is None:
        print("没找到卡，退出 demo_mifare_value_block")
        return

    print("UID:", uid.hex())

    # 假设我们要用 block 8 做 value block（确保这块是数据块而不是 sector trailer）
    block_num = 8

    # 1) 用 Key A 认证这个 block
    print(f"对 block {block_num} 做 Key A 认证...")
    if not pn532.mifare_classic_authenticate_block(uid, block_num, MIFARE_CMD_AUTH_A, DEFAULT_KEY):
        print("认证失败，可能不是 Classic 卡 / 密钥不对 / block 非数据块")
        return
    print("认证成功。")

    # 2) 先尝试把这个 block 格式化成 value block，初始值 100
    print("格式化该 block 为 value block，初始值=100...")
    if not pn532.mifare_classic_fmt_value_block(block_num, initial_value=100, address_block=block_num):
        print("格式化失败（写 block 失败）")
        return
    print("格式化完成。")

    # 3) 读取当前 value
    try:
        balance = pn532.mifare_classic_get_value_block(block_num)
        print("当前 value block 中的值:", balance)
    except RuntimeError as e:
        print("读取 value block 结构失败:", e)
        return

    # 4) 尝试加值 +20
    print("对该 value block +20 ...")
    if pn532.mifare_classic_add_value_block(block_num, 20):
        new_balance = pn532.mifare_classic_get_value_block(block_num)
        print("加值后余额:", new_balance)
    else:
        print("加值失败。")

    # 5) 再减值 -5
    print("对该 value block -5 ...")
    if pn532.mifare_classic_sub_value_block(block_num, 5):
        new_balance = pn532.mifare_classic_get_value_block(block_num)
        print("减值后余额:", new_balance)
    else:
        print("减值失败。")

    # 6) 顺便演示一下普通 block 的读写（例如 block 4）
    data_block = 4
    print(f"\n顺便演示普通 block {data_block} 的读写...")

    # 认证 block 4
    if not pn532.mifare_classic_authenticate_block(uid, data_block, MIFARE_CMD_AUTH_A, DEFAULT_KEY):
        print("对 block 4 认证失败，跳过读写示例。")
        return

    # 读取原始 block 数据
    original = pn532.mifare_classic_read_block(data_block)
    print(f"block {data_block} 原始数据:", original.hex() if original else None)

    # 写入 16 字节测试数据
    new_data = b"HelloPN532World!"  # 恰好 16 字节
    if pn532.mifare_classic_write_block(data_block, new_data):
        print(f"写入 block {data_block} 成功。")
        reread = pn532.mifare_classic_read_block(data_block)
        print(f"block {data_block} 重新读取:", reread.hex() if reread else None)
    else:
        print("写入 block 失败。")


# ===========================
# 5. NTAG2xx 读写示例（Type 2 Tag）
# ===========================

def demo_ntag2xx(pn532):
    print("\n== Demo 4: NTAG2xx 读写示例 ==")
    print("请放一张 NTAG213/215/216 或类似 Type 2 标签...")

    uid = pn532.read_passive_target(timeout=2.0)
    if uid is None:
        print("没找到标签，退出 demo_ntag2xx。")
        return
    print("UID:", uid.hex())

    # 这里只是简单示例，真实使用时最好先确认卡类型；
    # 现在假定你放的是 NTAG / Ultralight
    page = 4  # 通常 4 开始是用户数据区域（不同 NTAG 型号稍有差异）
    print(f"读取 page {page} ...")
    data = pn532.ntag2xx_read_block(page)
    print(f"原始数据: {data.hex() if data else None}")

    # 写入 4 字节测试数据
    new_page_data = b"\x01\x02\x03\x04"
    print(f"写入 page {page} -> {new_page_data.hex()}")
    if pn532.ntag2xx_write_block(page, new_page_data):
        reread = pn532.ntag2xx_read_block(page)
        print("重新读取:", reread.hex() if reread else None)
    else:
        print("写入失败。")


# ===========================
# 6. 底层 call_function / send_command / process_response 示例
#    以 GETGENERALSTATUS 命令为例
# ===========================

def demo_low_level_call(pn532):
    print("\n== Demo 5: 底层 call_function / send_command / process_response 示例 ==")

    # --- 方式一：直接 call_function ---
    # GETGENERALSTATUS 返回 0xD5 0x05 开头 + 一堆状态数据
    resp = pn532.call_function(_COMMAND_GETGENERALSTATUS, response_length=8)
    print("call_function GETGENERALSTATUS 返回:", resp)

    # --- 方式二：手动 send_command + process_response ---
    # 没有参数，所以 params 为空
    if not pn532.send_command(_COMMAND_GETGENERALSTATUS, params=b"", timeout=1.0):
        print("send_command 发送失败或没收到 ACK")
        return

    resp2 = pn532.process_response(_COMMAND_GETGENERALSTATUS, response_length=8, timeout=1.0)
    print("send_command + process_response 返回:", resp2)

    # 理论上 resp 和 resp2 内容应相同


# ===========================
# 7. power_down / reset 示意
# ===========================

def demo_power_reset(pn532):
    print("\n== Demo 6: power_down / reset 示意 ==")
    print("让 PN532 进入低功耗，然后再 reset 唤醒（仅示例调用顺序）。")

    # 进入低功耗（PN532 文档里有具体行为，库内封装了命令）
    pn532.power_down()
    print("已调用 power_down()。此时读卡很可能会失败。")

    time.sleep(1.0)

    # 用 reset() + SAM_configuration() 回到正常模式
    pn532.reset()
    pn532.SAM_configuration()
    print("已 reset 并重新 SAM_configuration()。")


# ===========================
# main 函数：依次跑几个 demo
# ===========================

def main():
    pn532 = init_pn532()

    # 可按需注释掉某些 demo

    demo_read_uid(pn532)
    demo_listen_and_get(pn532)

    # 下面两个分别针对 Classic 卡 和 NTAG 卡，
    # 实际用的时候你可以按放的卡类型来决定调用哪个。
    demo_mifare_value_block(pn532)
    # demo_ntag2xx(pn532)

    demo_low_level_call(pn532)
    demo_power_reset(pn532)

    print("\n全部 demo 跑完。")


if __name__ == "__main__":
    main()