"""Parse workflow syntax into node connections."""

import re
from typing import List, Tuple, Optional


class WorkflowParser:
    """Parse >> syntax into workflow nodes and edges."""
    
    @staticmethod
    def parse_workflow(workflow_lines: List[str]) -> List[Tuple[str, Optional[str], str]]:
        """
        Parse workflow lines into (source, action, target) tuples.
        
        Examples:
            "tool_a >> tool_b" -> [("tool_a", None, "tool_b")]
            "tool_a - 'error' >> tool_b" -> [("tool_a", "error", "tool_b")]
        
        Returns:
            List of (source_node, action, target_node) tuples
        """
        connections = []
        
        for line in workflow_lines:
            line = line.strip()
            if not line or not '>>' in line:
                continue
            
            # Match: "source >> target" or "source - 'action' >> target"
            match = re.match(r"(\w+)(?:\s*-\s*['\"](\w+)['\"])?\s*>>\s*(\w+)", line)
            
            if match:
                source = match.group(1)
                action = match.group(2)  # None if no conditional
                target = match.group(3)
                
                connections.append((source, action, target))
        
        return connections
    
    @staticmethod
    def get_ordered_nodes(connections: List[Tuple[str, Optional[str], str]]) -> List[str]:
        """
        Extract ordered list of unique nodes from connections.
        Preserves execution order (source nodes before target nodes).
        """
        nodes = []
        seen = set()
        
        for source, _, target in connections:
            if source not in seen:
                nodes.append(source)
                seen.add(source)
            if target not in seen:
                nodes.append(target)
                seen.add(target)
        
        return nodes
    
    @staticmethod
    def get_start_node(connections: List[Tuple[str, Optional[str], str]]) -> str:
        """Get the first node in the workflow (node that's never a target)."""
        if not connections:
            raise ValueError("No workflow connections found")
        
        # Find nodes that appear as sources but never as targets
        sources = {conn[0] for conn in connections}
        targets = {conn[2] for conn in connections}
        start_nodes = sources - targets
        
        if not start_nodes:
            # No clear start node, return first source
            return connections[0][0]
        
        # Return the first start node (in case of multiple entry points)
        return list(start_nodes)[0]
