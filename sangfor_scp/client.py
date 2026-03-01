"""
SCPClient — Sangfor Cloud Platform API ana istemcisi.

Özellikler:
  - Tek init → tek login (session hazır, her komut bekleme olmadan çalışır)
  - EC2 (AWS4-HMAC-SHA256) ve Token tabanlı auth desteği
  - Token süresi dolarsa otomatik yenileme
  - POST/PUT isteklerinde otomatik X-Client-Token (idempotency)
  - Yanıt parse, hata kodu → exception dönüşümü
  - SSL doğrulama devre dışı bırakılabilir (SCP varsayılan self-signed cert)
"""
from __future__ import annotations

import uuid
import warnings
from typing import Any, Dict, Optional

import requests
import urllib3

from sangfor_scp.auth.ec2 import EC2Signer
from sangfor_scp.auth.token import TokenAuth
from sangfor_scp.exceptions import SCPAuthError, raise_for_status


class SCPClient:
    """
    Sangfor Cloud Platform Open API istemcisi.

    EC2 Authentication (önerilen):
        client = SCPClient(
            host="10.x.x.x",
            access_key="...",
            secret_key="...",
            region="cn-south-1",
        )

    Token Authentication:
        client = SCPClient(
            host="10.x.x.x",
            username="admin",
            password="...",
        )
    """

    DEFAULT_API_VERSION = "20180725"

    def __init__(
        self,
        host: str,
        # EC2 auth
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: str = "cn-south-1",
        service: str = "open-api",
        # Token auth
        username: Optional[str] = None,
        password: Optional[str] = None,
        # Ortak
        verify_ssl: bool = False,
        timeout: int = 30,
        api_version: str = DEFAULT_API_VERSION,
    ):
        self.host = host.rstrip("/")
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.api_version = api_version

        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Auth yöntemi seç
        self._auth_method: str
        self._ec2_signer: Optional[EC2Signer] = None
        self._token_auth: Optional[TokenAuth] = None

        if access_key and secret_key:
            self._auth_method = "ec2"
            self._ec2_signer = EC2Signer(access_key, secret_key, region, service)
        elif username and password:
            self._auth_method = "token"
            self._token_auth = TokenAuth(
                host=self.host,
                username=username,
                password=password,
                verify_ssl=verify_ssl,
                timeout=timeout,
            )
        else:
            raise SCPAuthError(
                "Either (access_key + secret_key) or (username + password) must be provided."
            )

        # HTTP session — bağlantı havuzunu yeniden kullanır
        self._session = requests.Session()
        self._session.verify = verify_ssl
        self._session.headers.update({"Content-Type": "application/json"})

        # Başlangıç auth
        self._authenticate()

        # Resource'ları lazy import ile başlat (döngüsel import önlemi)
        self._init_resources()

    # ------------------------------------------------------------------ #
    # Resource erişim noktaları                                           #
    # ------------------------------------------------------------------ #

    def _init_resources(self) -> None:
        from sangfor_scp.resources.servers import ServersResource
        from sangfor_scp.resources.resource_pools import ResourcePoolsResource
        from sangfor_scp.resources.tenants import TenantsResource
        from sangfor_scp.resources.networks import NetworksResource
        from sangfor_scp.resources.images import ImagesResource
        from sangfor_scp.resources.volumes import VolumesResource
        from sangfor_scp.resources.eips import EIPsResource
        from sangfor_scp.resources.tasks import TasksResource
        from sangfor_scp.resources.system import SystemResource

        self.servers: ServersResource = ServersResource(self)
        self.resource_pools: ResourcePoolsResource = ResourcePoolsResource(self)
        self.tenants: TenantsResource = TenantsResource(self)
        self.networks: NetworksResource = NetworksResource(self)
        self.images: ImagesResource = ImagesResource(self)
        self.volumes: VolumesResource = VolumesResource(self)
        self.eips: EIPsResource = EIPsResource(self)
        self.tasks: TasksResource = TasksResource(self)
        self.system: SystemResource = SystemResource(self)

    # ------------------------------------------------------------------ #
    # Kimlik doğrulama                                                    #
    # ------------------------------------------------------------------ #

    def _authenticate(self) -> None:
        if self._auth_method == "ec2":
            self._session.auth = self._ec2_signer
        elif self._auth_method == "token":
            self._token_auth.authenticate()

    def _ensure_auth_valid(self) -> None:
        """Token tabanlı auth'da süresi dolmuşsa yenile."""
        if self._auth_method == "token" and self._token_auth.is_expired():
            self._token_auth.authenticate()

    # ------------------------------------------------------------------ #
    # Temel HTTP arayüzü                                                  #
    # ------------------------------------------------------------------ #

    def url(self, path: str) -> str:
        """
        Tam URL oluşturur.
        Path zaten /janus/... ile başlıyorsa olduğu gibi kullanılır,
        aksi hâlde /janus/{api_version}/ prefix'i eklenir.
        """
        if path.startswith("/janus/"):
            return f"{self.host}{path}"
        return f"{self.host}/janus/{self.api_version}{path}"

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        idempotent: bool = False,
        **kwargs: Any,
    ) -> Any:
        """
        Tüm API çağrılarının tek giriş noktası.

        Args:
            method:     HTTP metodu (GET, POST, PUT, DELETE)
            path:       API path (/servers, /janus/20180725/servers, vb.)
            params:     Query string parametreleri
            json:       Request body (dict → JSON)
            idempotent: True ise X-Client-Token header eklenir (POST/PUT)

        Returns:
            Başarılı yanıtın "data" alanı (veya raw dict, endpoint'e göre)

        Raises:
            SCPAuthError, SCPNotFoundError, SCPRateLimitError, vb.
        """
        self._ensure_auth_valid()

        full_url = self.url(path)

        headers: Dict[str, str] = {}

        # Token auth → Authorization header
        if self._auth_method == "token":
            headers["Authorization"] = f"Token {self._token_auth.token_id}"

        # Idempotency — POST ve PUT için otomatik X-Client-Token
        if idempotent and method.upper() in ("POST", "PUT"):
            headers["X-Client-Token"] = uuid.uuid4().hex

        # None değerli parametreleri temizle
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        resp = self._session.request(
            method=method,
            url=full_url,
            params=params or None,
            json=json,
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )

        return self._handle_response(resp)

    # ------------------------------------------------------------------ #
    # Yanıt işleme                                                        #
    # ------------------------------------------------------------------ #

    def _handle_response(self, resp: requests.Response) -> Any:
        """
        HTTP yanıtını parse eder:
        - 2xx → data alanını döndür
        - 4xx/5xx → uygun exception fırlat
        - 204 No Content → None döndür
        """
        if resp.status_code == 204:
            return None

        # Yanıt body parse
        try:
            body = resp.json()
        except ValueError:
            body = {"message": resp.text}

        if resp.status_code >= 400:
            raise_for_status(resp.status_code, body)

        # Başarılı yanıt — SCP her zaman data wrapper kullanır
        # Eski format: {"code": 0, "message": "", "data": {...}}
        # Yeni format: {"errcode": "", "message": "", "data": {...}}
        if "data" in body:
            return body["data"]

        # Bazı endpoint'ler wrapper olmadan doğrudan dict/list döner
        return body
