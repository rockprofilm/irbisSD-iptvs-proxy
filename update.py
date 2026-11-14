import json
import os
import re
import sys
import time
import requests

print("[*] Старт обновленного скрипта update.py (v3)")
render_url = os.environ.get("RENDER_URL")
target_page = "https://app.birge.tv/channels/1/irbis-tv"

print(f"[*] Целевой адрес: {target_page}")
print(
    f"[*] RENDER_URL: {render_url if render_url else 'НЕ ЗАДАН (проверьте Secrets)'}"
)

captured_hls_mbr = None
all_api_urls = []


def extract_m3u8_from_text(text):
  """Поиск любой ссылки .m3u8 в тексте или JSON"""
  match = re.search(r"https?://[^\s\"'\\]+\.m3u8[^\s\"'\\]*", text)
  if match:
    return match.group(0).replace("\\/", "/")
  return None


try:
  from playwright.sync_api import sync_playwright

  print("[*] Инициализация Playwright...")
  with sync_playwright() as p:
    # Запуск с аргументами, разрешающими автозапуск видео без жестких проверок браузера
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--autoplay-policy=no-user-gesture-required",
            "--no-first-run",
            "--use-fake-ui-for-media-stream",
        ],
    )

    # Настраиваем размер экрана как у обычного десктопа
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    def inspect_url_and_body(url, body_text=""):
      global captured_hls_mbr
      if captured_hls_mbr:
        return

      # 1. Прямой поиск .m3u8 в URL
      if ".m3u8" in url:
        captured_hls_mbr = url
        print(f"[+] [Direct M3U8 URL] Найдено: {captured_hls_mbr[:90]}")
        return

      # 2. Поиск .m3u8 внутри тела ответа
      found_in_body = extract_m3u8_from_text(body_text)
      if found_in_body:
        captured_hls_mbr = found_in_body
        print(f"[+] [Extracted M3U8 Body] Найдено: {captured_hls_mbr[:90]}")
        return

    def handle_response(response):
      global captured_hls_mbr
      url = response.url

      # Фильтруем статические ресурсы
      if any(
          ext in url
          for ext in [
              ".png",
              ".jpg",
              ".jpeg",
              ".css",
              ".woff",
              ".svg",
              ".js",
              ".ico",
          ]
      ):
        return

      all_api_urls.append(f"[{response.status}] {url[:100]}")

      try:
        content_type = response.headers.get("content-type", "").lower()
        if (
            "json" in content_type
            or "mpegurl" in content_type
            or "javascript" in content_type
            or "stream" in url
        ):
          text = response.text()
          inspect_url_and_body(url, text)
      except Exception:
        pass

    def handle_websocket(ws):
      """Слушаем WebSocket соединения на случай динамической передачи токена"""

      def frame_received(frame):
        global captured_hls_mbr
        if frame:
          inspect_url_and_body("ws_frame", str(frame))

      ws.on("framereceived", frame_received)

    page.on("response", handle_response)
    page.on("websocket", handle_websocket)

    print(f"[*] Загрузка страницы: {target_page}...")
    page.goto(target_page, timeout=60000, wait_until="domcontentloaded")

    print("[*] Ожидаем появление элементов плеера...")
    time.sleep(5)

    # Кликаем конкретно по элементам плеера или видеокадра
    selectors_to_click = [
      "video",
      ".vjs-tech",
      ".player",
      "#player",
      "iframe",
      "button",
    ]
    for selector in selectors_to_click:
      if captured_hls_mbr:
        break
      try:
        elem = page.query_selector(selector)
        if elem:
          print(f"[*] Клик по селектору: '{selector}'")
          elem.click(timeout=2000)
          time.sleep(3)
      except Exception:
        pass

    # Пауза для завершения XHR запросов
    if not captured_hls_mbr:
      print("[*] Финальное ожидание ответов сети (7 сек)...")
      time.sleep(7)

    browser.close()
    print("[*] Браузер закрыт.")

except Exception as e:
  print(f"[!] КРИТИЧЕСКАЯ ОШИБКА: {e}")

# Диагностический вывод, если ничего не поймали
if not captured_hls_mbr:
  print("\n[-] Ссылка не найдена. Перехваченные API-запросы сервера:")
  for u in all_api_urls[-15:]:
    print(f"    {u}")

# Отправка данных на Render
if captured_hls_mbr and render_url:
  clean_render_url = render_url.rstrip("/")
  print(f"\n[+] Отправка ссылки на Render ({clean_render_url})...")
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
  print(
      "\n[-] ИТОГ: Ссылка не отправлена. Проверьте логи перехваченных запросов"
      " выше."
  )
