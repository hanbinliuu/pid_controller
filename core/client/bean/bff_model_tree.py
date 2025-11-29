#!/usr/bin/env python3
"""
BFF模型树解析和处理模块
用于解析、遍历、查询BFF模型树结构
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TreeNode:
    """
    BFF模型树节点
    代表树中的一个节点（文件夹或实例）
    """
    uri: str
    browse_name: str
    display_name: str
    description: Optional[str] = None
    node_class: str = "FOLDER"  # FOLDER 或 INSTANCE
    parent_uri: Optional[str] = None
    extended_attr: Dict[str, Any] = field(default_factory=dict)
    uriPath: Optional[str] = None
    displayNamePath: Optional[str] = None
    browseNamePath: Optional[str] = None
    
    def is_folder(self) -> bool:
        """是否是文件夹"""
        return self.node_class == "FOLDER"
    
    def is_instance(self) -> bool:
        """是否是实例"""
        return self.node_class == "INSTANCE"
    
    def get_loop_type(self) -> Optional[str]:
        """获取回路类型（仅对实例有效）"""
        if self.is_instance():
            return self.extended_attr.get('loop_type')
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'uri': self.uri,
            'browse_name': self.browse_name,
            'display_name': self.display_name,
            'description': self.description,
            'node_class': self.node_class,
            'parent_uri': self.parent_uri,
            'extended_attr': self.extended_attr,
            'loop_type': self.get_loop_type()
        }
    
    @classmethod
    def from_bff_node(cls, node_data: Dict[str, Any], parent_uri: Optional[str] = None) -> 'TreeNode':
        """从BFF响应的节点数据创建TreeNode对象"""
        return cls(
            uri=node_data.get('uri', ''),
            browse_name=node_data.get('browseName', ''),
            display_name=node_data.get('displayName', ''),
            description=node_data.get('description'),
            node_class=node_data.get('nodeClass', 'FOLDER'),
            parent_uri=parent_uri,
            extended_attr=node_data.get('extendedAttr', {}),
            uriPath=node_data.get('uriPath'),
            displayNamePath=node_data.get('displayNamePath'),
            browseNamePath=node_data.get('browseNamePath')
        )


@dataclass
class ModelTree:
    """
    BFF模型树
    代表从BFF响应解析得到的完整树结构
    """
    root_node: TreeNode
    all_nodes: Dict[str, TreeNode] = field(default_factory=dict)  # uri -> TreeNode 映射
    parent_child_map: Dict[str, List[str]] = field(default_factory=dict)  # 父节点URI -> 子节点URI列表
    children_map: Dict[str, List[TreeNode]] = field(default_factory=dict)  # uri -> 子节点对象列表
    
    def add_node(self, node: TreeNode):
        """添加节点到树中"""
        self.all_nodes[node.uri] = node
        
        if node.parent_uri:
            if node.parent_uri not in self.parent_child_map:
                self.parent_child_map[node.parent_uri] = []
            self.parent_child_map[node.parent_uri].append(node.uri)
            
            if node.parent_uri not in self.children_map:
                self.children_map[node.parent_uri] = []
            self.children_map[node.parent_uri].append(node)
    
    def get_children(self, node_uri: str) -> List[TreeNode]:
        """获取某个节点的所有子节点"""
        return self.children_map.get(node_uri, [])
    
    def get_child_uris(self, node_uri: str) -> List[str]:
        """获取某个节点的所有子节点URI"""
        return self.parent_child_map.get(node_uri, [])
    
    def get_node(self, node_uri: str) -> Optional[TreeNode]:
        """根据URI获取节点"""
        return self.all_nodes.get(node_uri)
    
    def get_all_instances(self) -> List[TreeNode]:
        """获取所有实例节点"""
        return [node for node in self.all_nodes.values() if node.is_instance()]
    
    def get_all_folders(self) -> List[TreeNode]:
        """获取所有文件夹节点"""
        return [node for node in self.all_nodes.values() if node.is_folder()]
    
    def get_instances_by_type(self, loop_type: str) -> List[TreeNode]:
        """根据回路类型获取所有实例"""
        return [node for node in self.get_all_instances() if node.get_loop_type() == loop_type]
    
    def find_nodes_by_name(self, name_pattern: str) -> List[TreeNode]:
        """根据名称模式查找节点（模糊匹配）"""
        return [node for node in self.all_nodes.values() 
                if name_pattern.lower() in node.display_name.lower()]
    
    def get_node_path(self, node_uri: str) -> Optional[List[TreeNode]]:
        """获取从根节点到指定节点的路径"""
        if node_uri not in self.all_nodes:
            return None
        
        path = []
        current_uri = node_uri
        
        while current_uri:
            node = self.all_nodes.get(current_uri)
            if not node:
                break
            path.insert(0, node)
            current_uri = node.parent_uri
        
        return path
    
    def get_breadcrumb_path(self, node_uri: str) -> Optional[str]:
        """获取节点的导航路径（展示用）"""
        path = self.get_node_path(node_uri)
        if not path:
            return None
        
        return " > ".join([node.display_name for node in path])
    
    def traverse_dfs(self, node_uri: Optional[str] = None, callback=None):
        """深度优先遍历树"""
        if node_uri is None:
            node_uri = self.root_node.uri
        
        node = self.all_nodes.get(node_uri)
        if not node:
            return
        
        if callback:
            callback(node)
        
        for child in self.get_children(node_uri):
            self.traverse_dfs(child.uri, callback)
    
    def traverse_bfs(self, callback=None) -> List[TreeNode]:
        """广度优先遍历树"""
        from collections import deque
        
        queue = deque([self.root_node.uri])
        visited = set()
        nodes = []
        
        while queue:
            node_uri = queue.popleft()
            
            if node_uri in visited:
                continue
            
            visited.add(node_uri)
            node = self.all_nodes.get(node_uri)
            
            if node:
                nodes.append(node)
                if callback:
                    callback(node)
                
                for child in self.get_children(node_uri):
                    queue.append(child.uri)
        
        return nodes
    
    def get_tree_depth(self) -> int:
        """获取树的深度"""
        if not self.all_nodes:
            return 0
        
        max_depth = 0
        
        def calculate_depth(node_uri: str, depth: int):
            nonlocal max_depth
            max_depth = max(max_depth, depth)
            
            for child in self.get_children(node_uri):
                calculate_depth(child.uri, depth + 1)
        
        calculate_depth(self.root_node.uri, 1)
        return max_depth
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'root': self.root_node.to_dict(),
            'total_nodes': len(self.all_nodes),
            'total_instances': len(self.get_all_instances()),
            'total_folders': len(self.get_all_folders()),
            'tree_depth': self.get_tree_depth(),
            'instances': [node.to_dict() for node in self.get_all_instances()]
        }
    
    def print_tree(self, node_uri: Optional[str] = None, indent: int = 0):
        """打印树的结构"""
        if node_uri is None:
            node_uri = self.root_node.uri
        
        node = self.all_nodes.get(node_uri)
        if not node:
            return
        
        prefix = "  " * indent
        node_type = "📁" if node.is_folder() else "📌"
        loop_type = f" [{node.get_loop_type()}]" if node.get_loop_type() else ""
        
        print(f"{prefix}{node_type} {node.display_name}{loop_type}")
        
        for child in self.get_children(node_uri):
            self.print_tree(child.uri, indent + 1)


class BFFModelTreeParser:
    """
    BFF模型树解析器
    用于解析BFF返回的树形结构数据
    """
    
    @staticmethod
    def parse_tree_response(response_data: Dict[str, Any]) -> Optional[ModelTree]:
        """
        解析BFF树形查询响应
        
        Args:
            response_data: BFF的树形查询响应数据
            
        Returns:
            解析后的ModelTree对象
        """
        if not response_data or 'result' not in response_data:
            logger.error("无效的BFF响应数据")
            return None
        
        result = response_data.get('result', {})
        root_data = result.get('node')
        
        if not root_data:
            logger.error("BFF响应中缺少root节点")
            return None
        
        # 创建根节点
        root_node = TreeNode.from_bff_node(root_data)
        tree = ModelTree(root_node=root_node)
        
        # 递归解析所有子节点
        BFFModelTreeParser._parse_children(result.get('children', []), root_node.uri, tree)
        
        logger.info(f"成功解析BFF树，总节点数: {len(tree.all_nodes)}, "
                   f"实例数: {len(tree.get_all_instances())}")
        
        return tree
    
    @staticmethod
    def _parse_children(children_data: List[Dict[str, Any]], parent_uri: str, tree: ModelTree):
        """
        递归解析子节点
        
        Args:
            children_data: 子节点数据列表
            parent_uri: 父节点URI
            tree: ModelTree对象
        """
        if not children_data:
            return
        
        for child_data in children_data:
            if 'node' not in child_data:
                continue
            
            node_data = child_data.get('node')
            node = TreeNode.from_bff_node(node_data, parent_uri)
            tree.add_node(node)
            
            # 递归处理子节点
            grandchildren = child_data.get('children', [])
            if grandchildren:
                BFFModelTreeParser._parse_children(grandchildren, node.uri, tree)


class ModelTreeAnalyzer:
    """
    模型树分析器
    提供高层次的树分析和查询功能
    """
    
    def __init__(self, tree: ModelTree):
        """初始化分析器"""
        self.tree = tree
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取树的统计信息"""
        instances = self.tree.get_all_instances()
        
        # 按回路类型统计
        type_count = {}
        for instance in instances:
            loop_type = instance.get_loop_type() or "未分类"
            type_count[loop_type] = type_count.get(loop_type, 0) + 1
        
        return {
            "total_nodes": len(self.tree.all_nodes),
            "total_instances": len(instances),
            "total_folders": len(self.tree.get_all_folders()),
            "tree_depth": self.tree.get_tree_depth(),
            "instance_types": type_count
        }
    
    def find_instances_by_path(self, path_components: List[str]) -> List[TreeNode]:
        """
        根据路径查找实例
        
        Args:
            path_components: 路径组件列表，如 ['某石化工厂', '炼化车间', '催化']
            
        Returns:
            匹配的实例列表
        """
        matching_instances = []
        
        for instance in self.tree.get_all_instances():
            path = self.tree.get_node_path(instance.uri)
            if not path:
                continue
            
            # 检查路径是否包含所有指定的组件
            display_names = [node.display_name for node in path]
            
            if all(component in display_names for component in path_components):
                matching_instances.append(instance)
        
        return matching_instances
    
    def get_instances_at_depth(self, depth: int) -> List[TreeNode]:
        """获取指定深度的所有实例"""
        result = []
        
        for instance in self.tree.get_all_instances():
            path = self.tree.get_node_path(instance.uri)
            if path and len(path) == depth:
                result.append(instance)
        
        return result
    
    def get_folder_hierarchy(self) -> Dict[str, List[str]]:
        """获取文件夹层级结构"""
        hierarchy = {}
        
        for folder in self.tree.get_all_folders():
            children = self.tree.get_children(folder.uri)
            if children:
                hierarchy[folder.display_name] = [child.display_name for child in children]
        
        return hierarchy
    
    def export_instance_list(self) -> List[Dict[str, Any]]:
        """导出所有实例为列表"""
        instances = []
        
        for instance in self.tree.get_all_instances():
            path = self.tree.get_node_path(instance.uri)
            breadcrumb = " > ".join([node.display_name for node in path]) if path else ""
            
            instances.append({
                'uri': instance.uri,
                'display_name': instance.display_name,
                'browse_name': instance.browse_name,
                'loop_type': instance.get_loop_type(),
                'description': instance.description,
                'breadcrumb_path': breadcrumb,
                'depth': len(path) if path else 0
            })
        
        return instances
