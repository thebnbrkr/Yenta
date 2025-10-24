import re
from typing import List, Tuple, Optional, Dict


class WorkflowParser:
    """Parse >> syntax into workflow nodes and edges."""
    
    @staticmethod
    def parse_workflow(workflow_lines: List[str]) -> List[Tuple[str, Optional[str], str, Optional[List[str]]]]:
        """
        Parse workflow lines into (source, action, target, params) tuples.
        
        Examples:
            "tool_a >> tool_b" -> [("tool_a", None, "tool_b", None)]
            "tool_a - 'error' >> tool_b" -> [("tool_a", "error", "tool_b", None)]
            "tool_a >> tool_b[url]" -> [("tool_a", None, "tool_b", ["url"])]
            "tool_a >> tool_b[url,limit]" -> [("tool_a", None, "tool_b", ["url", "limit"])]
            "tool_a" -> [("tool_a", None, "complete", None)]  # Single tool
        
        Returns:
            List of (source_node, action, target_node, params) tuples
        """
        connections = []
        
        for line in workflow_lines:
            line = line.strip()
            if not line:
                continue
            
            # Check if it's a single tool (no >>)
            if '>>' not in line:
                # Single tool workflow
                tool_name = line.strip()
                connections.append((tool_name, None, "complete", None))
                continue
            
            # Match: "source[params] >> target[params]" or "source - 'action' >> target[params]"
            # Pattern breakdown:
            # (\w+) - source node
            # (?:\[([^\]]+)\])? - optional source params [param1,param2]
            # (?:\s*-\s*['\"](\w+)['\"])? - optional action
            # \s*>>\s* - separator
            # (\w+) - target node
            # (?:\[([^\]]+)\])? - optional target params [param1,param2]
            match = re.match(
                r"(\w+)(?:\[([^\]]+)\])?(?:\s*-\s*['\"](\w+)['\"])?\s*>>\s*(\w+)(?:\[([^\]]+)\])?", 
                line
            )
            
            if match:
                source = match.group(1)
                source_params_str = match.group(2)  # Source params (new!)
                action = match.group(3)  # None if no conditional
                target = match.group(4)
                target_params_str = match.group(5)  # Target params
                
                # For now, we only support params on TARGET (not source)
                # But we need to parse source params to not break the regex
                # Future: could support both source and target params
                
                # Parse target params if present
                params = None
                if target_params_str:
                    # Split by comma and strip whitespace
                    params = [p.strip() for p in target_params_str.split(',')]
                elif source_params_str:
                    # If params are on source (legacy format), use those
                    params = [p.strip() for p in source_params_str.split(',')]
                
                connections.append((source, action, target, params))
        
        return connections
    
    @staticmethod
    def get_ordered_nodes(connections: List[Tuple[str, Optional[str], str, Optional[List[str]]]]) -> List[str]:
        """Extract ordered list of unique nodes from connections."""
        nodes = []
        seen = set()
        
        for source, _, target, _ in connections:
            if source not in seen:
                nodes.append(source)
                seen.add(source)
            # Don't add "complete" as a node
            if target != "complete" and target not in seen:
                nodes.append(target)
                seen.add(target)
        
        return nodes
    
    @staticmethod
    def get_start_node(connections: List[Tuple[str, Optional[str], str, Optional[List[str]]]]) -> str:
        """Get the first node in the workflow."""
        if not connections:
            raise ValueError("No workflow connections found")
        
        # Return first source node
        return connections[0][0]
    
    @staticmethod
    def get_node_params(
        connections: List[Tuple[str, Optional[str], str, Optional[List[str]]]], 
        node_name: str
    ) -> Optional[List[str]]:
        """
        Get the explicitly specified parameters for a node.
        
        Args:
            connections: List of parsed connections
            node_name: Name of the node to look up
        
        Returns:
            List of parameter names if specified, None otherwise
        
        Example:
            For "scrape_url >> map_website[url]"
            get_node_params(connections, "map_website") -> ["url"]
        """
        for _, _, target, params in connections:
            if target == node_name and params:
                return params
        return None
