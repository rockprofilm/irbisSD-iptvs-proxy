import os
import re
import sys
import time
import requests

print("[*] Старт скрипта update.py (с поддержкой Proxy)")
render_url = os.environ.get("RENDER_URL")
proxy_url = os.environ.get("PROXY_URL")

target_page = "https://app.birge.tv/channels/1/irbis-tv"

print(f"[*] Целевой адрес: {target_page}")
print(f"[*] RENDER_URL задан: {'Да' if render_url else 'НЕТ'}")
print(f"[*] PROXY_URL задан: {'Да (' + proxy_url + ')' if proxy_url else 'НЕТ'}")

captured_hls_mbr = None
all_api_urls = []


def extract_m3u8_from_text(text):
  match = re.search(r"https?://[^\s\"'\\]+\.m3u8[^\s\"'\\]*", text)
  if match:
    return match.group(0).replace("\\/", "/")
  return None


try:
  from playwright.sync_api import sync_playwright

  print("[*] Инициализация Playwright...")
  with sync_playwright() as p:
    # Настраиваем параметры запуска, включая прокси, если он задан
    launch_args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--autoplay-policy=no-user-gesture-required",
    ]

    browser_config = {"headless": True, "args": launch_args}

    if proxy_url:
      browser_config["proxy"] = {"server": proxy_url}

    browser = p.chromium.launch(**browser_config)

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

      if ".m3u8" in url:
        captured_hls_mbr = url
        print(f"[+] [Direct M3U8 URL] Найдено: {captured_hls_mbr[:90]}")
        return

      found_in_body = extract_m3u8_from_text(body_text)
      if found_in_body:
        captured_hls_mbr = found_in_body
        print(f"[+] [Extracted M3U8 Body] Найдено: {captured_hls_mbr[:90]}")
        return


    def handle_response(response):
      global captured_hls_mbr
      url = response.url

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


    page.on("response", handle_response)

    print(f"[*] Загрузка страницы через прокси: {target_page}...")
    try:
      page.goto(target_page, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:
      print(
          "[!] Ошибка загрузки (возможно, прокси недоступен или лежит):"
          f" {e}"
      )

    print("[*] Ожидаем появление элементов плеера...")
    time.sleep(6)

    # Кликаем по плееру для инициализации потока
    try:
      elem = page.query_selector("video") or page.query_selector("button")
      if elem:
        print("[*] Клик по элементу плеера/кнопке...")
        elem.click(timeout=2000)
        time.sleep(4)
    except Exception:
      pass

    if not captured_hls_mbr:
      print("[*] Финальное ожидание ответов сети (7 сек)...")
      time.sleep(7)

    browser.close()
    print("[*] Браузер закрыт.")

except Exception as e:
  print(f"[!] КРИТИЧЕСКАЯ ОШИБКА PLAYWRIGHT: {e}")

if not captured_hls_mbr:
  print("\n[-] Ссылка не найдена. Последние запросы:")
  for u in all_api_urls[-15:]:
    print(f"    {u}")

# Отправка на Render
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
  print("\n[-] ИТОГ: Ссылка не отправлена.")
