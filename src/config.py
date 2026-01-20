"""Configuration settings for the tax calculator."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / '.env')

class Config:
    # Project paths
    PROJECT_ROOT = PROJECT_ROOT
    DATA_DIR = PROJECT_ROOT / 'data'
    OUTPUT_DIR = PROJECT_ROOT / 'output'
    
    # Long Bridge API credentials
    LONGBRIDGE_APP_KEY = os.getenv('LONGBRIDGE_APP_KEY')
    LONGBRIDGE_APP_SECRET = os.getenv('LONGBRIDGE_APP_SECRET')
    LONGBRIDGE_ACCESS_TOKEN = os.getenv('LONGBRIDGE_ACCESS_TOKEN')
    
    # Database settings
    DATABASE_PATH = DATA_DIR / 'tax_calculator.db'
    
    # Tax calculation settings
    CAPITAL_GAINS_TAX_RATE = 0.20  # 20% for Chinese residents
    DEFAULT_TAX_YEAR = 2024
    
    @classmethod
    def init_dirs(cls):
        """Create necessary directories."""
        cls.DATA_DIR.mkdir(exist_ok=True)
        cls.OUTPUT_DIR.mkdir(exist_ok=True)
    
    @classmethod
    def validate(cls):
        """Validate required configuration."""
        required = ['LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN']
        missing = [f for f in required if not getattr(cls, f)]
        
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        
        return True