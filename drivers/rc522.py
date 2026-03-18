import time

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - only hit off Raspberry Pi
    GPIO = None

try:
    from pirc522 import RFID
except ImportError:  # pragma: no cover - only hit when pi-rc522 is not installed
    RFID = None


class RC522Reader:
    """Simple driver for an RC522 RFID reader."""

    DEFAULT_KEY = [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]

    def __init__(
        self,
        bus: int = 0,
        device: int = 0,
        pin_rst: int = 25,
        pin_irq=None,
        gpio_module=None,
        rfid_class=None,
    ) -> None:
        """
        Initialize the RC522 reader.

        Args:
            bus: SPI bus number. Usually 0 on Raspberry Pi.
            device: SPI device number. Usually 0 for CE0 or 1 for CE1.
            pin_rst: BCM GPIO pin connected to the RC522 RST pin.
            pin_irq: BCM GPIO pin connected to IRQ, or None if IRQ is unused.
            gpio_module: Optional GPIO-compatible module for testing or mocking.
            rfid_class: Optional RFID-compatible class for testing or mocking.
        """
        self._gpio = gpio_module or GPIO
        self._rfid_class = rfid_class or RFID

        if self._gpio is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install it on the Raspberry Pi or "
                "pass a compatible gpio_module for testing."
            )

        if self._rfid_class is None:
            raise RuntimeError(
                "pi-rc522 is not available. Install dependencies with "
                "'pip install pi-rc522 spidev'."
            )

        self._reader = self._rfid_class(
            bus=bus,
            device=device,
            pin_rst=pin_rst,
            pin_irq=pin_irq,
            pin_mode=self._gpio.BCM,
        )

    def _normalize_key(self, key) -> list[int]:
        if key is None:
            return self.DEFAULT_KEY.copy()

        if isinstance(key, bytes):
            key = list(key)

        if not isinstance(key, (list, tuple)):
            raise ValueError("key must be a list, tuple, bytes, or None")

        key = [int(value) for value in key]

        if len(key) != 6:
            raise ValueError("key must contain exactly 6 bytes")

        for value in key:
            if not 0 <= value <= 255:
                raise ValueError("key bytes must be between 0 and 255")

        return key

    def _normalize_block_data(self, data) -> list[int]:
        if isinstance(data, str):
            data = data.encode("utf-8")

        if isinstance(data, bytes):
            data = list(data)

        if not isinstance(data, (list, tuple)):
            raise ValueError("data must be a string, bytes, list, or tuple")

        data = [int(value) for value in data]

        if len(data) > 16:
            raise ValueError("block data must be 16 bytes or less")

        for value in data:
            if not 0 <= value <= 255:
                raise ValueError("data bytes must be between 0 and 255")

        return data + [0x00] * (16 - len(data))

    def _get_auth_mode(self, auth_mode: str):
        auth_mode = auth_mode.upper()
        if auth_mode == "A":
            return self._reader.auth_a
        if auth_mode == "B":
            return self._reader.auth_b
        raise ValueError('auth_mode must be "A" or "B"')

    def _is_trailer_block(self, block_addr: int) -> bool:
        if block_addr < 0:
            raise ValueError("block_addr must be >= 0")

        if block_addr < 128:
            return block_addr % 4 == 3

        return (block_addr - 128) % 16 == 15

    def _block_address(self, sector: int, block_index: int) -> int:
        if sector < 0:
            raise ValueError("sector must be >= 0")

        if sector < 32:
            if not 0 <= block_index < 4:
                raise ValueError("block_index must be between 0 and 3 for sectors 0-31")
            return sector * 4 + block_index

        if sector < 40:
            if not 0 <= block_index < 16:
                raise ValueError("block_index must be between 0 and 15 for sectors 32-39")
            return 128 + (sector - 32) * 16 + block_index

        raise ValueError("sector must be between 0 and 39")

    def _sector_blocks(self, sector: int, include_trailer: bool = False) -> list[int]:
        if sector < 32:
            start = sector * 4
            blocks = list(range(start, start + 4))
        elif sector < 40:
            start = 128 + (sector - 32) * 16
            blocks = list(range(start, start + 16))
        else:
            raise ValueError("sector must be between 0 and 39")

        if include_trailer:
            return blocks

        return [block for block in blocks if not self._is_trailer_block(block)]

    def _next_writable_blocks(self, start_block: int, count: int) -> list[int]:
        if count < 1:
            raise ValueError("count must be >= 1")

        blocks = []
        block = start_block

        while len(blocks) < count:
            if block == 0:
                block += 1
                continue

            if self._is_trailer_block(block):
                block += 1
                continue

            blocks.append(block)
            block += 1

        return blocks

    def wait_for_card(self, timeout: float = None, poll_interval: float = 0.1) -> bool:
        """
        Wait until a card is detected.

        Args:
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be >= 0 or None")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be > 0")

        start_time = time.time()

        while True:
            error, _ = self._reader.request()
            if not error:
                return True

            if timeout is not None and time.time() - start_time >= timeout:
                return False

            time.sleep(poll_interval)

    def read_uid(self, timeout: float = None, poll_interval: float = 0.1) -> list[int] | None:
        """
        Read the UID bytes from a card.

        Args:
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        if not self.wait_for_card(timeout, poll_interval):
            return None

        error, uid = self._reader.anticoll()
        if error:
            return None

        return uid

    def read_uid_hex(self, timeout: float = None, poll_interval: float = 0.1) -> str | None:
        """
        Read the UID and return it as a hex string.

        Args:
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        uid = self.read_uid(timeout, poll_interval)
        if uid is None:
            return None

        return "".join(f"{byte:02X}" for byte in uid)

    def read_uid_number(self, timeout: float = None, poll_interval: float = 0.1) -> int | None:
        """
        Read the UID and return it as a single integer.

        Args:
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        uid = self.read_uid(timeout, poll_interval)
        if uid is None:
            return None

        value = 0
        for byte in uid:
            value = (value << 8) | byte

        return value

    def read_block(
        self,
        block_addr: int,
        key=None,
        auth_mode: str = "A",
        timeout: float = None,
        poll_interval: float = 0.1,
    ) -> list[int]:
        """
        Read one 16-byte block from the card.

        Args:
            block_addr: Absolute block address on the card.
            key: Authentication key. None uses the default shipping key.
            auth_mode: Authentication mode, "A" or "B".
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        uid = self.read_uid(timeout, poll_interval)
        if uid is None:
            raise RuntimeError("No card detected")

        key = self._normalize_key(key)
        auth_mode = self._get_auth_mode(auth_mode)

        if self._reader.select_tag(uid):
            raise RuntimeError("Failed to select card")

        try:
            if self._reader.card_auth(auth_mode, block_addr, key, uid):
                raise RuntimeError(f"Authentication failed for block {block_addr}")

            error, data = self._reader.read(block_addr)
            if error:
                raise RuntimeError(f"Failed to read block {block_addr}")

            return data
        finally:
            self._reader.stop_crypto()

    def write_block(
        self,
        block_addr: int,
        data,
        key=None,
        auth_mode: str = "A",
        allow_trailer: bool = False,
        allow_manufacturer_block: bool = False,
        timeout: float = None,
        poll_interval: float = 0.1,
    ) -> None:
        """
        Write one 16-byte block to the card.

        Args:
            block_addr: Absolute block address on the card.
            data: Data to write. Supports string, bytes, list, or tuple.
            key: Authentication key. None uses the default shipping key.
            auth_mode: Authentication mode, "A" or "B".
            allow_trailer: If True, allow writing sector trailer blocks.
            allow_manufacturer_block: If True, allow writing block 0.
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        if block_addr == 0 and not allow_manufacturer_block:
            raise ValueError("Writing block 0 is disabled by default")

        if self._is_trailer_block(block_addr) and not allow_trailer:
            raise ValueError("Writing trailer blocks is disabled by default")

        uid = self.read_uid(timeout, poll_interval)
        if uid is None:
            raise RuntimeError("No card detected")

        key = self._normalize_key(key)
        auth_mode = self._get_auth_mode(auth_mode)
        block_data = self._normalize_block_data(data)

        if self._reader.select_tag(uid):
            raise RuntimeError("Failed to select card")

        try:
            if self._reader.card_auth(auth_mode, block_addr, key, uid):
                raise RuntimeError(f"Authentication failed for block {block_addr}")

            self._reader.write(block_addr, block_data)
        finally:
            self._reader.stop_crypto()

    def read_sector(
        self,
        sector: int,
        key=None,
        auth_mode: str = "A",
        include_trailer: bool = False,
        timeout: float = None,
        poll_interval: float = 0.1,
    ) -> dict[int, list[int]]:
        """
        Read all blocks in a sector.

        Args:
            sector: Sector index to read.
            key: Authentication key. None uses the default shipping key.
            auth_mode: Authentication mode, "A" or "B".
            include_trailer: If True, include the trailer block in the result.
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        result = {}

        for block_addr in self._sector_blocks(sector, include_trailer):
            result[block_addr] = self.read_block(
                block_addr,
                key=key,
                auth_mode=auth_mode,
                timeout=timeout,
                poll_interval=poll_interval,
            )

        return result

    def read_sector_block(
        self,
        sector: int,
        block_index: int,
        key=None,
        auth_mode: str = "A",
        timeout: float = None,
        poll_interval: float = 0.1,
    ) -> list[int]:
        """
        Read one block inside a specific sector.

        Args:
            sector: Sector index.
            block_index: Block index inside the sector.
            key: Authentication key. None uses the default shipping key.
            auth_mode: Authentication mode, "A" or "B".
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        block_addr = self._block_address(sector, block_index)
        return self.read_block(block_addr, key, auth_mode, timeout, poll_interval)

    def write_sector_block(
        self,
        sector: int,
        block_index: int,
        data,
        key=None,
        auth_mode: str = "A",
        allow_trailer: bool = False,
        allow_manufacturer_block: bool = False,
        timeout: float = None,
        poll_interval: float = 0.1,
    ) -> None:
        """
        Write one block inside a specific sector.

        Args:
            sector: Sector index.
            block_index: Block index inside the sector.
            data: Data to write. Supports string, bytes, list, or tuple.
            key: Authentication key. None uses the default shipping key.
            auth_mode: Authentication mode, "A" or "B".
            allow_trailer: If True, allow writing trailer blocks.
            allow_manufacturer_block: If True, allow writing block 0.
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        block_addr = self._block_address(sector, block_index)
        self.write_block(
            block_addr,
            data,
            key=key,
            auth_mode=auth_mode,
            allow_trailer=allow_trailer,
            allow_manufacturer_block=allow_manufacturer_block,
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def read_text(
        self,
        start_block: int = 1,
        block_count: int = 1,
        key=None,
        auth_mode: str = "A",
        timeout: float = None,
        poll_interval: float = 0.1,
    ) -> str:
        """
        Read text data across one or more data blocks.

        Args:
            start_block: Absolute block address where reading starts.
            block_count: Number of writable data blocks to read.
            key: Authentication key. None uses the default shipping key.
            auth_mode: Authentication mode, "A" or "B".
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        blocks = self._next_writable_blocks(start_block, block_count)
        data = []

        for block_addr in blocks:
            data.extend(
                self.read_block(
                    block_addr,
                    key=key,
                    auth_mode=auth_mode,
                    timeout=timeout,
                    poll_interval=poll_interval,
                )
            )

        return bytes(data).rstrip(b"\x00").decode("utf-8", errors="ignore")

    def write_text(
        self,
        text: str,
        start_block: int = 1,
        key=None,
        auth_mode: str = "A",
        timeout: float = None,
        poll_interval: float = 0.1,
    ) -> list[int]:
        """
        Write text data across one or more writable data blocks.

        Args:
            text: UTF-8 text to write.
            start_block: Absolute block address where writing starts.
            key: Authentication key. None uses the default shipping key.
            auth_mode: Authentication mode, "A" or "B".
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        raw_data = text.encode("utf-8")
        if len(raw_data) == 0:
            raw_data = b"\x00"

        block_count = (len(raw_data) + 15) // 16
        blocks = self._next_writable_blocks(start_block, block_count)

        for index, block_addr in enumerate(blocks):
            chunk = raw_data[index * 16:(index + 1) * 16]
            self.write_block(
                block_addr,
                chunk,
                key=key,
                auth_mode=auth_mode,
                timeout=timeout,
                poll_interval=poll_interval,
            )

        return blocks

    def cleanup(self) -> None:
        """Release GPIO resources used by the RC522 reader."""
        self._reader.cleanup()

    def close(self) -> None:
        """Alias of cleanup()."""
        self.cleanup()


if __name__ == "__main__":
    reader = RC522Reader()
    try:
        print("Hold a card near the RC522...")
        uid = reader.read_uid_hex()
        print("UID:", uid)

        sector_data = reader.read_sector(1)
        for block_addr, data in sector_data.items():
            print(f"Block {block_addr}: {data}")  # 读取第 1 扇区的所有数据块

        text = reader.read_text(4, 2)
        print("Text:", text)  # 从 block 4 开始读取两个数据块里的文本

        # reader.write_text("hello rc522", 4)  # 从 block 4 开始写入文本
        # reader.write_sector_block(1, 1, "demo data")  # 向 sector 1 的 block 1 写入 16 字节内的数据
    finally:
        reader.cleanup()
