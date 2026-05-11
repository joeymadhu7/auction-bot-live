import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")

STARTING_PURSE = 200
MAX_PLAYERS = 8
BID_TIMEOUT = 15

ADMIN_IDS = [8212194710, 8548675437, 7751493709, 6023570085,]
