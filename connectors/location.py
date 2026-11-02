"""Best-effort location parsing for European job postings.

Covers country names (English and local), ISO codes in context, and the main tech-hiring
cities of each country. Unknown locations stay unknown; nothing is guessed from a company.
"""

import re
import unicodedata
from dataclasses import dataclass

COUNTRY_NAMES: dict[str, list[str]] = {
    "DE": ["germany", "deutschland"],
    "NL": ["netherlands", "the netherlands", "nederland", "holland"],
    "IE": ["ireland", "eire", "republic of ireland"],
    "SE": ["sweden", "sverige"],
    "DK": ["denmark", "danmark"],
    "FI": ["finland", "suomi"],
    "BE": ["belgium", "belgie", "belgique", "belgien"],
    "LU": ["luxembourg", "luxemburg"],
    "AT": ["austria", "osterreich"],
    "CH": ["switzerland", "schweiz", "suisse", "svizzera"],
    "FR": ["france"],
    "ES": ["spain", "espana"],
    "PT": ["portugal"],
    "IT": ["italy", "italia"],
    "PL": ["poland", "polska"],
    "CZ": ["czech republic", "czechia"],
    "NO": ["norway", "norge"],
    "EE": ["estonia", "eesti"],
    "LT": ["lithuania"],
    "LV": ["latvia"],
    "GR": ["greece"],
    "RO": ["romania"],
    "HU": ["hungary"],
    "GB": ["united kingdom", "uk", "england", "scotland", "wales", "great britain"],
}

CITIES: dict[str, list[str]] = {
    "DE": [
        "berlin",
        "munich",
        "munchen",
        "hamburg",
        "frankfurt",
        "frankfurt am main",
        "cologne",
        "koln",
        "dusseldorf",
        "stuttgart",
        "leipzig",
        "dresden",
        "hannover",
        "nuremberg",
        "nurnberg",
        "karlsruhe",
        "bonn",
        "essen",
        "dortmund",
        "bremen",
        "mannheim",
        "heidelberg",
        "walldorf",
        "potsdam",
        "garching",
        "ingolstadt",
        "aachen",
    ],
    "NL": [
        "amsterdam",
        "rotterdam",
        "the hague",
        "den haag",
        "utrecht",
        "eindhoven",
        "groningen",
        "delft",
        "leiden",
        "haarlem",
        "amstelveen",
        "hoofddorp",
        "almere",
    ],
    "IE": ["dublin", "cork", "galway", "limerick"],
    "SE": ["stockholm", "gothenburg", "goteborg", "malmo", "uppsala", "lund", "linkoping"],
    "DK": ["copenhagen", "kobenhavn", "aarhus", "odense", "aalborg"],
    "FI": ["helsinki", "espoo", "tampere", "oulu", "turku", "vantaa"],
    "BE": [
        "brussels",
        "bruxelles",
        "brussel",
        "antwerp",
        "antwerpen",
        "ghent",
        "gent",
        "leuven",
        "liege",
        "mechelen",
    ],
    "LU": ["luxembourg city", "kirchberg", "esch-sur-alzette", "belval"],
    "AT": ["vienna", "wien", "graz", "linz", "salzburg", "innsbruck"],
    "CH": ["zurich", "geneva", "geneve", "basel", "bern", "lausanne", "zug"],
    "FR": ["paris", "lyon", "toulouse", "nantes", "marseille", "lille", "bordeaux"],
    "ES": ["madrid", "barcelona", "valencia", "malaga", "seville", "sevilla", "bilbao"],
    "PT": ["lisbon", "lisboa", "porto", "braga"],
    "IT": ["milan", "milano", "rome", "roma", "turin", "torino"],
    "PL": ["warsaw", "warszawa", "krakow", "wroclaw", "gdansk", "poznan"],
    "CZ": ["prague", "praha", "brno"],
    "NO": ["oslo", "bergen", "trondheim"],
    "EE": ["tallinn", "tartu"],
    "LT": ["vilnius", "kaunas"],
    "LV": ["riga"],
    "GR": ["athens"],
    "RO": ["bucharest", "cluj-napoca", "cluj"],
    "HU": ["budapest"],
    "GB": ["london", "manchester", "edinburgh", "cambridge", "oxford", "bristol", "glasgow"],
}

EUROPE_REGION = re.compile(r"\b(europe|european union|emea|eu|eea|dach|benelux|nordics?)\b")
ISO_CODES = set(COUNTRY_NAMES)


def _fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()


_NAME_TO_CC = {name: cc for cc, names in COUNTRY_NAMES.items() for name in names}
_CITY_TO_CC = {city: cc for cc, cities in CITIES.items() for city in cities}
_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _NAME_TO_CC), key=len, reverse=True)) + r")\b"
)
_CITY_RE = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _CITY_TO_CC), key=len, reverse=True)) + r")\b"
)
_ISO_RE = re.compile(r"(?:^|[,(/|\-]\s*)([A-Z]{2})(?:\s*[),/|]|$)")


@dataclass(frozen=True)
class ParsedLocation:
    country: str | None
    city: str | None
    europe_wide: bool  # e.g. "Remote - EMEA": no single country, but in Europe


def parse_location(*values: str | None, default_country: str | None = None) -> ParsedLocation:
    """Parse one or more location strings; the first that yields a country wins."""
    europe_wide = False
    first_city: str | None = None
    for raw in values:
        if not raw:
            continue
        folded = _fold(raw)
        city_m = _CITY_RE.search(folded)
        city = city_m.group(1).title() if city_m else None
        first_city = first_city or city
        if m := _NAME_RE.search(folded):
            return ParsedLocation(_NAME_TO_CC[m.group(1)], city, False)
        if m := _ISO_RE.search(raw.strip()):
            if m.group(1) in ISO_CODES:
                return ParsedLocation(m.group(1), city, False)
        if city_m:
            # "Luxembourg" is both a city and a country; handled by the country names above.
            return ParsedLocation(_CITY_TO_CC[city_m.group(1)], city, False)
        if EUROPE_REGION.search(folded):
            europe_wide = True
    if default_country and not europe_wide:
        return ParsedLocation(default_country, first_city, False)
    return ParsedLocation(None, first_city, europe_wide)
