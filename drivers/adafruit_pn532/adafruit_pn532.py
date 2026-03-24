# SPDX-FileCopyrightText: 2015-2018 Tony DiCola for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
``adafruit_pn532``
====================================================

This module will let you communicate with a PN532 RFID/NFC shield or breakout
using I2C, SPI or UART.

* Author(s): Original Raspberry Pi code by Tony DiCola, CircuitPython by ladyada

Implementation Notes
--------------------

**Hardware:**

* Adafruit `PN532 Breakout <https://www.adafruit.com/product/364>`_
* Adafruit `PN532 Shield <https://www.adafruit.com/product/789>`_

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://github.com/adafruit/circuitpython/releases
* Adafruit's Bus Device library: https://github.com/adafruit/Adafruit_CircuitPython_BusDevice
"""

import struct
import time

from digitalio import Direction
from micropython import const

try:
    from typing import Optional, Tuple, Union

    from circuitpython_typing import ReadableBuffer
    from digitalio import DigitalInOut
    from typing_extensions import Literal
except ImportError:
    pass

__version__ = "2.4.6"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_PN532.git"

"""
https://www.nxp.com/docs/en/user-guide/141520.pdf
00 | 00 | FF | LEN | LCS | TFI | PD0 | PD1 | ... | PDn | DCS | 00

PREAMBLE 1 byte4
START CODE 2 bytes (0x00 and 0xFF),
LEN 1 byte indicating the number of bytes in the data field
(TFI and PD0 to PDn),

LCS 1 Packet Length Checksum LCS byte that satisfies the relation:
Lower byte of [LEN + LCS] = 0x00,

TFI 1 byte frame identifier, the value of this byte depends
on the way of the message
- D4h in case of a frame from the host controller to the PN532,
- D5h in case of a frame from the PN532 to the host controller.

DATA LEN-1 bytes of Packet Data Information
The first byte PD0 is the Command Code,

DCS 1 Data Checksum DCS byte that satisfies the relation:
Lower byte of [TFI + PD0 + PD1 + … + PDn + DCS] = 0x00,

POSTAMBLE 1 byte2
.
"""

_PREAMBLE = const(0x00)  # Preamble，固定值
# Start of Packet Code，固定 0x00FF
_STARTCODE1 = const(0x00)
_STARTCODE2 = const(0xFF)
_POSTAMBLE = const(0x00)  # Postamble，固定值

# TFI 帧方向
_HOSTTOPN532 = const(0xD4)  # From Host to PN532
_PN532TOHOST = const(0xD5)  # From PN532 to Host

# PN532 Commands PD0 见 manual table 12. Command Set
# https://www.nxp.com/docs/en/user-guide/141520.pdf

# Miscellaneous
_COMMAND_DIAGNOSE = const(0x00)  # 诊断
_COMMAND_GETFIRMWAREVERSION = const(0x02)  # 获取固件版本
_COMMAND_GETGENERALSTATUS = const(0x04)  # 获取通用状态
_COMMAND_READREGISTER = const(0x06)  # 读取寄存器
_COMMAND_WRITEREGISTER = const(0x08)  # 写入寄存器
_COMMAND_READGPIO = const(0x0C)  # 读取GPIO
_COMMAND_WRITEGPIO = const(0x0E)  # 写入GPIO
_COMMAND_SETSERIALBAUDRATE = const(0x10)  # 设置串口波特率
_COMMAND_SETPARAMETERS = const(0x12)  # 设置参数
_COMMAND_SAMCONFIGURATION = const(0x14)  # SAM配置
_COMMAND_POWERDOWN = const(0x16)  # 进入低功耗模式

# RF Communication
_COMMAND_RFCONFIGURATION = const(0x32)  # RF配置
_COMMAND_RFREGULATIONTEST = const(0x58)  # RF调节测试

# Initiator
_COMMAND_INJUMPFORDEP = const(0x56)  # 进入DEP模式
_COMMAND_INJUMPFORPSL = const(0x46)  # 进入PSL模式
_COMMAND_INLISTPASSIVETARGET = const(0x4A)  # 列出被动目标
_COMMAND_INATR = const(0x50)  # ATR
_COMMAND_INPSL = const(0x4E)  # PSL
_COMMAND_INDATAEXCHANGE = const(0x40)  # 数据交换
_COMMAND_INCOMMUNICATETHRU = const(0x42)  # 通过PN532进行通信
_COMMAND_INDESELECT = const(0x44)  # 取消选择
_COMMAND_INRELEASE = const(0x52)  # 释放
_COMMAND_INSELECT = const(0x54)  # 选择
_COMMAND_INAUTOPOLL = const(0x60)  # 自动轮询

# Target
_COMMAND_TGINITASTARGET = const(0x8C)  # 初始化为目标
_COMMAND_TGSETGENERALBYTES = const(0x92)  # 设置通用字节
_COMMAND_TGGETDATA = const(0x86)  # 获取数据
_COMMAND_TGSETDATA = const(0x8E)  # 设置数据
_COMMAND_TGSETMETADATA = const(0x94)  # 设置元数据
_COMMAND_TGGETINITIATORCOMMAND = const(0x88)  # 获取发起者命令
_COMMAND_TGRESPONSETOINITIATOR = const(0x90)  # 响应发起者
_COMMAND_TGGETTARGETSTATUS = const(0x8A)  # 获取目标状态

_RESPONSE_INDATAEXCHANGE = const(0x41)  # InDataExchange response (40h + 1)
_RESPONSE_INLISTPASSIVETARGET = const(0x4B)  # InListPassiveTarget response (4Ah + 1)

_WAKEUP = const(0x55)

_MIFARE_ISO14443A = const(0x00)

# Mifare Commands Page 130 of PN532 User Manual 通过 PN532 发送给 Mifare 卡本身的指令
MIFARE_CMD_AUTH_A = const(0x60)  # 用于认证的命令 A 密钥
MIFARE_CMD_AUTH_B = const(0x61)  # 用于认证的命令 B 密钥
MIFARE_CMD_READ = const(0x30)  # 读取命令 16 bytes reading
MIFARE_CMD_WRITE = const(0xA0)  # 写入命令 16 bytes writing
MIFARE_CMD_TRANSFER = const(0xB0)  # 传输命令
MIFARE_CMD_DECREMENT = const(0xC0)  # 递减命令
MIFARE_CMD_INCREMENT = const(0xC1)  # 递增命令
MIFARE_CMD_STORE = const(0xC2)  # 存储命令
MIFARE_ULTRALIGHT_CMD_WRITE = const(0xA2)  # 超轻量级写入命令 4 bytes writing

# Prefixes for NDEF Records (to identify record type) 不知道这是什么
NDEF_URIPREFIX_NONE = const(0x00)
NDEF_URIPREFIX_HTTP_WWWDOT = const(0x01)
NDEF_URIPREFIX_HTTPS_WWWDOT = const(0x02)
NDEF_URIPREFIX_HTTP = const(0x03)
NDEF_URIPREFIX_HTTPS = const(0x04)
NDEF_URIPREFIX_TEL = const(0x05)
NDEF_URIPREFIX_MAILTO = const(0x06)
NDEF_URIPREFIX_FTP_ANONAT = const(0x07)
NDEF_URIPREFIX_FTP_FTPDOT = const(0x08)
NDEF_URIPREFIX_FTPS = const(0x09)
NDEF_URIPREFIX_SFTP = const(0x0A)
NDEF_URIPREFIX_SMB = const(0x0B)
NDEF_URIPREFIX_NFS = const(0x0C)
NDEF_URIPREFIX_FTP = const(0x0D)
NDEF_URIPREFIX_DAV = const(0x0E)
NDEF_URIPREFIX_NEWS = const(0x0F)
NDEF_URIPREFIX_TELNET = const(0x10)
NDEF_URIPREFIX_IMAP = const(0x11)
NDEF_URIPREFIX_RTSP = const(0x12)
NDEF_URIPREFIX_URN = const(0x13)
NDEF_URIPREFIX_POP = const(0x14)
NDEF_URIPREFIX_SIP = const(0x15)
NDEF_URIPREFIX_SIPS = const(0x16)
NDEF_URIPREFIX_TFTP = const(0x17)
NDEF_URIPREFIX_BTSPP = const(0x18)
NDEF_URIPREFIX_BTL2CAP = const(0x19)
NDEF_URIPREFIX_BTGOEP = const(0x1A)
NDEF_URIPREFIX_TCPOBEX = const(0x1B)
NDEF_URIPREFIX_IRDAOBEX = const(0x1C)
NDEF_URIPREFIX_FILE = const(0x1D)
NDEF_URIPREFIX_URN_EPC_ID = const(0x1E)
NDEF_URIPREFIX_URN_EPC_TAG = const(0x1F)
NDEF_URIPREFIX_URN_EPC_PAT = const(0x20)
NDEF_URIPREFIX_URN_EPC_RAW = const(0x21)
NDEF_URIPREFIX_URN_EPC = const(0x22)
NDEF_URIPREFIX_URN_NFC = const(0x23)

_GPIO_VALIDATIONBIT = const(0x80)
_GPIO_P30 = const(0)
_GPIO_P31 = const(1)
_GPIO_P32 = const(2)
_GPIO_P33 = const(3)
_GPIO_P34 = const(4)
_GPIO_P35 = const(5)

_ACK = b"\x00\x00\xff\x00\xff\x00"
_FRAME_START = b"\x00\x00\xff"


class BusyError(Exception):
    """
    Base class for exceptions in this module.
    用来做抛出不那么严重的忙碌错误，至少是可预见的
    """


class PN532:
    """
    PN532 driver base, must be extended for I2C/SPI/UART interfacing
    负责协议层，具体传输在子类里实现
    """

    def __init__(
        self,
        *,
        debug: bool = False,
        irq: Optional[DigitalInOut] = None,
        reset: Optional[DigitalInOut] = None,
    ) -> None:
        """
        Create an instance of the PN532 class
        debug: 是否打印调试信息
        irq: 一个连接到 PN532 IRQ 引脚 的 DigitalInOut 对象。可以不用轮询 wait_ready，用 IRQ pin 检测有卡，再来读 UID，减少轮询时间
        reset: 一个连接到 PN532 RST 引脚 的 DigitalInOut。有它的话，驱动可以通过软件控制：上电后硬件复位一下 PN532或在出错后强制 reset 芯片
        """
        self.low_power = True  # 初始化时处于低功耗状态
        self.debug = debug
        self._irq = irq
        self._reset_pin = reset
        self.reset()
        _ = self.firmware_version

# 四个抽象方法，子类必须实现

    def _read_data(self, count: int) -> Union[bytes, bytearray]:
        # Read raw data from device, not including status bytes:
        # Subclasses MUST implement this!
        raise NotImplementedError

    def _write_data(self, framebytes: bytes) -> None:
        # Write raw bytestring data to device, not including status bytes:
        # Subclasses MUST implement this!
        raise NotImplementedError

    def _wait_ready(self, timeout: float) -> bool:
        # Check if busy up to max length of 'timeout' seconds
        # Subclasses MUST implement this!
        raise NotImplementedError

    def _wakeup(self) -> None:
        # Send special command to wake up
        raise NotImplementedError

    def reset(self) -> None:
        """
        Perform a hardware reset toggle and then wake up the PN532
        硬件复位，然后唤醒 PN532
        要用的话把RSTO接到某个 GPIO，然后在代码中把这个 GPIO 包装成 DigitalInOut 对象传给库。
        """
        if self._reset_pin:  # 如果接了 reset 引脚，就硬件复位一下
            if self.debug:
                print("Resetting")

            # 低电平 0.1秒，然后高电平 0.1秒 对应 reset state -> normal operation state
            self._reset_pin.direction = Direction.OUTPUT
            self._reset_pin.value = False
            time.sleep(0.1)
            self._reset_pin.value = True
            time.sleep(0.1)
        self._wakeup()  # TODO: 子类实现

    def _write_frame(self, data: bytearray) -> None:
        """
        Write a frame to the PN532 with the specified data bytearray.
        构建并发送Normal Information Frame 到 PN532
        data: bytearray 要发送的数据内容，包含 TFI 和 PD0~PDn 部分
        00 | 00 | FF | LEN | LCS | TFI | PD0 | PD1 | ... | PDn | DCS | 00
        Preamble, Postamble 固定 0x00, Start of Packet Code固定0x00 FF
        LEN: len(TFI~PDn)
        LCS: 满足lower of [LEN+LCS]=0x00   等价  LCS=0x100-LEN  或者说  LCS = -LEN  （取低位）
                Eg. LEN=0xFE,     LCS=0x02
        TFI: 帧方向：(0xD4: Host→PN532  @  0xD5: PN532→Host)
        PD0~PDn: (PD0: Command   PD1,…,PDn: 参数)
        DCS: lower of (TFI+PD0+⋯+PDn+DCS)=0x00   等价  DCS=0x100-(TFI+PD0+⋯+PDn)
        """
        assert data is not None and 1 < len(data) < 255, "Data must be array of 1 to 255 bytes."
        # Build frame to send as:
        # - Preamble (0x00)
        # - Start code  (0x00, 0xFF)
        # - Command length (1 byte)
        # - Command length checksum
        # - Command bytes
        # - Checksum
        # - Postamble (0x00)
        length = len(data)  # data 长度
        frame = bytearray(length + 8)  # data（包括 TFI 和 PD0~PDn 部分）+ 8 字节的其他部分
        frame[0] = _PREAMBLE  # 00
        frame[1] = _STARTCODE1  # 00
        frame[2] = _STARTCODE2  # FF
        checksum = sum(frame[0:3])  # DCS 用，初始化为前三个字节之和，就是 0xFF
        frame[3] = length & 0xFF  # 截取低8位作为 LEN （前面已经断言过长度小于255了，所以这里基本不会截断）
        frame[4] = (~length + 1) & 0xFF  #  LCS = -LEN & 0xFF  括号里是补码，就是(-length)取低8位
        frame[5:-2] = data  # TFI 和 PD0~PDn
        checksum += sum(data)  # 现在是 0xFF + TFI + PD0 + ... + PDn
        frame[-2] = ~checksum & 0xFF  # DCS = ~(FF+DATA) & 0xFF = (-FF-DATA) & 0xFF = 0 + (-DATA) & 0xFF
        # Send frame.
        if self.debug:
            print("Write frame: ", [hex(i) for i in frame])  # 调试打印生成的帧
        self._write_data(bytes(frame))  # TODO: 子类实现

    def _read_frame(self, length: int) -> Union[bytes, bytearray]:
        """Read a response frame from the PN532 of at most length bytes in size.
        Returns the data inside the frame if found, otherwise raises an exception
        if there is an error parsing the frame.  Note that less than length bytes
        might be returned!
        length: 期望读取的数据长度，包括 TFI 和 PD0~PDn 部分
        00 | 00 | FF | LEN | LCS | TFI | PD0 | PD1 | ... | PDn | DCS | 00
        读取 PN532 发回的 Normal Information Frame，并解析返回 TFI 和 PD0~PDn 部分
        """
        # Read frame with expected length of data.
        response = self._read_data(length + 7)  # TODO: 子类实现
        if self.debug:
            print("Read frame:", [hex(i) for i in response])

        # Swallow all the 0x00 values that preceed 0xFF. 定位 0x00FF起始位置
        offset = 0
        while response[offset] == 0x00:
            offset += 1
            if offset >= len(response):
                raise RuntimeError("Response frame preamble does not contain 0x00FF!")

        # 检查是否找到了
        if response[offset] != 0xFF:
            raise RuntimeError("Response frame preamble does not contain 0x00FF!")
        offset += 1  #看下一位 LEN
        if offset >= len(response):
            raise RuntimeError("Response contains no data!")

        # Check length & length checksum match.
        frame_len = response[offset]  # 获取 LEN
        if (frame_len + response[offset + 1]) & 0xFF != 0:  # 检查 LEN和 LCS 是否匹配
            raise RuntimeError("Response length checksum did not match length!")
        # Check frame checksum value matches bytes. 获取 DCS 并检查 （从 TFI到 PDn）
        checksum = sum(response[offset + 2 : offset + 2 + frame_len + 1]) & 0xFF
        if checksum != 0:
            raise RuntimeError("Response checksum did not match expected value: ", checksum)
        # Return frame data.
        return response[offset + 2 : offset + 2 + frame_len]  # 返回 TFI 和 PD0~PDn 部分

    def call_function(
        self,
        command: int,
        response_length: int = 0,
        params: ReadableBuffer = b"",
        timeout: float = 1,
    ) -> Optional[Union[bytes, bytearray]]:
        """Send specified command to the PN532 and expect up to response_length
        bytes back in a response.  Note that less than the expected bytes might
        be returned!  Params can optionally specify an array of bytes to send as
        parameters to the function call.  Will wait up to timeout seconds
        for a response and return a bytearray of response bytes, or None if no
        response is available within the timeout.
        发送指定命令到 PN532，并读取响应
        command: 要发送的命令 PD0
        response_length: 期望读取的数据长度，包括 TFI 和 PD0~PDn 部分
        params: 可选的参数列表 PD1~PDn
        timeout: 最长等待时间，单位秒，这个函数最长响应 2*timeout 秒
        """
        if not self.send_command(command, params=params, timeout=timeout):
            return None
        return self.process_response(command, response_length=response_length, timeout=timeout)

    def send_command(self, command: int, params: ReadableBuffer = b"", timeout: float = 1) -> bool:
        """Send specified command to the PN532 and wait for an acknowledgment.
        Will wait up to timeout seconds for the acknowledgment and return True.
        If no acknowledgment is received, False is returned.
        发送指定命令到 PN532，并等待 ACK 确认帧
        command: 要发送的命令 PD0
        params: 可选的参数列表 PD1~PDn
        timeout: 最长等待时间，单位秒
        """
        # 唤醒
        if self.low_power:
            self._wakeup()  # TODO: 子类实现

        # Build frame data with command and parameters.
        data = bytearray(2 + len(params))  # 长度是 TFI + PD0(command) + PD1~PDn(params)
        data[0] = _HOSTTOPN532  # TFI: Host to PN532
        data[1] = command & 0xFF  # PD0: Command
        for i, val in enumerate(params):
            data[2 + i] = val
        # Send frame and wait for response.
        try:
            self._write_frame(data)  # 构建并发送帧
        except OSError:
            return False
        # 等待 PN532 准备好（有 ACK）
        if not self._wait_ready(timeout):  # TODO: 子类实现
            return False

        # Verify ACK response and wait to be ready for function response.
        # 验证 PN532 的固定 ACK 帧
        if not _ACK == self._read_data(len(_ACK)):  # TODO: 子类实现
            raise RuntimeError("Did not receive expected ACK from PN532!")
        return True

    def process_response(
        self, command: int, response_length: int = 0, timeout: float = 1
    ) -> Optional[Union[bytes, bytearray]]:
        """Process the response from the PN532 and expect up to response_length
        bytes back in a response.  Note that less than the expected bytes might
        be returned! Will wait up to timeout seconds for a response and return
        a bytearray of response bytes, or None if no response is available
        within the timeout.
        处理 PN532 的响应，读取并解析响应帧，获取 TFI 和 PD0~PDn 部分
        command: 之前发送的命令，用来验证响应帧的 PD0 是 command + 1
        response_length: 期望读取的数据长度，包括 TFI 和 PD0~PDn 部分
        timeout: 最长等待时间，单位秒
        """
        # Wait for PN532 to be ready.
        if not self._wait_ready(timeout):  # TODO: 子类实现
            return None

        # Read response bytes. 读取并解析响应帧，获取 TFI 和 PD0~PDn 部分
        response = self._read_frame(response_length + 2)
        # Check that response is for the called function. 检查 TFI 是 PN532 to Host，PD0 是 command + 1 （command 指令的响应）
        if not (response[0] == _PN532TOHOST and response[1] == (command + 1)):
            raise RuntimeError("Received unexpected command response!")
        # Return response data.
        return response[2:]

    def power_down(self) -> bool:
        """Put the PN532 into a low power state. If the reset pin is connected a
        hard power down is performed, if not, a soft power down is performed
        instead. Returns True if the PN532 was powered down successfully or
        False if not.
        将 PN532 置于低功耗状态。如果连接了 reset 引脚，则执行硬掉电，否则执行软掉电。
        返回 PN532 是否成功掉电的布尔值。
        """
        # 如果接了 reset 引脚，就硬件掉电
        if self._reset_pin:  # Hard Power Down if the reset pin is connected
            self._reset_pin.value = False
            self.low_power = True
        else:  # 否则软掉电，同时启用 I2C、SPI、UART 唤醒
            # Soft Power Down otherwise. Enable wakeup on I2C, SPI, UART
            response = self.call_function(_COMMAND_POWERDOWN, params=[0xB0, 0x00])
            self.low_power = response[0] == 0x00
        time.sleep(0.005)
        return self.low_power

    @property
    def firmware_version(self) -> Tuple[int, int, int, int]:
        """Call PN532 GetFirmwareVersion function and return a tuple with the IC,
        Ver, Rev, and Support values.
        返回 PN532 固件版本信息的元组 (IC, Ver, Rev, Support)
        代表芯片型号、版本号、修订号和支持的功能
        """
        response = self.call_function(_COMMAND_GETFIRMWAREVERSION, 4, timeout=0.5)
        if response is None:
            raise RuntimeError("Failed to detect the PN532")
        return tuple(response)

    def SAM_configuration(self) -> None:
        """Configure the PN532 to read MiFare cards."""
        # Send SAM configuration command with configuration for:
        # - 0x01, normal mode
        # - 0x14, timeout 50ms * 20 = 1 second
        # - 0x01, use IRQ pin
        # Note that no other verification is necessary as call_function will
        # check the command was executed as expected.
        self.call_function(_COMMAND_SAMCONFIGURATION, params=[0x01, 0x14, 0x01])

    def read_passive_target(
        self, card_baud: int = _MIFARE_ISO14443A, timeout: float = 1
    ) -> Optional[bytearray]:
        """Wait for a MiFare card to be available and return its UID when found.
        Will wait up to timeout seconds and return None if no card is found,
        otherwise a bytearray with the UID of the found card is returned.
        获取卡的 UID。
        具体实现是先调用 `listen_for_passive_target` 让 PN532 进入监听模式，
        然后调用 `get_passive_target` 读取卡的 UID。
        没有卡的话返回 None。等待 ACK基本很快，等待卡片出现可能会比较久，最长等 timeout 秒。没放卡也会等 timeout 秒。
        card_baud: 卡的波特率，默认为 MIFARE_ISO14443A
        timeout: 最长等待时间，单位秒
        """
        # Send passive read command for 1 card.  Expect at most a 7 byte UUID.
        response = self.listen_for_passive_target(card_baud=card_baud, timeout=timeout)
        # If no response is available return None to indicate no card is present.
        if not response:
            return None
        return self.get_passive_target(timeout=timeout)

    def listen_for_passive_target(
        self, card_baud: int = _MIFARE_ISO14443A, timeout: float = 1
    ) -> bool:
        """Send command to PN532 to begin listening for a Mifare card. This
        returns True if the command was received successfully. Note, this does
        not also return the UID of a card! `get_passive_target` must be called
        to read the UID when a card is found. If just looking to see if a card
        is currently present use `read_passive_target` instead.
        给 PN532 发送命令，开始监听 MiFare 卡。
        返回response 如果命令成功发送则为 True。 这里并不返回卡的 UID
        card_baud: 卡的波特率，默认为 MIFARE_ISO14443A
        timeout: 最长等待时间，单位秒
        """
        # Send passive read command for 1 card.  Expect at most a 7 byte UUID.
        try:
            response = self.send_command(
                _COMMAND_INLISTPASSIVETARGET, params=[0x01, card_baud], timeout=timeout
            )
        except BusyError:
            return False  # _COMMAND_INLISTPASSIVETARGET failed
        return response

    def get_passive_target(self, timeout: float = 1) -> Optional[Union[bytes, bytearray]]:
        """Will wait up to timeout seconds and return None if no card is found,
        otherwise a bytearray with the UID of the found card is returned.
        `listen_for_passive_target` must have been called first in order to put
        the PN532 into a listening mode.

        It can be useful to use this when using the IRQ pin. Use the IRQ pin to
        detect when a card is present and then call this function to read the
        card's UID. This reduces the amount of time spend checking for a card.

        获取卡的 UID，前提是之前已经调用过 `listen_for_passive_target` 让 PN532 进入监听模式。
        """
        # 获取上面函数发出的命令的响应结果，这里是读取卡的 UID
        response = self.process_response(
            _COMMAND_INLISTPASSIVETARGET, response_length=30, timeout=timeout
        )
        # If no response is available return None to indicate no card is present.
        if response is None:
            return None
        # Check only 1 card with up to a 7 byte UID is present.
        if response[0] != 0x01:
            raise RuntimeError("More than one card detected!")
        if response[5] > 7:
            raise RuntimeError("Found card with unexpectedly long UID!")

        # Return UID of card.
        return response[6 : 6 + response[5]]

    def mifare_classic_authenticate_block(
        self,
        uid: ReadableBuffer,
        block_number: int,
        key_number: Literal[0x60, 0x61],
        key: ReadableBuffer,
    ) -> bool:
        """Authenticate specified block number for a MiFare classic card.  Uid
        should be a byte array with the UID of the card, block number should be
        the block to authenticate, key number should be the key type (like
        MIFARE_CMD_AUTH_A or MIFARE_CMD_AUTH_B), and key should be a byte array
        with the key data.  Returns True if the block was authenticated, or False
        if not authenticated.
        认证 MiFare classic 卡的指定块号。
        uid: 卡的 UID
        block_number: 要认证的块号
        key_number: 密钥类型，MIFARE_CMD_AUTH_A 或 MIFARE_CMD_AUTH_B
        key: 密钥数据
        认证成功返回 True，否则返回 False。
        """
        # Build parameters for InDataExchange command to authenticate MiFare card.
        uidlen = len(uid)
        keylen = len(key)
        params = bytearray(3 + uidlen + keylen)
        params[0] = 0x01  # Max card numbers
        params[1] = key_number & 0xFF
        params[2] = block_number & 0xFF
        params[3 : 3 + keylen] = key
        params[3 + keylen :] = uid
        # Send InDataExchange request and verify response is 0x00.
        # 构建并发送 InDataExchange 命令
        response = self.call_function(_COMMAND_INDATAEXCHANGE, params=params, response_length=1)
        return response[0] == 0x00  # 0是成功状态码，非0是失败状态码

    def mifare_classic_read_block(self, block_number: int) -> Optional[Union[bytes, bytearray]]:
        """Read a block of data from the card.  Block number should be the block
        to read.  If the block is successfully read a bytearray of length 16 with
        data starting at the specified block will be returned.  If the block is
        not read then None will be returned.
        认证后执行。
        读取卡的指定块号的数据，返回长度为16的字节数组。如果读取失败则返回 None。
        block_number: 要读取的块号
        """
        # Send InDataExchange request to read block of MiFare data.
        response = self.call_function(
            _COMMAND_INDATAEXCHANGE,
            params=[0x01, MIFARE_CMD_READ, block_number & 0xFF],
            response_length=17,
        )
        # Check first response is 0x00 to show success.
        if response[0] != 0x00:
            return None
        # Return first 4 bytes since 16 bytes are always returned.
        # 由于返回的数据包含状态码，所以返回时跳过第一个字节
        return response[1:]

    def mifare_classic_write_block(self, block_number: int, data: ReadableBuffer) -> bool:
        """Write a block of data to the card.  Block number should be the block
        to write and data should be a byte array of length 16 with the data to
        write.  If the data is successfully written then True is returned,
        otherwise False is returned.
        认证后执行。
        写入数据到卡的指定块号。data 应该是一个长度为16的字节数组。
        如果数据成功写入则返回 True，否则返回 False。
        block_number: 要写入的块号
        data: 要写入的数据，长度为16字节。可以用bytearray()，或 bytes().fromhex() 创建等。
        """
        assert data is not None and len(data) == 16, "Data must be an array of 16 bytes!"
        # Build parameters for InDataExchange command to do MiFare classic write.
        params = bytearray(19)
        params[0] = 0x01  # Max card numbers
        params[1] = MIFARE_CMD_WRITE
        params[2] = block_number & 0xFF
        params[3:] = data
        # Send InDataExchange request.
        response = self.call_function(_COMMAND_INDATAEXCHANGE, params=params, response_length=1)
        return response[0] == 0x0

    def mifare_classic_sub_value_block(self, block_number: int, amount: int) -> bool:
        """Decrease the balance of a value block. Block number should be the block
        to change and amount should be an integer up to a maximum of 2147483647.
        If the value block is successfully updated then True is returned,
        otherwise False is returned.
        认证后执行。
        减少值块的余额。
        block_number: 要更改的块号
        amount: 要减少的金额，最大值为 2147483647
        如果值块成功更新则返回 True，否则返回 False。
        """
        params = [0x01, MIFARE_CMD_DECREMENT, block_number & 0xFF]
        params.extend(list(amount.to_bytes(4, "little")))

        # 对 value block 增减必须执行两步
        # 1. 发送 DECREMENT/INCREMENT 命令
        response = self.call_function(_COMMAND_INDATAEXCHANGE, params=params, response_length=1)
        if response[0] != 0x00:
            return False

        # 2. 发送 TRANSFER 命令
        response = self.call_function(
            _COMMAND_INDATAEXCHANGE,
            params=[0x01, MIFARE_CMD_TRANSFER, block_number & 0xFF],
            response_length=1,
        )

        return response[0] == 0x00

    def mifare_classic_add_value_block(self, block_number: int, amount: int) -> bool:
        """Increase the balance of a value block. Block number should be the block
        to change and amount should be an integer up to a maximum of 2147483647.
        If the value block is successfully updated then True is returned,
        otherwise False is returned.
        认证后执行。
        增加值块的余额。
        block_number: 要更改的块号
        amount: 要增加的金额，最大值为 2147483647
        如果值块成功更新则返回 True，否则返回 False。
        """
        params = [0x01, MIFARE_CMD_INCREMENT, block_number & 0xFF]
        params.extend(list(amount.to_bytes(4, "little")))

        response = self.call_function(_COMMAND_INDATAEXCHANGE, params=params, response_length=1)
        if response[0] != 0x00:
            return False

        response = self.call_function(
            _COMMAND_INDATAEXCHANGE,
            params=[0x01, MIFARE_CMD_TRANSFER, block_number & 0xFF],
            response_length=1,
        )

        return response[0] == 0x00

    def mifare_classic_get_value_block(self, block_number: int) -> int:
        """Read the contents of a value block and return a integer representing the
        current balance. Block number should be the block to read.
        little-endian：小端，0x1234 -> 34 12 存储顺序。地位储存低地址。
        Value block 结构：
        Bytes 0-3: Value (4字节，little-endian integer)
        Bytes 4-7: Value取反 (4字节，little-endian integer)
        Bytes 8-11: Value 拷贝 (4字节，little-endian integer)
        Bytes 12: Address (block 编号或逻辑地址)
        Bytes 13: Address 取反
        Bytes 14: Address拷贝 (block 编号或逻辑地址)
        Bytes 15: Address 取反
        认证后执行。
        读取值块的内容并返回一个整数，表示当前余额。
        block_number: 要读取的块号
        进行完整性检查，如果检查失败则抛出 RuntimeError 异常。
        """
        block = self.mifare_classic_read_block(block_number=block_number)  # 先读出块数据
        if block is None:
            return None

        # 做完整性检查
        value = block[0:4]
        value_inverted = block[4:8]
        value_backup = block[8:12]
        if value != value_backup:
            raise RuntimeError(
                "Value block bytes 0-3 do not match 8-11: " + "".join("%02x" % b for b in block)
            )
        if value_inverted != bytearray(map((lambda x: x ^ 0xFF), value)):
            raise RuntimeError(
                "Inverted value block bytes 4-7 not valid: " + "".join("%02x" % b for b in block)
            )

        return struct.unpack("<i", value)[0]  # 全部通过检查，返回整数值

    def mifare_classic_check_value_block(self, block_number: int) -> bool:
        """Check the integrity of a value block. Block number should be the block
        to check.
        认证后执行。
        检查值块的完整性。
        block_number: 要检查的块号
        如果值块通过完整性检查则返回 True，否则返回 False。
        """
        block = self.mifare_classic_read_block(block_number=block_number)  # 先读出块数据
        if block is None:
            return False

        # 做完整性检查
        value = block[0:4]
        value_inverted = block[4:8]
        value_backup = block[8:12]
        if value != value_backup:
            return False
        if value_inverted != bytearray(map((lambda x: x ^ 0xFF), value)):
            return False

        return True  # 全部通过检查

    def mifare_classic_fmt_value_block(
        self, block_number: int, initial_value: int, address_block: int = 0
    ) -> bool:
        """Formats a block on the card so it is suitable for use as a value block.
        Block number should be the block to use. Initial value should be an integer
        up to a maximum of 2147483647. Address block is optional and can be used
        as part of backup management.
        认证后执行。
        把一个普通 block 格式化成 value block
        block_number: 要使用的块号
        initial_value: 初始值，最大值为 2147483647
        address_block: 可选的地址块，用作备份管理的一部分
        如果块成功格式化则返回 True，否则返回 False。
        """
        data = bytearray()
        initial_value = initial_value.to_bytes(4, "little")  # initial_value 转成 4 字节小端表示
        # Value
        data.extend(initial_value)  # 写到 data 里
        # Inverted value
        data.extend(bytearray(map((lambda x: x ^ 0xFF), initial_value)))  # 取反后写到 data 里
        # Duplicate of value
        data.extend(initial_value)  # 复制一份写到 data 里

        # Address
        address_block = address_block.to_bytes(1, "little")[0]  # 取低8位作为地址块
        data.extend([address_block, address_block ^ 0xFF, address_block, address_block ^ 0xFF])  # 地址块及其取反写到 data 里

        return self.mifare_classic_write_block(block_number, data)  # 写入数据到卡

# NFC Type 2（例如 NTAG203/213/215/216） 相关的方法

    def ntag2xx_write_block(self, block_number: int, data: ReadableBuffer) -> bool:
        """Write a block of data to the card.  Block number should be the block
        to write and data should be a byte array of length 4 with the data to
        write.  If the data is successfully written then True is returned,
        otherwise False is returned.
        写入数据到 NFC Type 2 卡的指定块号。data 应该是一个长度为4的字节数组。
        如果数据成功写入则返回 True，否则返回 False。
        block_number: 要写入的块号
        data: 要写入的数据，长度为4字节。可以用bytearray()，或 bytes().fromhex() 创建等。
        """
        assert data is not None and len(data) == 4, "Data must be an array of 4 bytes!"
        # Build parameters for InDataExchange command to do NTAG203 classic write.
        params = bytearray(3 + len(data))
        params[0] = 0x01  # Max card numbers
        params[1] = MIFARE_ULTRALIGHT_CMD_WRITE
        params[2] = block_number & 0xFF
        params[3:] = data
        # Send InDataExchange request.
        response = self.call_function(_COMMAND_INDATAEXCHANGE, params=params, response_length=1)
        return response[0] == 0x00

    def ntag2xx_read_block(self, block_number: int) -> Optional[Union[bytes, bytearray]]:
        """Read a block of data from the card.  Block number should be the block
        to read.  If the block is successfully read the first 4 bytes (after the
        leading 0x00 byte) will be returned.
        If the block is not read then None will be returned.
        读取 NFC Type 2 卡的指定块号的数据，返回长度为4的字节数组。
        block_number: 要读取的块号
        读取失败则返回 None。
        """
        ntag2xx_block = self.mifare_classic_read_block(block_number)
        if ntag2xx_block is not None:
            return ntag2xx_block[0:4]  # only 4 bytes per page
        return None
