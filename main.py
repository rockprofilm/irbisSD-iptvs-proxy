import os
import re
import requests

from flask import Flask, Response, abort

app = Flask(__name__)

SOURCE_URL = os.environ.get("SOURCE_URL")

if not SOURCE_URL:
    raise RuntimeError("SOURCE_URL environment variable is missing")

BASE_URL = SOURCE_URL.rsplit("/", 1)[0]

session = requests.Session()

session.headers.update({
    "User-Agent": "VLC/3.0.21 LibVLC/3.0.21",
    "Accept": "*/*",
})


@app.route("/")
def index():
    return "Irbis TV Proxy is running", 200


@app.route("/health")
def health():
    return {
        "status": "online",
        "channel": "Irbis TV"
    }, 200


@app.route("/irbis.m3u8")
def playlist():

    try:
        response = session.get(
            SOURCE_URL,
            timeout=15
        )

        response.raise_for_status()

        lines = response.text.splitlines()
        output = []

        for line in lines:

            line = line.strip()

            if line and not line.startswith("#"):

                segment_match = re.fullmatch(
                    r"0/(\d+\.ts)",
                    line
                )

                if not segment_match:
                    abort(502)

                segment_name = segment_match.group(1)

                output.append(
                    f"/irbis/{segment_name}"
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


@app.route("/irbis/<segment>")
def segment(segment):

    if not re.fullmatch(r"\d+\.ts", segment):
        abort(404)

    url = f"{BASE_URL}/0/{segment}"

    try:
        upstream = session.get(
            url,
            stream=True,
            timeout=(10, 30)
        )

        if upstream.status_code != 200:
            upstream.close()
            abort(upstream.status_code)

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