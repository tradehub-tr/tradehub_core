"""
TeamsLike chat servisi için Frappe proxy katmanı.

Mimari:
- Tek `istoc` tenant'ı; tüm istoc marketplace burada yaşar
- Admin user (`admin@istoc.io`): Teamslike Settings'de tutulan access token
  ile yönetim çağrıları (user create, seller listesi vs.)
- Seller'lar: ilk chat'inde otomatik provision edilen ayrı teamslike staff
  user'ı; parolası User doctype'ında encrypted alanda
- Buyer'lar: teamslike'da hesabı yok; tradehub_core tenant signing-secret
  ile imzalanmış kısa ömürlü "external identity" JWT mint eder, frontend
  bunu Bearer olarak `/v1/portal/me/*` çağrılarında kullanır

Bu modül frontend'lere şu @frappe.whitelist() metotlarını sunar:

- get_buyer_token()           → buyer'ın 60dk geçerli external JWT'si
- start_or_get_thread()       → seller_id ile buyer adına thread başlatır
- list_my_threads()           → çağıran user'ın thread listesi (rol bazlı)
- list_messages()             → bir thread'in mesajları
- send_message()              → mesaj gönder (rol bazlı: portal veya inbox)
- ensure_seller_provisioned() → admin/seller tarafından çağrılır, idempotent

Tüm dış HTTP çağrıları `requests` ile, JWT imzalama stdlib HMAC ile yapılır
(ek dependency yok).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import frappe
import requests
from frappe.utils.password import get_decrypted_password

REQUEST_TIMEOUT = 10
TOKEN_REFRESH_MARGIN_SECONDS = 60
BUYER_TOKEN_TTL_SECONDS = 3600


# ─────────────────────────────────────────────────────────────────────────────
# Settings helpers
# ─────────────────────────────────────────────────────────────────────────────


def _settings():
	s = frappe.get_single("Teamslike Settings")
	if not s.get("enabled"):
		frappe.throw("Chat servisi (Teamslike Settings) etkin değil.", frappe.PermissionError)
	if not s.get("base_url") or not s.get("tenant_slug"):
		frappe.throw("Teamslike Settings eksik (base_url / tenant_slug).", frappe.ValidationError)
	return s


def _settings_secret(s, fieldname: str) -> str:
	value = get_decrypted_password(
		"Teamslike Settings", "Teamslike Settings", fieldname, raise_exception=False
	)
	if not value:
		# Password tipindeki alan boşsa cleartext fallback (test/dev için)
		value = s.get(fieldname) or ""
	return value


def _api_url(s, path: str) -> str:
	return urljoin(s.base_url.rstrip("/") + "/", path.lstrip("/"))


# ─────────────────────────────────────────────────────────────────────────────
# JWT (HS256) — stdlib only
# ─────────────────────────────────────────────────────────────────────────────


def _b64url(b: bytes) -> str:
	return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _sign_hs256(payload: dict, secret: str) -> str:
	header = {"alg": "HS256", "typ": "JWT"}
	header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
	payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
	signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
	sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
	return f"{header_b64}.{payload_b64}.{_b64url(sig)}"


# ─────────────────────────────────────────────────────────────────────────────
# Admin token (cached + auto-refresh)
# ─────────────────────────────────────────────────────────────────────────────


def _admin_token() -> str:
	s = _settings()
	expires_at = s.get("admin_token_expires_at")
	cached = s.get("admin_access_token")
	now = datetime.now(timezone.utc).replace(tzinfo=None)
	# Frappe Datetime field'ı bazen str, bazen datetime döner — normalize et
	if isinstance(expires_at, str):
		try:
			expires_at = datetime.fromisoformat(expires_at)
		except ValueError:
			expires_at = None
	if cached and isinstance(expires_at, datetime):
		if expires_at - timedelta(seconds=TOKEN_REFRESH_MARGIN_SECONDS) > now:
			return cached
	return _refresh_admin_token(s)


def _refresh_admin_token(s) -> str:
	password = _settings_secret(s, "admin_password")
	if not password or not s.admin_email:
		frappe.throw("Admin parolası ayarlanmamış; teamslike login yapılamıyor.", frappe.ValidationError)

	r = requests.post(
		_api_url(s, "/v1/auth/login"),
		json={
			"tenant_slug": s.tenant_slug,
			"email": s.admin_email,
			"password": password,
		},
		timeout=REQUEST_TIMEOUT,
	)
	if r.status_code >= 400:
		frappe.throw(f"TeamsLike admin login başarısız: {r.status_code} {r.text}", frappe.AuthenticationError)
	data = r.json()
	token = data.get("access_token") or ""
	# Access token TTL teamslike .env'inde JWT_ACCESS_TOKEN_EXPIRE_MINUTES (default 60)
	expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=55)
	frappe.db.set_single_value("Teamslike Settings", "admin_access_token", token)
	frappe.db.set_single_value("Teamslike Settings", "admin_token_expires_at", expires_at)
	frappe.db.commit()
	return token


def _admin_headers() -> dict[str, str]:
	return {"Authorization": f"Bearer {_admin_token()}", "Content-Type": "application/json"}


# ─────────────────────────────────────────────────────────────────────────────
# Buyer JWT (external identity)
# ─────────────────────────────────────────────────────────────────────────────


def _buyer_jwt_for(user: str) -> str:
	"""Frappe user için tenant-signed external identity JWT üret."""
	s = _settings()
	signing_secret = _settings_secret(s, "signing_secret")
	if not signing_secret:
		frappe.throw("Tenant signing secret ayarlı değil.", frappe.ValidationError)

	u = frappe.db.get_value("User", user, ["email", "full_name"], as_dict=True) or {}
	now = int(time.time())
	payload = {
		"iss": s.tenant_slug,
		"sub": f"buyer_{user}",
		"email": u.get("email") or user,
		"name": u.get("full_name") or u.get("email") or user,
		"iat": now,
		"exp": now + BUYER_TOKEN_TTL_SECONDS,
	}
	return _sign_hs256(payload, signing_secret)


def _buyer_headers(user: str) -> dict[str, str]:
	return {"Authorization": f"Bearer {_buyer_jwt_for(user)}", "Content-Type": "application/json"}


# ─────────────────────────────────────────────────────────────────────────────
# Seller provisioning (idempotent)
# ─────────────────────────────────────────────────────────────────────────────


def _ensure_seller_user(seller_user: str) -> dict[str, str]:
	"""Frappe seller user'ı için teamslike staff user yarat (yoksa).

	Dönüş: {teamslike_user_id, teamslike_password}
	"""
	tl_user_id = frappe.db.get_value("User", seller_user, "teamslike_user_id")
	if tl_user_id:
		tl_password = (
			get_decrypted_password("User", seller_user, "teamslike_password", raise_exception=False) or ""
		)
		if tl_password:
			return {"teamslike_user_id": tl_user_id, "teamslike_password": tl_password}

	s = _settings()
	frappe_user = frappe.db.get_value("User", seller_user, ["email", "full_name"], as_dict=True)
	if not frappe_user:
		frappe.throw(f"Frappe user bulunamadı: {seller_user}", frappe.DoesNotExistError)

	password = secrets.token_urlsafe(24)
	full_name = frappe_user.full_name or frappe_user.email or seller_user

	r = requests.post(
		_api_url(s, "/v1/users/"),
		headers=_admin_headers(),
		json={
			"email": frappe_user.email,
			"full_name": full_name,
			"password": password,
			"role": "member",
		},
		timeout=REQUEST_TIMEOUT,
	)
	if r.status_code >= 400:
		# Email zaten kayıtlı olabilir; teamslike `/v1/users/` çoğunlukla bunu
		# unique constraint hatası ile çevirir. Bu durumda admin token ile
		# kullanıcıyı listede bulup id'sini almayı dene.
		if r.status_code in (400, 409):
			existing = _find_user_by_email(s, frappe_user.email)
			if existing:
				# Parolayı bilmiyoruz; admin reset endpoint'i şu an yok, bu yüzden
				# bu durumu açıkça raporla. Manuel müdahale gerekir.
				frappe.throw(
					f"TeamsLike'da {frappe_user.email} zaten var ama parola istoc'ta yok. "
					f"Manuel olarak rotate edilmesi gerekiyor (teamslike admin paneli).",
					frappe.ValidationError,
				)
		frappe.throw(f"TeamsLike user create başarısız: {r.status_code} {r.text}", frappe.ValidationError)

	data = r.json()
	tl_user_id = data.get("id")
	if not tl_user_id:
		frappe.throw(f"TeamsLike user response'da id yok: {data}", frappe.ValidationError)

	user_doc = frappe.get_doc("User", seller_user)
	user_doc.teamslike_user_id = tl_user_id
	user_doc.teamslike_password = password
	user_doc.teamslike_provisioned_at = frappe.utils.now()
	user_doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"teamslike_user_id": tl_user_id, "teamslike_password": password}


def _find_user_by_email(s, email: str) -> dict | None:
	r = requests.get(_api_url(s, "/v1/users/"), headers=_admin_headers(), timeout=REQUEST_TIMEOUT)
	if r.status_code >= 400:
		return None
	for u in r.json():
		if u.get("email", "").lower() == email.lower():
			return u
	return None


def _seller_token(seller_user: str) -> str:
	"""Seller user için teamslike access token al (her seferinde login).

	Not: Hızlı bir cache eklenebilir ama Frappe request lifecycle kısa olduğu
	için her çağrı bir login = 1 ekstra HTTP request kabul edilebilir.
	"""
	creds = _ensure_seller_user(seller_user)
	s = _settings()
	frappe_user = frappe.db.get_value("User", seller_user, "email")
	r = requests.post(
		_api_url(s, "/v1/auth/login"),
		json={"tenant_slug": s.tenant_slug, "email": frappe_user, "password": creds["teamslike_password"]},
		timeout=REQUEST_TIMEOUT,
	)
	if r.status_code >= 400:
		frappe.throw(
			f"Seller login başarısız ({frappe_user}): {r.status_code} {r.text}", frappe.AuthenticationError
		)
	return r.json().get("access_token", "")


def _seller_headers(seller_user: str) -> dict[str, str]:
	return {"Authorization": f"Bearer {_seller_token(seller_user)}", "Content-Type": "application/json"}


# ─────────────────────────────────────────────────────────────────────────────
# Role detection
# ─────────────────────────────────────────────────────────────────────────────


SELLER_ROLES = {"Seller", "Marketplace Seller", "Verified Seller"}


def _is_seller(user: str) -> bool:
	if user in ("Administrator", "Guest"):
		return False
	roles = set(frappe.get_roles(user))
	return bool(SELLER_ROLES & roles)


def _resolve_perspective(perspective: str | None, caller: str) -> str:
	"""perspective frontend'den explicit gelirse kullan, yoksa role'e göre belirle.

	- "buyer"  → portal/me endpoint'leri (buyer JWT)
	- "seller" → inbox endpoint'leri (seller token)
	- "auto"/None → user role'üne göre otomatik
	"""
	if perspective == "buyer":
		return "buyer"
	if perspective == "seller":
		# Seller perspektifi seçildiyse user'ın gerçekten seller olması gerek
		if not _is_seller(caller):
			frappe.throw(
				"Seller perspektifinden çağrı yapabilmek için Seller rolünde olmalısın.",
				frappe.PermissionError,
			)
		return "seller"
	# auto / default
	return "seller" if _is_seller(caller) else "buyer"


# ─────────────────────────────────────────────────────────────────────────────
# Whitelisted API
# ─────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_buyer_token() -> dict[str, Any]:
	"""Çağıran user için kısa ömürlü buyer JWT'si döner.

	Tradehubfront bunu Bearer olarak teamslike'ın `/v1/portal/me/*` çağrılarında
	doğrudan kullanabilir — ama tam proxy modelinde frontend bunu kullanmaz,
	tüm çağrılar bu modüldeki diğer endpoint'lerden gider. Burası debug ve
	gelecekteki direct-portal akışları için.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw("Önce oturum aç.", frappe.AuthenticationError)
	token = _buyer_jwt_for(user)
	return {"token": token, "expires_in": BUYER_TOKEN_TTL_SECONDS}


@frappe.whitelist()
def whoami() -> dict[str, Any]:
	"""Hangi rol bağlamında konuşacağımızı söyler (UI için)."""
	user = frappe.session.user
	return {
		"user": user,
		"role": "seller" if _is_seller(user) else "buyer",
		"is_guest": user == "Guest",
	}


def _resolve_seller_user(seller_ref: str) -> str:
	"""seller_ref farklı formatlarda gelebilir:

	- User email (içerir '@') → doğrudan döner
	- Admin Seller Profile name (slug) → profile.user'ı döner

	Frontend'de `data-seller-id` genelde supplier.id (= profile slug) olur.
	"""
	if not seller_ref:
		frappe.throw("seller_ref boş olamaz.", frappe.ValidationError)
	if "@" in seller_ref and frappe.db.exists("User", seller_ref):
		return seller_ref
	user = frappe.db.get_value("Admin Seller Profile", seller_ref, "user")
	if user:
		return user
	# Son şans: belki direkt User name'i ama @ yok (Frappe'de bazı kullanıcı isimleri email değil)
	if frappe.db.exists("User", seller_ref):
		return seller_ref
	frappe.throw(f"Seller bulunamadı: {seller_ref}", frappe.DoesNotExistError)


@frappe.whitelist()
def start_or_get_thread(seller_id: str, initial_message: str | None = None) -> dict[str, Any]:
	"""Buyer → seller thread'ini bul veya yarat. Buyer rolünden çağrılır.

	seller_id: Admin Seller Profile name veya User email/name. _resolve_seller_user
	bunu Frappe User'a çevirir. Bulunan user önce teamslike'da provision edilir
	(yoksa).

	Plus tier seller'lar için aktif rezervasyon zorunluluğu kontrol edilir;
	yoksa frappe.ValidationError fırlatılır. Frontend bu hatayı yakalayıp
	rezervasyon modal'ı açabilir.
	"""
	caller = frappe.session.user
	if caller == "Guest":
		frappe.throw("Önce oturum aç.", frappe.AuthenticationError)

	seller_user = _resolve_seller_user(seller_id)

	# Plus tier gating
	from tradehub_core.api import reservation as _res

	gate = _res.can_chat(seller_id)
	if not gate.get("allowed"):
		frappe.throw(
			gate.get("message") or "Bu satıcıyla mesajlaşmak için rezervasyon gerekli.",
			frappe.ValidationError,
		)

	# Seller'ı provision et + teamslike user_id'sini al
	creds = _ensure_seller_user(seller_user)
	tl_seller_id = creds["teamslike_user_id"]

	# Buyer olarak portal endpoint'ini çağır
	s = _settings()
	body: dict[str, Any] = {"seller_user_id": tl_seller_id}
	if initial_message:
		body["initial_message"] = initial_message
	r = requests.post(
		_api_url(s, "/v1/portal/me/threads"),
		headers=_buyer_headers(caller),
		json=body,
		timeout=REQUEST_TIMEOUT,
	)
	if r.status_code >= 400:
		frappe.throw(f"Thread create başarısız: {r.status_code} {r.text}", frappe.ValidationError)
	return r.json()


@frappe.whitelist()
def list_my_threads(perspective: str | None = None) -> list[dict[str, Any]]:
	"""Çağıran user için thread listesi.

	perspective: "buyer" → portal/me, "seller" → inbox, None/"auto" → role'e göre.
	Dual-role user'larda (hem seller hem buyer) frontend hangi modda olduğunu
	söyleyebilir.
	"""
	caller = frappe.session.user
	if caller == "Guest":
		frappe.throw("Önce oturum aç.", frappe.AuthenticationError)
	mode = _resolve_perspective(perspective, caller)
	s = _settings()
	if mode == "seller":
		r = requests.get(
			_api_url(s, "/v1/inbox/threads"), headers=_seller_headers(caller), timeout=REQUEST_TIMEOUT
		)
	else:
		r = requests.get(
			_api_url(s, "/v1/portal/me/threads"), headers=_buyer_headers(caller), timeout=REQUEST_TIMEOUT
		)
	if r.status_code >= 400:
		frappe.throw(f"Thread list başarısız: {r.status_code} {r.text}", frappe.ValidationError)
	return r.json()


@frappe.whitelist()
def list_messages(conversation_id: int | str, perspective: str | None = None) -> list[dict[str, Any]]:
	caller = frappe.session.user
	if caller == "Guest":
		frappe.throw("Önce oturum aç.", frappe.AuthenticationError)
	conv_id = int(conversation_id)
	mode = _resolve_perspective(perspective, caller)
	s = _settings()
	if mode == "seller":
		path = f"/v1/inbox/threads/{conv_id}/messages"
		headers = _seller_headers(caller)
	else:
		path = f"/v1/portal/me/threads/{conv_id}/messages"
		headers = _buyer_headers(caller)
	r = requests.get(_api_url(s, path), headers=headers, timeout=REQUEST_TIMEOUT)
	if r.status_code >= 400:
		frappe.throw(f"Mesaj listesi başarısız: {r.status_code} {r.text}", frappe.ValidationError)
	return r.json()


@frappe.whitelist()
def send_message(conversation_id: int | str, content: str, perspective: str | None = None) -> dict[str, Any]:
	caller = frappe.session.user
	if caller == "Guest":
		frappe.throw("Önce oturum aç.", frappe.AuthenticationError)
	if not content or not content.strip():
		frappe.throw("Boş mesaj gönderilemez.", frappe.ValidationError)
	conv_id = int(conversation_id)
	mode = _resolve_perspective(perspective, caller)
	frappe.logger("chat").info(
		f"send_message caller={caller} conv={conv_id} perspective_in={perspective!r} mode={mode}"
	)
	s = _settings()
	if mode == "seller":
		path = f"/v1/inbox/threads/{conv_id}/messages"
		headers = _seller_headers(caller)
	else:
		path = f"/v1/portal/me/threads/{conv_id}/messages"
		headers = _buyer_headers(caller)
	r = requests.post(_api_url(s, path), headers=headers, json={"content": content}, timeout=REQUEST_TIMEOUT)
	if r.status_code >= 400:
		frappe.throw(f"Mesaj gönderme başarısız: {r.status_code} {r.text}", frappe.ValidationError)
	return r.json()


# Buyer attachment upload — 10 MB sınırı. Tek dosya/istek; çoklu için frontend
# ardışık çağrı yapar. Sadece buyer perspektifi destekli (storefront kapsamı).
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


@frappe.whitelist()
def send_attachment(conversation_id: int | str, content: str = "") -> dict[str, Any]:
	caller = frappe.session.user
	if caller == "Guest":
		frappe.throw("Önce oturum aç.", frappe.AuthenticationError)
	conv_id = int(conversation_id)

	files = frappe.request.files if frappe.request else None
	upload = files.get("file") if files else None
	if upload is None:
		frappe.throw("Dosya bulunamadı (form alanı: 'file').", frappe.ValidationError)
	data = upload.read()
	if not data:
		frappe.throw("Boş dosya gönderilemez.", frappe.ValidationError)
	if len(data) > MAX_ATTACHMENT_BYTES:
		frappe.throw(
			f"Dosya 10 MB sınırını aşıyor ({len(data) // 1024} KB).",
			frappe.ValidationError,
		)

	filename = upload.filename or "file"
	mime = upload.mimetype or "application/octet-stream"
	# M20 fix — uzantı allowlist (yürütülebilir/aktif içerik reddi; boyut limiti zaten var).
	_ALLOWED_CHAT_EXT = (
		".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp",
		".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".zip",
	)
	if not filename.lower().endswith(_ALLOWED_CHAT_EXT):
		frappe.throw("Bu dosya türü desteklenmiyor.", frappe.ValidationError)
	frappe.logger("chat").info(
		f"send_attachment caller={caller} conv={conv_id} file={filename!r} bytes={len(data)} mime={mime}"
	)

	s = _settings()
	path = f"/v1/portal/me/threads/{conv_id}/attachments"
	headers = _buyer_headers(caller)
	# Multipart için JSON Content-Type'ı sil; requests boundary'i kendisi koyar.
	headers.pop("Content-Type", None)
	r = requests.post(
		_api_url(s, path),
		headers=headers,
		data={"content": content or ""},
		files={"file": (filename, data, mime)},
		timeout=REQUEST_TIMEOUT * 4,
	)
	if r.status_code >= 400:
		frappe.throw(f"Dosya yüklenemedi: {r.status_code} {r.text}", frappe.ValidationError)
	return r.json()


VIDEO_CALL_MARKER = "🎥"


@frappe.whitelist()
def start_video_call(conversation_id: int | str, title: str | None = None) -> dict[str, Any]:
	"""Belirtilen konuşma için yeni bir Jitsi görüntülü görüşme aç.

	Akış:
	1. Admin token ile teamslike `POST /v1/meetings/` çağırılır → moderator
	   JWT'li join_url üretilir.
	2. Thread'e otomatik bir mesaj post edilir (caller'ın perspektifinden) —
	   içerik `🎥 Görüntülü görüşme başlatıldı: <join_url>`. Polling ile diğer
	   taraf bu mesajı görür.
	3. Caller'a meeting bilgisi + join_url döner; frontend yeni sekmede açar.

	Not: İlk versiyonda hem caller hem counterpart aynı moderator URL'ini
	kullanır. Daha sıkı güvenlik için ileride per-user guest token mint edilir.
	"""
	caller = frappe.session.user
	if caller == "Guest":
		frappe.throw("Önce oturum aç.", frappe.AuthenticationError)
	conv_id = int(conversation_id)
	s = _settings()

	meeting_title = (title or "").strip() or f"Chat görüşmesi #{conv_id}"
	now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

	# 1) Meeting yarat (admin host olarak)
	r = requests.post(
		_api_url(s, "/v1/meetings/"),
		headers=_admin_headers(),
		json={
			"title": meeting_title,
			"scheduled_at": now,
			"duration_minutes": 60,
		},
		timeout=REQUEST_TIMEOUT,
	)
	if r.status_code >= 400:
		frappe.throw(f"Görüntülü görüşme yaratılamadı: {r.status_code} {r.text}", frappe.ValidationError)
	meeting = r.json()
	join_url = meeting.get("join_url") or ""  # moderator URL → caller (host)
	room_name = meeting.get("room_name") or ""
	meeting_id = meeting.get("id")

	# 1b) Karşı taraf için guest (moderator:false) join URL üret; davet linki bu olur.
	#     Böylece thread'deki 🎥 linkine tıklayan moderator olmaz; sadece caller host'tur.
	guest_join_url = ""
	if meeting_id:
		try:
			gr = requests.post(
				_api_url(s, f"/v1/meetings/{meeting_id}/guest-token"),
				headers=_admin_headers(),
				json={"guest_name": meeting_title},
				timeout=REQUEST_TIMEOUT,
			)
			if gr.status_code < 400:
				guest_join_url = gr.json().get("join_url") or ""
			else:
				frappe.log_error(f"{gr.status_code}: {gr.text}", "chat.start_video_call guest-token")
		except Exception:
			frappe.log_error(frappe.get_traceback(), "chat.start_video_call guest-token failed")
	# guest-token alınamazsa davet linkini moderator URL'e düşürmektense boş bırakmayız:
	# en azından görüşme kurulabilsin diye fallback moderator URL (eski davranış).
	invite_url = guest_join_url or join_url

	# 2) Thread'e davet mesajı at — GUEST linki paylaşılır (karşı taraf moderator olmasın).
	#    Caller kendisi return'deki moderator join_url ile host olur.
	invite_text = f"{VIDEO_CALL_MARKER} Görüntülü görüşme başlatıldı: {invite_url}"
	# Inline call — perspective None, role-based otomatik
	try:
		send_message(conversation_id=conv_id, content=invite_text)
	except Exception:
		# Mesaj post hatalıysa yine de caller URL'yi alır
		frappe.log_error(frappe.get_traceback(), "chat.start_video_call invite post failed")

	return {
		"meeting_id": meeting.get("id"),
		"room_name": room_name,
		"join_url": join_url,
		"title": meeting_title,
	}


@frappe.whitelist()
def ensure_seller_provisioned(seller_user: str | None = None) -> dict[str, Any]:
	"""Bir seller'ın teamslike provision'ı yoksa yarat. Sadece System Manager
	veya hedef seller kendisi çağırabilir. Sonuç: teamslike_user_id.
	"""
	caller = frappe.session.user
	target = seller_user or caller
	if target != caller:
		if "System Manager" not in frappe.get_roles(caller):
			frappe.throw("Yetki yok.", frappe.PermissionError)
	if not _is_seller(target):
		frappe.throw(f"{target} seller değil.", frappe.ValidationError)
	creds = _ensure_seller_user(target)
	return {"teamslike_user_id": creds["teamslike_user_id"]}


@frappe.whitelist()
def health_check() -> dict[str, Any]:
	"""TeamsLike erişilebilir mi + admin login çalışıyor mu kontrol et.

	System Manager'a aittir; settings ekranında "Test" butonu için.
	"""
	if "System Manager" not in frappe.get_roles():
		frappe.throw("Yetki yok.", frappe.PermissionError)
	s = _settings()
	try:
		r = requests.get(_api_url(s, "/health"), timeout=REQUEST_TIMEOUT)
		r.raise_for_status()
		token = _admin_token()
		me = requests.get(
			_api_url(s, "/v1/auth/me"), headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT
		)
		me.raise_for_status()
		status = "ok"
		details = me.json()
	except Exception as e:
		status = "error"
		details = {"error": str(e)}
	frappe.db.set_single_value("Teamslike Settings", "last_test_at", frappe.utils.now())
	frappe.db.set_single_value("Teamslike Settings", "last_test_status", status)
	frappe.db.commit()
	return {"status": status, "details": details}
