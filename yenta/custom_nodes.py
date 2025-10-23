"""
Custom node types for user-defined workflow logic.

ValidationNode: For conditional routing based on data validation
RoutingNode: For complex routing decisions
TransformNode: For data transformation between nodes
"""

from typing import Any, Dict, Optional, List
from agora.telemetry import AuditedAsyncNode


class ValidationNode(AuditedAsyncNode):
    """
    Base class for user-defined validation and routing logic.
    
    Users extend this class and implement `validate()` method to return
    a routing key that determines the next node.
    
    Example:
        class CheckCacheNode(ValidationNode):
            def validate(self, input_data):
                if input_data.get("cache_hit"):
                    return "hit"  # Route to cached result handler
                return "miss"    # Route to fetch data
        
        # Wire it up:
        check_cache - "hit" >> return_cached
        check_cache - "miss" >> fetch_data
    """
    
    def __init__(
        self, 
        name: str, 
        audit_logger, 
        allowed_routes: Optional[List[str]] = None,
        default_route: str = "default",
        max_retries: int = 1,
        wait: int = 0
    ):
        super().__init__(name, audit_logger, max_retries, wait)
        self.allowed_routes = allowed_routes
        self.default_route = default_route
    
    async def prep_async(self, shared: Dict[str, Any]) -> Any:
        """Get input from previous node's output"""
        # Check if this is the first node with initial input
        if f"{self.name}_input" in shared:
            return shared[f"{self.name}_input"]
        
        # Get output from previous node
        prev_output_key = shared.get("_prev_output_key")
        if prev_output_key:
            return shared.get(prev_output_key, {})
        
        return {}
    
    async def exec_async(self, input_data: Any) -> str:
        """Execute validation logic and return routing key"""
        try:
            routing_key = self.validate(input_data)
            
            # Validate routing key if allowed_routes specified
            if self.allowed_routes and routing_key not in self.allowed_routes:
                print(f"⚠️  Invalid route '{routing_key}' from {self.name}. Using default.")
                return self.default_route
            
            return routing_key
            
        except Exception as e:
            print(f"❌ Validation error in {self.name}: {e}")
            return "error"
    
    async def post_async(self, shared: Dict[str, Any], prep_res: Any, routing_key: str) -> str:
        """Store input data and return routing key"""
        # Store the original input for debugging
        output_key = f"{self.name}_output"
        shared[output_key] = {
            "input": prep_res,
            "routing_key": routing_key
        }
        shared["_prev_output_key"] = output_key
        
        return routing_key
    
    def validate(self, input_data: Any) -> str:
        """
        User-defined validation logic.
        
        Args:
            input_data: Input from previous node
        
        Returns:
            Routing key (string) determining next node
        
        Raises:
            NotImplementedError: If not overridden by user
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement validate() method"
        )


class RoutingNode(AuditedAsyncNode):
    """
    Advanced routing node with support for multiple conditions.
    
    Example:
        class QueryRouter(RoutingNode):
            def route(self, input_data):
                query_type = input_data.get("type")
                confidence = input_data.get("confidence", 0)
                
                if confidence < 0.5:
                    return "low_confidence_handler"
                elif query_type == "search":
                    return "search"
                elif query_type == "generate":
                    return "generate"
                else:
                    return "default"
    """
    
    def __init__(
        self,
        name: str,
        audit_logger,
        routes: Optional[Dict[str, str]] = None,
        default_route: str = "default",
        max_retries: int = 1,
        wait: int = 0
    ):
        super().__init__(name, audit_logger, max_retries, wait)
        self.routes = routes or {}
        self.default_route = default_route
    
    async def prep_async(self, shared: Dict[str, Any]) -> Any:
        """Get input from previous node"""
        if f"{self.name}_input" in shared:
            return shared[f"{self.name}_input"]
        
        prev_output_key = shared.get("_prev_output_key")
        if prev_output_key:
            return shared.get(prev_output_key, {})
        
        return {}
    
    async def exec_async(self, input_data: Any) -> str:
        """Execute routing logic"""
        try:
            routing_key = self.route(input_data)
            return routing_key
        except Exception as e:
            print(f"❌ Routing error in {self.name}: {e}")
            return "error"
    
    async def post_async(self, shared: Dict[str, Any], prep_res: Any, routing_key: str) -> str:
        """Store routing decision and return key"""
        output_key = f"{self.name}_output"
        shared[output_key] = {
            "input": prep_res,
            "routing_key": routing_key
        }
        shared["_prev_output_key"] = output_key
        
        return routing_key
    
    def route(self, input_data: Any) -> str:
        """
        User-defined routing logic.
        
        Args:
            input_data: Input from previous node
        
        Returns:
            Routing key (string) determining next node
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement route() method"
        )


class TransformNode(AuditedAsyncNode):
    """
    Transform data between nodes without changing routing.
    
    Example:
        class ExtractEmbedding(TransformNode):
            def transform(self, input_data):
                # Extract just the embedding vector
                return {
                    "embedding": input_data.get("embedding"),
                    "metadata": input_data.get("metadata")
                }
    """
    
    def __init__(
        self,
        name: str,
        audit_logger,
        next_node: str = "default",
        max_retries: int = 1,
        wait: int = 0
    ):
        super().__init__(name, audit_logger, max_retries, wait)
        self.next_node = next_node
    
    async def prep_async(self, shared: Dict[str, Any]) -> Any:
        """Get input from previous node"""
        if f"{self.name}_input" in shared:
            return shared[f"{self.name}_input"]
        
        prev_output_key = shared.get("_prev_output_key")
        if prev_output_key:
            return shared.get(prev_output_key, {})
        
        return {}
    
    async def exec_async(self, input_data: Any) -> Any:
        """Execute transformation"""
        try:
            return self.transform(input_data)
        except Exception as e:
            print(f"❌ Transform error in {self.name}: {e}")
            return input_data  # Return original on error
    
    async def post_async(self, shared: Dict[str, Any], _, transformed_data: Any) -> str:
        """Store transformed data"""
        output_key = f"{self.name}_output"
        shared[output_key] = transformed_data
        shared["_prev_output_key"] = output_key
        
        return self.next_node
    
    def transform(self, input_data: Any) -> Any:
        """
        User-defined transformation logic.
        
        Args:
            input_data: Input from previous node
        
        Returns:
            Transformed data
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement transform() method"
        )


# ======================================================================
# EXAMPLE IMPLEMENTATIONS
# ======================================================================

class RetryHandler(ValidationNode):
    """
    Example: Retry logic with max attempts.
    
    Usage:
        retry - "retry" >> fetch_data
        retry - "max_retries" >> log_failure
    """
    
    def __init__(self, name: str, audit_logger, max_attempts: int = 3):
        super().__init__(name, audit_logger, allowed_routes=["retry", "max_retries"])
        self.max_attempts = max_attempts
    
    def validate(self, input_data: Any) -> str:
        retry_count = input_data.get("retry_count", 0)
        
        if retry_count < self.max_attempts:
            return "retry"
        return "max_retries"


class ErrorHandler(ValidationNode):
    """
    Example: Route based on error type.
    
    Usage:
        error_handler - "retry" >> fetch_data
        error_handler - "skip" >> next_step
        error_handler - "fatal" >> log_failure
    """
    
    def __init__(self, name: str, audit_logger):
        super().__init__(
            name, 
            audit_logger, 
            allowed_routes=["retry", "skip", "fatal"]
        )
    
    def validate(self, input_data: Any) -> str:
        error = input_data.get("error", {})
        error_type = error.get("type", "unknown")
        
        if error_type in ["TimeoutError", "ConnectionError"]:
            return "retry"
        elif error_type in ["ValidationError", "SchemaError"]:
            return "skip"
        else:
            return "fatal"


class ConditionalRouter(RoutingNode):
    """
    Example: Route based on multiple conditions.
    
    Usage:
        router - "high" >> priority_handler
        router - "medium" >> standard_handler
        router - "low" >> batch_handler
    """
    
    def route(self, input_data: Any) -> str:
        priority = input_data.get("priority", "medium")
        confidence = input_data.get("confidence", 0.5)
        
        if confidence < 0.3:
            return "low_confidence"
        elif priority == "urgent":
            return "high"
        elif priority == "normal":
            return "medium"
        else:
            return "low"