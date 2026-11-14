import os
import sys
import time
import requests

print("[*] Старт скрипта update.py")
render_url = os.environ.get("RENDER_URL")
target_page = "https://app.birge.tv/channels/1/irbis-tv"

print(f"[*] Целевой адрес: {target_page}")
print(
    f"[*] RENDER_URL: {render_url if render_url else 'НЕ ЗАДАН (проверьте Secrets)'}"
)

captured_hls_mbr = None

try:
  from playwright.sync_api import sync_playwright

  print("[*] Инициализация Playwright...")
  with sync_playwright() as p:
    print("[*] Запуск Chromium в headless-режиме...")
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
        ],
    )
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    )
    page = context.new_page()

    def handle_response(response):
      global captured_hls_mbr
      url = response.url
      if (
          "stream" in url
          or "hls_mbr" in url
          or "channels/5858" in url
          or "playlist" in url
      ):
        try:
          data = response.json()
          hls_mbr = (
              data.get("data", {}).get("hls_mbr")
              or data.get("hls_mbr")
              or data.get("url")
          )
          if hls_mbr and "http" in hls_mbr:
            captured_hls_mbr = hls_mbr
            print(f"[+] Перехвачена ссылка: {captured_hls_mbr[:70]}...")
        except Exception:
          pass

    page.on("response", handle_response)

    print(f"[*] Переходим на страницу {target_page}...")
    page.goto(target_page, timeout=60000, wait_until="domcontentloaded")

    print("[*] Ожидаем загрузку элементов (10 сек)...")
    time.sleep(10)

    # Кликом активируем плеер на случай автопаузы
    try:
      print("[*] Имитируем клик по плееру для запуска вещания...")
      page.click("body", timeout=3000)
      time.sleep(5)
    except Exception as e:
      print(f"[!] Не удалось сделать клик: {e}")

    browser.close()
    print("[*] Браузер закрыт.")

except Exception as e:
  print(f"[!] КРИТИЧЕСКАЯ ОШИБКА PLAYWRIGHT: {e}")

if captured_hls_mbr and render_url:
  print(f"[+] Отправка найденной ссылки на Render ({render_url})...")
  try:
    resp = requests.post(
        f"{render_url.rstrip('/')}/update_link",
        json={"hls_mbr": captured_hls_mbr},
        timeout=15,
    )
    print(f"[+] Ответ Render: {resp.status_code} - {resp.text}")
  except Exception as e:
    print(f"[!] Ошибка отправки запроса на Render: {e}")
else:
  print(
      "[-] ИТОГ: Ссылка не поймана или RENDER_URL не настроен в GitHub Secrets."
  )
