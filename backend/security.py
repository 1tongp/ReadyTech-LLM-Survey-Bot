import os
from dotenv import load_dotenv
from fastapi import HTTPException, Header

load_dotenv()
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "change-me")

def verify_admin(x_api_key: str = Header(default="")):
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin API key")
