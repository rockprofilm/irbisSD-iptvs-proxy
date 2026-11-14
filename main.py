import os
import re
import threading
import requests

from urllib.parse import urljoin
from flask import Flask, Response, abort, request

app = Flask(__name__)

API_ACCESS_TOKEN = os.environ.get("API_ACCESS_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "5858")

if not API_ACCESS_TOKEN:
    raise RuntimeError("API_ACCESS_TOKEN environment variable is missing")

API_URL = (
    f"https://birgetv.platform24.tv"
    f"/v2/channels/{CHANNEL_ID}/stream"
)

session = requests.Session()

session.headers.update({
    "User-Agent": "VLC/3.0.21 LibVLC/3.0.21",
    "Accept": "*/*",
})

CURRENT_BASE_URL = None
base_lock = threading.Lock()


def get_master_url():
    response = session.get(
        API_URL,
        params={
            "access_token": API_ACCESS_TOKEN,
            "force_https": "true"
        },
        timeout=15
    )

    response.raise_for_status()

    data = response.json()
    master_url = data.get("hls_mbr")

    if not master_url:
        raise RuntimeError("API response does not contain hls_mbr")

    if not master_url.startswith(
        "https://stream.qfilm.platform24.tv/mbrjwt/"
    ):
        raise RuntimeError("Unexpected hls_mbr URL")

    return master_url


def get_media_playlist():
    global CURRENT_BASE_URL

    master_url = get_master_url()

    master_response = session.get(
        master_url,
        timeout=15
    )

    master_response.raise_for_status()

    variant_uri = None

    for line in master_response.text.splitlines():
        line = line.strip()

        if line and not line.startswith("#"):
            variant_uri = line
            break

    if not variant_uri:
        raise RuntimeError("Master Playlist has no variant URI")

    media_url = urljoin(master_url, variant_uri)

    base_url = urljoin(media_url, "./").rstrip("/")

    media_response = session.get(
        media_url,
        timeout=15
    )

    media_response.raise_for_status()

    with base_lock:
        CURRENT_BASE_URL = base_url

    return media_response.text


@app.route("/")
def index():
    return "Irbis TV Proxy is running", 200


@app.route("/health")
def health():
    return {
        "status": "online",
        "channel": CHANNEL_ID
    }, 200


@app.route("/irbis.m3u8")
def playlist():
    try:
        playlist_text = get_media_playlist()

        output = []

        for line in playlist_text.splitlines():
            line = line.strip()

            if line and not line.startswith("#"):

                match = re.fullmatch(
                    r"0/(\d+\.ts)(\?.*)?",
                    line
                )

                if not match:
                    abort(502)

                segment_name = match.group(1)
                query = match.group(2) or ""

                output.append(
                    f"/irbis/{segment_name}{query}"
                )

            else:
                output.append(line)

        return Response(
            "\n".join(output) + "\n",
            content_type="application/vnd.apple.mpegurl",
            headers={
                "Cache-Control": "no-cache, no-store"
            }
        )

    except requests.RequestException:
        abort(502)

    except (ValueError, KeyError, RuntimeError):
        abort(502)


@app.route("/irbis/<segment>")
def segment(segment):
    global CURRENT_BASE_URL

    if not re.fullmatch(r"\d+\.ts", segment):
        abort(404)

    with base_lock:
        base_url = CURRENT_BASE_URL

    try:
        if not base_url:
            get_media_playlist()

            with base_lock:
                base_url = CURRENT_BASE_URL

        url = f"{base_url}/0/{segment}"

        query = request.query_string.decode("ascii")

        if query:
            url += f"?{query}"

        upstream = session.get(
            url,
            stream=True,
            timeout=(10, 30)
        )

        # Если JWT истёк — получаем новый через API
        if upstream.status_code in (401, 403):
            upstream.close()

            get_media_playlist()

            with base_lock:
                base_url = CURRENT_BASE_URL

            url = f"{base_url}/0/{segment}"

            if query:
                url += f"?{query}"

            upstream = session.get(
                url,
                stream=True,
                timeout=(10, 30)
            )

        if upstream.status_code != 200:
            status = upstream.status_code
            upstream.close()
            abort(status)

        def generate():
            try:
                for chunk in upstream.iter_content(
                    chunk_size=64 * 1024
                ):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()

        return Response(
            generate(),
            content_type="video/mp2t",
            headers={
                "Cache-Control": "no-cache"
            }
        )

    except requests.RequestException:
        abort(502)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
