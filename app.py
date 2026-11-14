import os
import requests
from flask import Flask, Response, request

app = Flask(__name__)

# Оперативное хранилище ссылки на поток
current_stream_data = {"hls_mbr": None}


@app.route("/update_link", methods=["POST"])
def update_link():
  """Эндпоинт, принимающий свежую ссылку от GitHub Actions"""
  data = request.json
  hls_mbr = data.get("hls_mbr")
  if hls_mbr:
    current_stream_data["hls_mbr"] = hls_mbr
    print(f"[+] Ссылка успешно обновлена из GitHub Actions!")
    return {"status": "success"}, 200
  return {"status": "error", "message": "No hls_mbr provided"}, 400


@app.route("/irbis.m3u8")
def proxy_playlist():
  """Эндпоинт, который запрашивает ваш телевизор"""
  hls_mbr = current_stream_data.get("hls_mbr")
  if not hls_mbr:
    return (
        "Ссылка еще не получена. Ожидайте первый запуск GitHub Actions.",
        503,
    )

  try:
    # Проксируем плейлист телевизору
    resp = requests.get(hls_mbr, timeout=10)
    return Response(resp.text, content_type="application/vnd.apple.mpegurl")
  except Exception as e:
    return f"Proxy error: {e}", 500


if __name__ == "__main__":
  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port)
