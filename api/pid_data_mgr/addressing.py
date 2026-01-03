import socket
import ipaddress
from typing import Callable

HOSTNAME_PORT_SEPARATOR = ":"


class Addressing:
    """地址处理工具类"""

    @staticmethod
    def create_host_and_port_str(hostname: str, port: int) -> str:
        """创建主机和端口字符串"""
        return f"{hostname}{HOSTNAME_PORT_SEPARATOR}{port}"

    @staticmethod
    def _get_ip_address(condition: Callable[[str], bool]) -> str:
        """
        获取符合条件的IP地址

        Args:
            condition: 判断地址是否可接受的函数

        Returns:
            IP地址字符串

        Raises:
            socket.error: 无法获取IP地址时抛出
        """
        interfaces = []

        # 获取所有网络接口
        try:
            # 获取主机名
            hostname = socket.gethostname()

            # 获取所有IP地址
            addrinfo = socket.getaddrinfo(hostname, None)

            for info in addrinfo:
                addr = info[4][0]  # 获取IP地址

                # 跳过环回地址
                if addr == '127.0.0.1' or addr == '::1':
                    continue

                # 检查地址是否符合条件
                if condition(addr):
                    return addr

                interfaces.append(addr)

        except socket.error as e:
            raise socket.error(f"获取网络接口失败: {e}")

        raise socket.error(f"无法获取符合条件的IP地址，找到的接口: {interfaces}")

    @staticmethod
    def get_ip_address() -> str:
        """获取IP地址（IPv4或IPv6）"""

        def condition(addr: str) -> bool:
            try:
                # 尝试解析为IPv4或IPv6
                ipaddress.ip_address(addr)
                return True
            except ValueError:
                return False

        return Addressing._get_ip_address(condition)

    @staticmethod
    def get_ipv4_address() -> str:
        """获取IPv4地址"""

        def condition(addr: str) -> bool:
            try:
                ip_obj = ipaddress.ip_address(addr)
                return isinstance(ip_obj, ipaddress.IPv4Address)
            except ValueError:
                return False

        return Addressing._get_ip_address(condition)

    @staticmethod
    def get_ipv6_address() -> str:
        """获取IPv6地址"""

        def condition(addr: str) -> bool:
            try:
                ip_obj = ipaddress.ip_address(addr)
                return isinstance(ip_obj, ipaddress.IPv6Address)
            except ValueError:
                return False

        return Addressing._get_ip_address(condition)


# 测试
if __name__ == "__main__":
    try:
        # 获取IPv4地址
        ipv4 = Addressing.get_ipv4_address()
        print(f"IPv4地址: {ipv4}")

        # 获取IPv6地址
        ipv6 = Addressing.get_ipv6_address()
        print(f"IPv6地址: {ipv6}")

        # 获取任何IP地址
        ip = Addressing.get_ip_address()
        print(f"IP地址: {ip}")

        # 创建主机端口字符串
        host_port = Addressing.create_host_and_port_str("localhost", 8080)
        print(f"主机端口: {host_port}")

    except socket.error as e:
        print(f"错误: {e}")