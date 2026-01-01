class BlockUtil:
    """分块计算工具类"""

    @staticmethod
    def calc_blocks_count(file_size: int, block_size: int) -> int:
        """
        计算需要的分块数量

        Args:
            file_size: 文件大小
            block_size: 分块大小

        Returns:
            int: 分块数量
        """
        if file_size % block_size == 0:
            return file_size // block_size
        else:
            return (file_size // block_size) + 1

    @staticmethod
    def build_block_list(file_size: int, block_size: int) -> set[int]:
        """
        构建分块索引列表

        Args:
            file_size: 文件大小
            block_size: 分块大小

        Returns:
            set[int]: 分块索引集合（已排序）
        """
        size = BlockUtil.calc_blocks_count(file_size, block_size)
        # 使用集合推导式创建已排序的集合
        return set(range(size))

    @staticmethod
    def calc_last_block_size(file_size: int, block_size: int) -> int:
        """
        计算最后一个分块的大小

        Args:
            file_size: 文件大小
            block_size: 分块大小

        Returns:
            int: 最后一个分块的大小
        """
        if file_size % block_size == 0:
            return block_size

        blocks_count = file_size // block_size
        return file_size - (block_size * blocks_count)

    @staticmethod
    def calc_block_index(position: int, block_size: int) -> int:
        """
        计算指定位置所在的分块索引

        Args:
            position: 位置（偏移量）
            block_size: 分块大小

        Returns:
            int: 分块索引
        """
        return position // block_size

    @staticmethod
    def calc_block_offset(position: int, block_size: int) -> int:
        """
        计算指定位置在分块内的偏移量

        Args:
            position: 位置（偏移量）
            block_size: 分块大小

        Returns:
            int: 在分块内的偏移量
        """
        block_index = position // block_size
        offset = position - (block_index * block_size)
        return offset