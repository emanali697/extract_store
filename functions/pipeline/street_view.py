"""
Google Street View Static API.
يجيب صورة Street View للإحداثية → تستخدم في الـ Vision Judge للمقارنة.
بيحتاج Maps Static API + Street View Static API مفعّلين على الـ GCP project.
"""
import os
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from config import GCP_CREDENTIALS

_creds = None


def get_creds():
    global _creds
    if _creds is None:
        _creds = service_account.Credentials.from_service_account_file(
            GCP_CREDENTIALS,
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
    if not _creds.valid:
        _creds.refresh(Request())
    return _creds


def fetch_street_view(lat, lng, save_path, size="640x400", heading=None,
                       fov=90, pitch=0, log_fn=print):
    """
    تنزيل صورة Street View للإحداثية.
    heading=None → نخلي Google يختار الزاوية الافتراضية.
    """
    params = {
        'location': f'{lat},{lng}',
        'size': size,
        'fov': fov,
        'pitch': pitch,
        'source': 'outdoor',
    }
    if heading is not None:
        params['heading'] = heading

    try:
        creds = get_creds()
        params['key'] = ''  # Static API uses API key not OAuth → fallback below
    except Exception:
        pass

    # Static API بيستخدم API key. نحاول قراءته من env.
    api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
    if not api_key:
        log_fn(f"  Street View skipped: GOOGLE_MAPS_API_KEY not set")
        return None
    params['key'] = api_key

    try:
        resp = requests.get(
            'https://maps.googleapis.com/maps/api/streetview',
            params=params,
            timeout=30,
        )
        if resp.status_code != 200:
            log_fn(f"  Street View HTTP {resp.status_code}: {resp.text[:120]}")
            return None

        # Google ساعات بترجع صورة "no imagery" حتى في 200
        if resp.headers.get('Content-Type', '').startswith('image/'):
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            return save_path
        return None
    except Exception as e:
        log_fn(f"  Street View error: {e}")
        return None


def check_metadata(lat, lng):
    """
    Street View Metadata API - يقول إذا كانت في صورة متاحة قبل ما نطلبها (مجاني).
    """
    api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
    if not api_key:
        return None
    try:
        resp = requests.get(
            'https://maps.googleapis.com/maps/api/streetview/metadata',
            params={'location': f'{lat},{lng}', 'key': api_key},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None
