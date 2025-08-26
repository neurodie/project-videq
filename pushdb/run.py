# scrape_luxsioab.py
import os
import json
import time
import logging
from typing import Any, Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ===== Konfigurasi (override via ENV) =====
API_URL = os.getenv("API_URL", "https://api.luxsioab.com/directory/info")
TOKEN = os.getenv("TOKEN", "017bceb5-f1d9-448b-9e00-ac140270c98b")
DIRECTORY_ID = os.getenv("DIRECTORY_ID", "a82f1dd8-c5bc-4649-bc1c-4639031e4e74")
PUBLIC_LIST_URL = os.getenv("PUBLIC_LIST_URL", "https://api.luxsioab.com/pub/api/file/page")
PUBLIC_KEY = os.getenv("PUBLIC_KEY", "QSi9UNeop/2n1gS9+rxXc3NAOu2cSQabcHwS0qeQZcM=")
TIMEOUT_MS = int(os.getenv("TIMEOUT_MS", "30000"))

OUTFILE = os.getenv("OUTFILE", "db.json")

# ===== Logging =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ===== HTTP Session dgn Retry =====
def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({"Accept": "application/json"})
    return s

def timeout_s() -> float:
    return max(1.0, TIMEOUT_MS / 1000.0)

def fetch_json(
    session: requests.Session,
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    timeout = timeout or timeout_s()
    resp = session.request(
        method=method.upper(),
        url=url,
        headers=headers,
        params=params,
        json=json_body,
        timeout=timeout,
    )
    if not resp.ok:
        # coba baca body error utk debug
        body = ""
        try:
            body = resp.text[:400]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {resp.status_code} {url} :: {body}")
    try:
        return resp.json()
    except Exception as e:
        raise RuntimeError(f"Gagal parse JSON dari {url}: {e}")

# ===== Model tipe ringan =====
def is_directory(entry: Dict[str, Any]) -> bool:
    return (entry or {}).get("file_meta", {}).get("type") == "DIRECTORY" and bool(entry.get("id"))

def map_file_item(f: Dict[str, Any]) -> Dict[str, Any]:
    """Normalisasi 1 item file publik agar fields aman & tidak kosong."""
    title = f.get("title") or f.get("name") or "(no title)"
    code = f.get("code") or None
    embed = f.get("embed_link") or None
    # Fallback thumbnail
    thumb = None
    cs = f.get("collage_screenshots") or []
    if isinstance(cs, list) and cs:
        thumb = cs[0]
    if not thumb:
        thumb = f.get("thumbnail") or None
    if not thumb:
        thumb = "https://dummyimage.com/600x338/cccccc/000000.png&text=No+Thumb"

    return {
        "title": title,
        "code": code,
        "embed": embed,
        "thumb": thumb,
    }

def fetch_all_public_files(session: requests.Session, dir_id: str) -> List[Dict[str, Any]]:
    """Ambil SEMUA halaman file publik dari PUBLIC_LIST_URL untuk 1 folder."""
    page = 1
    page_size = 100
    out: List[Dict[str, Any]] = []

    while True:
        params = {
            "key": PUBLIC_KEY,
            "page_num": str(page),
            "dir_id": dir_id,
            "page_size": str(page_size),
        }
        data = fetch_json(session, PUBLIC_LIST_URL, method="GET", params=params)
        d = (data or {}).get("data") or {}
        files = d.get("files") or []

        # Map & extend
        mapped = [map_file_item(f) for f in files]
        out.extend(mapped)

        logging.info(f"dir_id={dir_id} page={page} got={len(files)} (acc={len(out)})")
        # Jika jumlah < page_size, berarti sudah halaman terakhir
        if len(files) < page_size:
            break
        page += 1
        # kecilkan tempo agar ramah API
        time.sleep(0.15)

    return out

def main():
    session = make_session()

    # 1) Ambil daftar items di directory (type DIRECTORY saja)
    req_body = {
        "directory_id": DIRECTORY_ID,
        "page": 0,
        "size": 100,
        "sort": [],
    }
    headers = {
        "Content-Type": "application/json",
        "X-Token": TOKEN,
    }

    logging.info("Memuat daftar folder dari API_URL ...")
    try:
        dir_resp = fetch_json(session, API_URL, method="POST", headers=headers, json_body=req_body)
    except Exception as e:
        logging.error(f"Gagal ambil directory info: {e}")
        raise SystemExit(1)

    all_files = dir_resp.get("files") or []
    folders = [it for it in all_files if is_directory(it)]

    logging.info(f"Total entries: {len(all_files)} | Folders terdeteksi: {len(folders)}")

    results: List[Dict[str, Any]] = []
    for idx, item in enumerate(folders, start=1):
        dir_id = item["id"]
        name = (item.get("file_meta") or {}).get("display_name") or "(no name)"
        try:
            files = fetch_all_public_files(session, dir_id)
            results.append(
                {
                    "name": name,
                    "dir_id": dir_id,
                    "total": len(files),
                    "files": files,
                }
            )
        except Exception as e:
            logging.error(f"Gagal ambil files untuk dir_id={dir_id} ({name}): {e}")
            # tetap push entry agar struktur konsisten
            results.append(
                {
                    "name": name,
                    "dir_id": dir_id,
                    "total": 0,
                    "files": [],
                    "error": str(e),
                }
            )
        # kecilkan tempo antar folder
        time.sleep(0.2)

    payload = {
        "ok": True,
        "directory_id": DIRECTORY_ID,
        "count": len(results),
        "results": results,
    }

    # Simpan ke db.json
    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    logging.info(f"Selesai. Tersimpan ke {OUTFILE}")
    # Opsional: print ringkas ke stdout
    print(json.dumps(
        {
            "ok": True,
            "count_folders": len(results),
            "total_files_sum": sum(r.get("total", 0) for r in results),
            "outfile": OUTFILE,
        },
        ensure_ascii=False
    ))

if __name__ == "__main__":
    main()
