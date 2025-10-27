"""
Retry logic and error handling utilities for MCP calls.
"""
import asyncio
import time
from typing import Any, Callable, Optional, Type, Union, List
from functools import wraps

class RetryConfig:
    """Configuration for retry behavior"""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: Optional[List[Type[Exception]]] = None
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions or [
            asyncio.TimeoutError,
            ConnectionError,
            OSError
        ]

def is_retryable_exception(exception: Exception, retryable_types: List[Type[Exception]]) -> bool:
    """Check if an exception is retryable"""
    return any(isinstance(exception, exc_type) for exc_type in retryable_types)

def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay for retry attempt"""
    delay = config.base_delay * (config.exponential_base ** (attempt - 1))
    delay = min(delay, config.max_delay)
    
    if config.jitter:
        # Add random jitter to prevent thundering herd
        import random
        jitter_factor = random.uniform(0.5, 1.5)
        delay *= jitter_factor
    
    return delay

async def retry_async(
    func: Callable,
    *args,
    config: Optional[RetryConfig] = None,
    **kwargs
) -> Any:
    """
    Retry an async function with exponential backoff.
    
    Args:
        func: Async function to retry
        *args: Arguments to pass to function
        config: Retry configuration
        **kwargs: Keyword arguments to pass to function
        
    Returns:
        Result of successful function call
        
    Raises:
        Last exception if all retries fail
    """
    if config is None:
        config = RetryConfig()
    
    last_exception = None
    
    for attempt in range(1, config.max_attempts + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            # Check if this exception is retryable
            if not is_retryable_exception(e, config.retryable_exceptions):
                raise e
            
            # If this was the last attempt, raise the exception
            if attempt == config.max_attempts:
                raise e
            
            # Calculate delay and wait
            delay = calculate_delay(attempt, config)
            await asyncio.sleep(delay)
    
    # This should never be reached, but just in case
    raise last_exception

def retryable(
    config: Optional[RetryConfig] = None,
    retryable_exceptions: Optional[List[Type[Exception]]] = None
):
    """
    Decorator to make an async function retryable.
    
    Args:
        config: Retry configuration
        retryable_exceptions: List of exception types to retry on
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            retry_config = config or RetryConfig()
            if retryable_exceptions:
                retry_config.retryable_exceptions = retryable_exceptions
            
            return await retry_async(func, *args, config=retry_config, **kwargs)
        return wrapper
    return decorator

# Predefined retry configurations
QUICK_RETRY = RetryConfig(max_attempts=2, base_delay=0.5, max_delay=5.0)
STANDARD_RETRY = RetryConfig(max_attempts=3, base_delay=1.0, max_delay=30.0)
PERSISTENT_RETRY = RetryConfig(max_attempts=5, base_delay=2.0, max_delay=120.0)
