import os
import sys
import time
import requests

print("[*] Старт обновленного скрипта update.py")
render_url = os.environ.get("RENDER_URL")
target_page = "https://app.birge.tv/channels/1/irbis-tv"

print(f"[*] Целевой адрес: {target_page}")
print(f"[*] RENDER_URL: {render_url if render_url else 'НЕ ЗАДАН'}")

captured_hls_mbr = None

try:
  from playwright.sync_api import sync_playwright

  print("[*] Инициализация Playwright...")
  with sync_playwright() as p:
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

      # Игнорируем статику (картинки, CSS, шрифты)
      if any(
          ext in url
          for ext in [".png", ".jpg", ".jpeg", ".css", ".woff", ".js", ".svg"]
      ):
        return

      # Проверяем все ответы, похожие на API или потоковые ссылки
      try:
        # Вариант 1: Попытка разбора JSON-ответа
        if "application/json" in response.headers.get("content-type", ""):
          data = response.json()
          # Ищем ключи hls_mbr, hls, stream, url в любых вложенных словарях
          possible_url = None
          if isinstance(data, dict):
            # Проход по типовым структурам API
            d = data.get("data", data)
            if isinstance(d, dict):
              possible_url = (
                  d.get("hls_mbr")
                  or d.get("hls")
                  or d.get("stream")
                  or d.get("url")
              )

          if possible_url and "http" in str(possible_url):
            captured_hls_mbr = possible_url
            print(f"[+] [JSON] Перехвачена ссылка: {captured_hls_mbr[:80]}...")

        # Вариант 2: Прямой перехват запроса/редиректа с расширением .m3u8
        elif ".m3u8" in url and not captured_hls_mbr:
          captured_hls_mbr = url
          print(
              f"[+] [Direct M3U8] Перехвачена ссылка:"
              f" {captured_hls_mbr[:80]}..."
          )

      except Exception:
        pass

    page.on("response", handle_response)

    print(f"[*] Переходим на страницу {target_page}...")
    page.goto(target_page, timeout=60000, wait_until="networkidle")

    print("[*] Ожидаем инициализации плеера (8 сек)...")
    time.sleep(8)

    # Если ссылка еще не поймана, делаем клики по области плеера
    if not captured_hls_mbr:
      try:
        print("[*] Клик по центру экрана для запуска вещания...")
        page.mouse.click(640, 360)
        time.sleep(5)
      except Exception as e:
        print(f"[!] Ошибка клика: {e}")

    browser.close()
    print("[*] Браузер закрыт.")

except Exception as e:
  print(f"[!] КРИТИЧЕСКАЯ ОШИБКА: {e}")

# Отправка результатов
if captured_hls_mbr and render_url:
  clean_render_url = render_url.rstrip("/")
  print(f"[+] Отправка ссылки на Render ({clean_render_url})...")
  try:
    resp = requests.post(
        f"{clean_render_url}/update_link",
        json={"hls_mbr": captured_hls_mbr},
        timeout=15,
    )
    print(f"[+] Ответ Render: {resp.status_code} - {resp.text}")
  except Exception as e:
    print(f"[!] Ошибка запроса к Render: {e}")
else:
  print("[-] ИТОГ: Ссылка не поймана или RENDER_URL не настроен.")
