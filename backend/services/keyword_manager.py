SECTOR_PRESETS: dict[str, list[str]] = {
    "Alışveriş (E-Ticaret Harmanı)": [
        "trendyol indirimli ürünler", "hepsiburada günün fırsatları", "amazon tr en çok satanlar",
        "n11 kuponlu ürünler", "çiçeksepeti hediye fikirleri", "pazarama alışveriş indirimi",
        "sahibinden ikinci el temiz", "dolap alım satım", "pttavm uygun fiyatlı ürünler",
        "teknosa cep telefonu fiyatları", "vatan bilgisayar sistem toplayıcı", "mediamarkt laptop indirimleri",
        "incehesap efsane cuma", "itopya oyuncu kulaklığı", "sinerji hazır sistem",
        "lc waikiki yeni sezon", "defacto erkek giyim", "koton kadın elbise", "boyner ayakkabı fırsatları",
        "zara tr mont modelleri", "bershka ceket", "pull and bear pantolon", "stradivarius çanta",
        "mango sonbahar kreasyonu", "beymen lüks marka giyim", "morhipo indirimli saat",
        "gratis indirimli kozmetik", "watsons saç bakım ürünleri", "sephora parfüm çeşitleri",
        "ikea tr çalışma masası", "koçtaş el aletleri seti", "vivense koltuk takımı modelleri",
        "enza home yatak odası", "bauhaus bahçe mobilyaları",
        "migros sanal market sipariş", "carrefoursa gıda indirimleri", "getir büyük sipariş",
        "a101 kapıda aktüel ürünler", "bim aktüel broşürü bu hafta", "cepte şok indirimli ürünler",
        "dr çok satan romanlar", "kitapyurdu yeni çıkan kitaplar", "idefix edebiyat eserleri",
        "decathlon kamp ekipmanları", "adidas tr spor ayakkabı", "nike tr koşu ayakkabısı",
        "2026 en iyi bluetooth kulaklık tavsiye", "fiyat performans akıllı telefonlar",
        "en ucuz robot süpürge karşılaştırma", "kablosuz gaming mouse modelleri",
        "oyuncu koltuğu fiyatları en ucuz", "hava temizleme cihazı tavsiye",
        "kahve makinesi filtreli indirim", "spor çantası su geçirmez",
        "en çok satan elektronik ürünler", "günün en iyi fırsat ürünleri",
    ],
    "Pazaryerleri & Dev Siteler": [
        "trendyol indirim", "hepsiburada süper fiyatlar", "amazon tr fırsatları", "n11 kuponlar",
        "ciceksepeti aynı gün teslimat", "pazarama bonus kart fırsatları", "sahibinden araba ilanları",
        "dolap kargo bedava", "pttavm ucuz alışveriş", "modanisa muhafazakar giyim",
    ],
    "Teknoloji & Elektronik": [
        "teknosa cep telefonu kampanya", "vatan bilgisayar ekran kartı stok", "mediamarkt oled tv modelleri",
        "incehesap gaming gecesi", "itopya f/p bilgisayar", "sinerji oyuncu kasası", "turkcell pasaj taksitli telefon",
    ],
    "Moda & Giyim": [
        "lc waikiki çocuk giyim", "defacto mont kaban", "koton kadın triko", "boyner indirim çarkı",
        "zara tr elbise modelleri", "bershka jean pantolon", "mavi kot ceket", "beymen takım elbise",
    ],
    "Kozmetik & Kişisel Bakım": [
        "gratis 1 alana 1 bedava", "watsons cilt bakım kremi", "sephora orijinal parfüm",
        "rossmann organik kozmetik", "flormar ruj renkleri", "yves rocher bitkisel şampuan",
    ],
    "Ev, Yaşam & Dekorasyon": [
        "ikea tr kitaplık fiyatları", "koçtaş matkap seti", "vivense köşe koltuk",
        "enza home konsol modelleri", "english home nevresim takımı", "madame coco bornoz",
    ],
    "Süpermarket & Hızlı Teslimat": [
        "migros sanal market 100 tl indirim", "carrefoursa et fiyatları", "getir büyük kampanya",
        "a101 kapıda aktüel katalog", "bim aktüel cuma broşürü", "cepte şok ramazan kolisi",
    ],
    "Eğitim & Kitap": [
        "dr en çok okunan kitaplar", "kitapyurdu kargo bedava", "idefix sınav hazırlık",
        "bkm kitap indirim kodu", "istanbul üniversitesi aksis", "yök atlas üniversite taban puanları",
    ],
    "Araç Kiralama & Rent a Car": [
        "araç kiralama istanbul", "rent a car fiyatları", "günlük araba kiralama",
        "havalimanı araç kiralama", "ekonomik oto kiralama", "uzun dönem araç kiralama",
        "aylık araba kiralama kampanya", "şoförlü araç kiralama", "lüks araç kiralama",
        "en ucuz rent a car", "kredi kartısız araç kiralama", "genç sürücü araç kiralama",
        "suv kiralama fiyat", "enterprise rent a car türkiye", "avis araç kiralama",
        "budget oto kiralama", "sixt rent a car", "garenta araç kiralama",
        "yolcu360 araç kiralama", "otokoç filo kiralama", "sabiha gökçen araç kiralama",
        "antalya havalimanı rent a car", "izmir araba kiralama", "ankara oto kiralama",
        "haftalık araç kiralama indirim", "dizel otomatik araç kiralama", "elektrikli araç kiralama",
        "vito minibüs kiralama", "ticari araç kiralama", "depozitosuz araç kiralama",
    ],
}


class KeywordManager:
    # SINIF-seviyesi custom kelimeler: router, HER FarmingEngine ve scheduler AYNI dict'i paylaşır.
    # (Önceden __init__'te instance-başı boş _custom vardı → engine/scheduler custom kelimeleri
    #  GÖRMÜYOR, hep varsayılana düşüyordu; manuel üretim ise UI'dan custom yolluyordu → tutarsızlık.)
    _custom: dict[str, list[str]] = {}

    def get_keywords(self, sector: str) -> list[str]:
        if sector in self._custom:
            return self._custom[sector]
        return SECTOR_PRESETS.get(sector, SECTOR_PRESETS["Alışveriş (E-Ticaret Harmanı)"])

    def set_custom_keywords(self, sector: str, keywords: list[str]):
        self._custom[sector] = keywords

    def get_all_sectors(self) -> list[str]:
        sectors = list(SECTOR_PRESETS.keys())
        for s in self._custom:
            if s not in sectors:
                sectors.append(s)
        return sectors

    @classmethod
    def load_custom(cls, data: dict) -> None:
        """Redis'ten yüklenen custom kelimeleri paylaşılan dict'e koy (restart'ta korunur)."""
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    cls._custom[k] = [str(x) for x in v]

    @classmethod
    def dump_custom(cls) -> dict:
        return dict(cls._custom)
