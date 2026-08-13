import hashlib
import random
import secrets
import time
from typing import Any

REQUIRED_COOKIES = {
    "NID", "AEC", "SID", "HSID", "SSID", "APISID", "SAPISID",
    "GAPS", "_GRECAPTCHA", "__Secure-1PSID", "__Secure-1PSIDCC",
    "__Secure-3PSID", "__Secure-STRP", "__Secure-1PSIDTS",
}

# Google Zorunlu & Çekirdek Çerezler
COOKIE_TEMPLATES = [
    {"name": "NID", "domain": ".google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 6, "value_len": 160},
    {"name": "AEC", "domain": ".google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 6, "value_len": 44},
    {"name": "SID", "domain": ".google.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 50, "prefix": "g.a000"},
    {"name": "HSID", "domain": ".google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 16},
    {"name": "SSID", "domain": ".google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 16},
    {"name": "APISID", "domain": ".google.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 20, "fmt": "slash"},
    {"name": "SAPISID", "domain": ".google.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 20, "fmt": "slash"},
    {"name": "__Secure-1PSID", "domain": ".google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 50, "prefix": "g.a000"},
    {"name": "__Secure-1PSIDCC", "domain": ".google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 12, "value_len": 30},
    {"name": "__Secure-3PSID", "domain": ".google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 50, "prefix": "g.a000"},
    {"name": "GAPS", "domain": "accounts.google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 24, "fmt": "gaps"},
    {"name": "_GRECAPTCHA", "domain": "www.google.com", "path": "/recaptcha", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 6, "value_len": 60},
    {"name": "__Secure-STRP", "domain": ".google.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Strict", "ttl_months": 12, "value_len": 70},
    {"name": "__Secure-1PSIDTS", "domain": ".google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 40},
]

# Devasa Türkiye E-Ticaret, Alışveriş, Moda, Teknoloji ve Market Çerez Havuzu
OPTIONAL_COOKIE_TEMPLATES = [
    # Google Yan Çerezler
    {"name": "1P_JAR", "domain": ".google.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "None", "ttl_months": 1, "value_len": 20},
    {"name": "CONSENT", "domain": ".google.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 35, "prefix": "PENDING+"},
    {"name": "SOCS", "domain": ".google.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 12, "value_len": 40},
    {"name": "SEARCH_SAMESITE", "domain": ".google.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Strict", "ttl_months": 6, "value_len": 12},
    {"name": "SIDCC", "domain": ".google.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "None", "ttl_months": 12, "value_len": 30},
    {"name": "__Secure-3PSIDCC", "domain": ".google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 12, "value_len": 30},
    {"name": "__Secure-3PSIDTS", "domain": ".google.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 40},
    {"name": "DV", "domain": "www.google.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "None", "ttl_months": 1, "value_len": 24},

    # 1. Trendyol
    {"name": "_ga", "domain": ".trendyol.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 28, "prefix": "GA1.2."},
    {"name": "_gid", "domain": ".trendyol.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 1, "value_len": 28, "prefix": "GA1.2."},
    {"name": "sid", "domain": ".trendyol.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 12, "value_len": 40},
    {"name": "_fbp", "domain": ".trendyol.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 3, "value_len": 32, "prefix": "fb.1."},
    {"name": "storefront_id", "domain": ".trendyol.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 12, "value_len": 8},

    # 2. Hepsiburada
    {"name": "_ga", "domain": ".hepsiburada.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 28, "prefix": "GA1.2."},
    {"name": "hb_sess", "domain": ".hepsiburada.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 6, "value_len": 32},
    {"name": "_fbp", "domain": ".hepsiburada.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 3, "value_len": 32, "prefix": "fb.1."},
    {"name": "hb_visitor_id", "domain": ".hepsiburada.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 36},

    # 3. Amazon Türkiye
    {"name": "session-id", "domain": ".amazon.com.tr", "path": "/", "httpOnly": False, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 20},
    {"name": "ubid-acbtr", "domain": ".amazon.com.tr", "path": "/", "httpOnly": False, "secure": True, "sameSite": "None", "ttl_months": 24, "value_len": 20},
    {"name": "session-token", "domain": ".amazon.com.tr", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 12, "value_len": 120},
    {"name": "i18n-prefs", "domain": ".amazon.com.tr", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 3, "prefix": "TRY"},

    # 4. N11
    {"name": "_ga", "domain": ".n11.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 28, "prefix": "GA1.2."},
    {"name": "n11_sess", "domain": ".n11.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 12, "value_len": 32},
    {"name": "n11_user_city", "domain": ".n11.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 12, "value_len": 6, "prefix": "34"},

    # 5. Çiçeksepeti
    {"name": "_ga", "domain": ".ciceksepeti.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 28, "prefix": "GA1.2."},
    {"name": "cs_session", "domain": ".ciceksepeti.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 6, "value_len": 40},

    # 6. Pazarama
    {"name": "pazarama_sess", "domain": ".pazarama.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 12, "value_len": 32},
    {"name": "_ga", "domain": ".pazarama.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 28, "prefix": "GA1.2."},

    # 7. Sahibinden & Dolap
    {"name": "shb_vid", "domain": ".sahibinden.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 12, "value_len": 36},
    {"name": "dolap_sess", "domain": ".dolap.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 12, "value_len": 32},

    # 8. Teknosa, Vatan Bilgisayar, MediaMarkt
    {"name": "_ga", "domain": ".teknosa.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 28, "prefix": "GA1.2."},
    {"name": "vatan_sess", "domain": ".vatanbilgisayar.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 6, "value_len": 32},
    {"name": "mms_user", "domain": ".mediamarkt.com.tr", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 12, "value_len": 32},

    # 9. Boyner, LC Waikiki, DeFacto, Zara
    {"name": "_ga", "domain": ".boyner.com.tr", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 28, "prefix": "GA1.2."},
    {"name": "lcw_basket", "domain": ".lcwaikiki.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 3, "value_len": 24},
    {"name": "defacto_user", "domain": ".defacto.com.tr", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 12, "value_len": 24},
    {"name": "zara_cart", "domain": ".zara.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 6, "value_len": 32},

    # 10. Gratis, Watsons, Sephora
    {"name": "_ga", "domain": ".gratis.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 24, "value_len": 28, "prefix": "GA1.2."},
    {"name": "watsons_sess", "domain": ".watsons.com.tr", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 6, "value_len": 32},
    {"name": "sephora_tr", "domain": ".sephora.com.tr", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 12, "value_len": 28},

    # 11. IKEA, Koçtaş, Vivense
    {"name": "ikea_session", "domain": ".ikea.com.tr", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 6, "value_len": 32},
    {"name": "koctas_user", "domain": ".koctas.com.tr", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 12, "value_len": 24},
    {"name": "vivense_sess", "domain": ".vivense.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 6, "value_len": 32},

    # 12. Migros Sanal Market, Getir, A101, BİM
    {"name": "migros_sess", "domain": ".migros.com.tr", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 12, "value_len": 36},
    {"name": "getir_auth", "domain": ".getir.com", "path": "/", "httpOnly": True, "secure": True, "sameSite": "None", "ttl_months": 12, "value_len": 48},
    {"name": "a101_sess", "domain": ".a101.com.tr", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 6, "value_len": 32},
    {"name": "bim_aktuel", "domain": ".bim.com.tr", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 3, "value_len": 20},

    # 13. D&R, Kitapyurdu, Decathlon
    {"name": "dr_sess", "domain": ".dr.com.tr", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 6, "value_len": 32},
    {"name": "ky_user", "domain": ".kitapyurdu.com", "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax", "ttl_months": 12, "value_len": 24},
    {"name": "decathlon_tr", "domain": ".decathlon.com.tr", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax", "ttl_months": 6, "value_len": 32},
]


class SessionGenerator:
    def generate_cookie_value(self, template: dict) -> str:
        value = secrets.token_urlsafe(template["value_len"])
        fmt = template.get("fmt")
        prefix = template.get("prefix", "")

        if fmt == "gaps":
            return f"1:{secrets.token_urlsafe(24)}:{secrets.randbelow(10**10):010d}"
        if fmt == "slash":
            part_a = secrets.token_urlsafe(template["value_len"] // 2)
            part_b = secrets.token_urlsafe(template["value_len"] // 2)
            return f"{part_a}/{part_b}"
        if prefix:
            return f"{prefix}{value}"
        return value

    def generate_cookies(self, base_time: float | None = None, jitter: bool = True) -> list[dict]:
        if base_time is None:
            base_time = time.time()

        cookies = []
        templates = COOKIE_TEMPLATES.copy()
        # Her profilde 15 ila 35 arasında zengin e-ticaret ve alışveriş çerezi rastgele seçilip harmanlansın
        extra_count = random.randint(15, min(35, len(OPTIONAL_COOKIE_TEMPLATES)))
        templates.extend(random.sample(OPTIONAL_COOKIE_TEMPLATES, extra_count))

        for tmpl in templates:
            ttl_seconds = tmpl["ttl_months"] * 30 * 86400
            expires = base_time + ttl_seconds
            if jitter:
                expires += random.randint(-300, 300)

            cookies.append({
                "name": tmpl["name"],
                "value": self.generate_cookie_value(tmpl),
                "domain": tmpl["domain"],
                "path": tmpl["path"],
                "expires": round(expires, 3),
                "httpOnly": tmpl["httpOnly"],
                "secure": tmpl["secure"],
                "sameSite": tmpl["sameSite"],
            })
        return cookies

    def generate_storage_state(
        self,
        email: str,
        profile_index: int,
        keywords: list[str],
        proxy_ip: str = "",
        lifespan_days: int = 5,
        user_agent: str = "",
        device: str = "",
        fingerprint: dict | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        cookies = self.generate_cookies(base_time=now)

        token_hash = hashlib.sha256(
            cookies[0]["value"].encode() + str(profile_index).encode()
        ).hexdigest()

        # Profil bazında tutarlı fakat rastgele sektörel kelime harmanı
        rng = random.Random(profile_index * 7919)
        shuffled_kw = keywords.copy() if keywords else [
            "trendyol indirimli ürünler", "hepsiburada günün fırsatları", "amazon tr en çok satanlar",
            "n11 kuponlu ürünler", "teknosa cep telefonu fiyatları", "lc waikiki yeni sezon",
            "gratis indirimli kozmetik", "ikea tr çalışma masası", "migros sanal market sipariş"
        ]
        rng.shuffle(shuffled_kw)
        # Kelime sayısı azsa (1-3) randint(4,3) ValueError verirdi → alt/üst sınırı klample.
        n_kw = len(shuffled_kw)
        kw_count = rng.randint(min(4, n_kw), min(10, n_kw)) if n_kw else 0
        selected_kw = shuffled_kw[:kw_count]

        search_history = []
        for kw in selected_kw:
            ts = int(now) - rng.randint(60, 72 * 3600)
            search_history.append({"q": kw, "ts": ts})
        search_history.sort(key=lambda x: x["ts"])

        ds_locale_choices = ["tr"] * 90 + ["tr-TR"] * 8 + ["tr-tr"] * 2
        ds_locale = rng.choice(ds_locale_choices)

        storage_state = {
            "cookies": cookies,
            "origins": [
                {
                    "origin": "https://www.google.com",
                    "localStorage": [
                        {"name": "cse_search_history", "value": str(search_history)},
                        {"name": "sb_wiz_afs_used", "value": str(rng.randint(0, 2))},
                        {"name": "ds_locale", "value": ds_locale},
                    ],
                },
                {
                    "origin": "https://accounts.google.com",
                    "localStorage": [
                        {"name": "lara_visited", "value": "1"},
                        {"name": "gm_last_login", "value": str(int(now) - rng.randint(0, 3600))},
                    ],
                },
            ],
        }

        return {
            "profile_index": profile_index,
            "session_id": f"iu-sess-{profile_index:05d}-{token_hash[:8].upper()}",
            "token_hash": token_hash,
            "email": email,
            "proxy_ip": proxy_ip,
            "user_agent": user_agent,
            "device": device,
            # ÖMÜR: çerezi tüketen taraf bu parmak izini birebir tekrar kullanmalı
            # (aynı UA + viewport + locale + timezone + proxy). Google, oturumu doğduğundan
            # FARKLI bir kimlikle kullanılırsa güvenlik gereği sonlandırır → mismatch = erken ölüm.
            "fingerprint": fingerprint or {
                "user_agent": user_agent, "device": device, "proxy_ip": proxy_ip,
            },
            "created_at": now,
            "expires_at": now + lifespan_days * 86400,
            "cookie_count": len(cookies),
            "status": "ACTIVE",
            "storage_state": storage_state,
        }

    def validate_cookies(self, cookies: list[dict]) -> tuple[bool, set[str]]:
        cookie_names = {c["name"] for c in cookies}
        missing = REQUIRED_COOKIES - cookie_names
        return len(missing) == 0, missing
