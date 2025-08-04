import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

# Create logs directory if it doesn't exist
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

def get_logger(name: str, log_level: int = logging.INFO) -> logging.Logger:
    """
    Get a logger with the specified name.
    
    Args:
        name (str): Name of the logger (will be used as part of the log filename)
        log_level (int): Logging level (default: logging.INFO)
        
    Returns:
        logging.Logger: Configured logger instance
    """
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Create log file handler
    log_filename = f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
    log_path = os.path.join(LOG_DIR, log_filename)
    
    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(formatter)
    
    # Add handler to logger if not already added
    if not logger.handlers:
        logger.addHandler(file_handler)
    
    return logger

def log_data(data_name: str, message: str, level: str = 'info') -> None:
    """
    Log a message for specific data.
    
    Args:
        data_name (str): Name of the data (will be used for the log filename)
        message (str): Message to log
        level (str): Log level ('debug', 'info', 'warning', 'error', 'critical')
    """
    logger = get_logger(data_name)
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(log_level, message)

