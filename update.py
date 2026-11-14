import os
import time
import requests
from playwright.sync_api import sync_playwright

render_url = os.environ.get("RENDER_URL")
target_page = "https://app.birge.tv/channels/1/irbis-tv"

print("[*] Запуск Playwright в GitHub Actions...")
captured_hls_mbr = None

with sync_playwright() as p:
  browser = p.chromium
