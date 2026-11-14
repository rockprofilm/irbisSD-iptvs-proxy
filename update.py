import os
import time
import requests

print("[*] Импорт библиотек завершен успешно.")

render_url = os.environ.get("RENDER_URL")
target_page = "https://app.birge.tv/channels/1/irbis-tv"

print(f"[*] Целевой адрес: {target_page}")
print(f"[*] RENDER_URL задан: {'Да' if render_url else 'ЕТ'}")

captured_hls_mbr = None

try:
  from playwright.sync_api import sync_playwright

  print("[*] Запуск Playwright...")
  with sync_playwright() as p:
    # Запускаем Chromium с отключенной песочницей для Linux
