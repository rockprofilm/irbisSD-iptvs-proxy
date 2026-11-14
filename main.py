
import os
import re
import threading
import requests

from urllib.parse import urljoin, urlsplit, urlunsplit
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


# ==========================================
# SAFE LOGGING
# ==========================================

def safe_url(url):
    """Remove query parameters and JWT from logged URLs."""

    if not url:
        return None

    try:
        parts = urlsplit(str(url))

        path = re.sub(
            r"(/mbrjwt/)[^/]+",
            r"\1<REDACTED>",
            parts.path,
            flags=re.IGNORECASE
        )

        return urlunsplit((
            parts.scheme,
            parts.netloc,
            path,
            "",
            ""
        ))

    except Exception:
        return "<URL_REDACTED>"


def safe_playlist_sample(text, limit=8):
    """Return sanitized playlist lines for diagnostic logging."""

    lines = str(text).splitlines()[:limit]
    result = []

    for line in lines:

        line = re.sub(
            r"(/mbrjwt/)[^/]+",
            r"\1<REDACTED>",
            line,
            flags=re.IGNORECASE
        )

        line = re.sub(
            r"(?i)(access_token|token|jwt)=([^&\s\"]+)",
            r"\1=<REDACTED>",
            line
        )

        result.append(line[:500])

    return result


# ==========================================
# API: GET MASTER URL
# ==========================================

def get_master_url():

    app.logger.info("[M3U8] STEP 1: Requesting Birge API")

    try:

        response = session.get(
            API_URL,
            params={
                "access_token": API_ACCESS_TOKEN,
                "force_https": "true"
            },
            timeout=15
        )

        app.logger.info(
            "[M3U8] API status=%s content_type=%s final_url=%s size=%s",
            response.status_code,
            response.headers.get("Content-Type"),
            safe_url(response.url),
            len(response.content)
        )

        app.logger.info(
            "[M3U8] API redirects=%s",
            [
                {
                    "status": r.status_code,
                    "url": safe_url(r.url)
                }
                for r in response.history
            ]
        )

        response.raise_for_status()

        data = response.json()

        master_url = data.get("hls_mbr")

        if not master_url:
            raise RuntimeError(
                "API response does not contain hls_mbr"
            )

        if not master_url.startswith(
            "https://stream.qfilm.platform24.tv/mbrjwt/"
        ):
            raise RuntimeError(
                "Unexpected hls_mbr URL"
            )

        app.logger.info(
            "[M3U8] API returned master URL: %s",
            safe_url(master_url)
        )

        return master_url

    except Exception:

        app.logger.exception(
            "[M3U8] ERROR in get_master_url"
        )

        raise


# ==========================================
# GET MEDIA PLAYLIST
# ==========================================

def get_media_playlist():

    global CURRENT_BASE_URL

    app.logger.info(
        "[M3U8] STEP 2: Starting playlist retrieval"
    )

    try:

        master_url = get_master_url()

        app.logger.info(
            "[M3U8] STEP 3: Requesting master playlist: %s",
            safe_url(master_url)
        )

        master_response = session.get(
            master_url,
            timeout=15
        )

        app.logger.info(
            "[M3U8] MASTER status=%s content_type=%s final_url=%s size=%s",
            master_response.status_code,
            master_response.headers.get("Content-Type"),
            safe_url(master_response.url),
            len(master_response.content)
        )

        app.logger.info(
            "[M3U8] MASTER redirects=%s",
            [
                {
                    "status": r.status_code,
                    "url": safe_url(r.url)
                }
                for r in master_response.history
            ]
        )

        master_response.raise_for_status()

        app.logger.info(
            "[M3U8] MASTER first lines: %s",
            safe_playlist_sample(master_response.text)
        )

        variant_uri = None

        for line in master_response.text.splitlines():

            line = line.strip()

            if line and not line.startswith("#"):

                variant_uri = line
                break

        if not variant_uri:

            raise RuntimeError(
                "Master Playlist has no variant URI"
            )

        media_url = urljoin(
            master_response.url,
            variant_uri
        )

        base_url = urljoin(
            media_url,
            "./"
        ).rstrip("/")

        app.logger.info(
            "[M3U8] STEP 4: Variant URI=%s media URL=%s",
            safe_playlist_sample(variant_uri, limit=1),
            safe_url(media_url)
        )

        media_response = session.get(
            media_url,
            timeout=15
        )

        app.logger.info(
            "[M3U8] MEDIA status=%s content_type=%s final_url=%s size=%s",
            media_response.status_code,
            media_response.headers.get("Content-Type"),
            safe_url(media_response.url),
            len(media_response.content)
        )

        app.logger.info(
            "[M3U8] MEDIA redirects=%s",
            [
                {
                    "status": r.status_code,
                    "url": safe_url(r.url)
                }
                for r in media_response.history
            ]
        )

        media_response.raise_for_status()

        playlist_text = media_response.text

        app.logger.info(
            "[M3U8] MEDIA first lines: %s",
            safe_playlist_sample(playlist_text)
        )

        if not playlist_text.lstrip().startswith("#EXTM3U"):

            raise RuntimeError(
                "Upstream media response is not a valid M3U8 playlist"
            )

        with base_lock:

            CURRENT_BASE_URL = base_url

        app.logger.info(
            "[M3U8] STEP 5: Playlist retrieved successfully; base=%s",
            safe_url(base_url)
        )

        return playlist_text

    except Exception:

        app.logger.exception(
            "[M3U8] ERROR in get_media_playlist"
        )

        raise


# ==========================================
# INDEX
# ==========================================

@app.route("/")
def index():

    return "Irbis TV Proxy is running", 200


# ==========================================
# HEALTH
# ==========================================

@app.route("/health")
def health():

    return {
        "status": "online",
        "channel": CHANNEL_ID
    }, 200


# ==========================================
# MAIN M3U8 PLAYLIST
# ==========================================

@app.route("/irbis.m3u8")
def playlist():

    app.logger.info(
        "[M3U8] INCOMING request: method=%s path=%s remote=%s",
        request.method,
        request.path,
        request.remote_addr
    )

    try:

        app.logger.info(
            "[M3U8] STEP 0: Calling get_media_playlist"
        )

        playlist_text = get_media_playlist()

        app.logger.info(
            "[M3U8] STEP 6: Processing media playlist, lines=%s",
            len(playlist_text.splitlines())
        )

        output = []

        for line_number, line in enumerate(
            playlist_text.splitlines(),
            start=1
        ):

            line = line.strip()

            if line and not line.startswith("#"):

                match = re.fullmatch(
                    r"0/(\d+\.ts)(\?.*)?",
                    line
                )

                if not match:

                    app.logger.error(
                        "[M3U8] INVALID SEGMENT URI at line %s: %s",
                        line_number,
                        safe_playlist_sample(line, limit=1)
                    )

                    abort(502)

                segment_name = match.group(1)

                query = match.group(2) or ""

                output.append(
                    f"/irbis/{segment_name}{query}"
                )

            else:

                output.append(line)

        result = "\n".join(output) + "\n"

        app.logger.info(
            "[M3U8] SUCCESS: output lines=%s bytes=%s",
            len(output),
            len(result.encode("utf-8"))
        )

        return Response(
            result,
            content_type="application/vnd.apple.mpegurl",
            headers={
                "Cache-Control": "no-cache, no-store"
            }
        )

    except requests.RequestException:

        app.logger.exception(
            "[M3U8] UPSTREAM REQUEST ERROR"
        )

        abort(502)

    except (ValueError, KeyError, RuntimeError):

        app.logger.exception(
            "[M3U8] PLAYLIST PROCESSING ERROR"
        )

        abort(502)


# ==========================================
# TS SEGMENTS
# ==========================================

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

        app.logger.info(
            "[TS] UPSTREAM status=%s segment=%s url=%s",
            upstream.status_code,
            segment,
            safe_url(upstream.url)
        )

        # Refresh JWT if expired

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

        app.logger.exception(
            "[TS] UPSTREAM REQUEST ERROR"
        )

        abort(502)


# ==========================================
# DEBUG
# ==========================================

@app.route("/debug")
def debug():

    app.logger.warning(
        "DEBUG ROUTE WAS CALLED"
    )

    return {
        "status": "ok",
        "message": "Flask handler reached"
    }, 200


# ==========================================
# APPLICATION START
# ==========================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
