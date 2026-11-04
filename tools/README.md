# Screenshot intake server

A tiny upload endpoint for screenshots, for when the assistant in use cannot
receive images directly. You open the page, send a screenshot, and the server
extracts the text in it with OCR. That text is what the assistant reads.

## Why it exists

Some models are text-only. An image sent to one of them is either dropped or
never delivered at all, so a screenshot of an error message never arrives. This
server turns the picture into text first, and the text always arrives.

## Run it

```bash
pip install -r requirements.txt
sudo apt-get install -y tesseract-ocr   # the OCR engine itself
./run.sh                                 # listens on 12000
```

Open `http://<host>:12000/`, choose an image, press Upload. The extracted text
appears under the image, and the same text is available at `/feed`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | The upload page |
| `POST` | `/upload` | Multipart form, field `files`. Returns each upload with its OCR text |
| `GET` | `/feed` | Newest uploads as plain text — one call to read them all |
| `GET` | `/shots` | Newest uploads as JSON |
| `GET` | `/shots/{id}` | The stored image |
| `GET` | `/shots/{id}/text` | OCR text for one upload |
| `GET` | `/health` | Liveness, whether OCR is available, upload count |

## Reading uploads from a shell

```bash
curl -s http://localhost:12000/feed
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `12000` | Listen port |
| `SCREENSHOT_DIR` | `/tmp/screenshot-server` | Where uploads and their metadata are stored |
| `MAX_UPLOAD_MB` | `25` | Per-file size limit |
| `UPLOAD_TOKEN` | *(unset)* | When set, every route but `/health` requires `?t=<token>` |

## Security

With no `UPLOAD_TOKEN` the server is open to anyone who can reach the port: they
can upload and they can read every stored screenshot. Set a token, and put the
port behind the same access control as the rest of the deployment, unless the
only route to it is a private network.

Files are stored on disk and are not deleted on a schedule. Clear
`SCREENSHOT_DIR` when you no longer need the history.

## Tests

```bash
python -m pytest test_screenshot_server.py -q
```

The tests cover the accepted types, empty and oversized rejection, the token
gate, and reading an upload back through `/feed` and `/shots/{id}/text`. OCR
accuracy itself is not asserted, because it depends on the tesseract build.

## Checking cookies before a deployment

`check_cookies.py` validates a `cookies.txt` before it is set as `YTDLP_COOKIES`
on the downloader. A file that is malformed, exported while signed out, or
expired is accepted silently and then fails every download with the same 403 it
was meant to clear.

```bash
python3 check_cookies.py ~/Downloads/cookies.txt
cat cookies.txt | python3 check_cookies.py      # reads stdin with no argument
```

It prints the cookie counts, whether any carry a session, and a verdict, and
exits non-zero when the file will not work. Export the file from a browser
signed in to youtube.com, with the "Get cookies.txt LOCALLY" extension.
