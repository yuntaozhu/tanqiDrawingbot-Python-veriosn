import logging
import os
import sys
import contextvars

_trace_id_var = contextvars.ContextVar("trace_id", default="")

class TraceIdFilter(logging.Filter):
    def filter(self, record):
        tid = _trace_id_var.get()
        record.trace_id = f" [TraceID: {tid}]" if tid else ""
        return True

def set_trace_id(trace_id: str):
    _trace_id_var.set(trace_id)

def get_trace_id() -> str:
    return _trace_id_var.get()

def setup_logger(name: str):
    logger = logging.getLogger(name)
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level_str, logging.INFO)
    logger.setLevel(level)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # Formatter with dynamic trace_id field
    formatter = logging.Formatter('%(asctime)s - %(name)s%(trace_id)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    
    # Add Trace ID filter to the handler
    console_handler.addFilter(TraceIdFilter())
    
    # Add handler if not already present
    if not logger.handlers:
        logger.addHandler(console_handler)
        
    return logger


# Example usage:
# logger = setup_logger("toddler_app")
